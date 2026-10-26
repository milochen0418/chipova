"""RTL to GDSII and its layout checks, in real containers (needs Docker and chipova/eda-osic)."""

from __future__ import annotations

import asyncio

import pytest

from chipova.domain.models import RunStatus, SignoffStatus, StepStatus
from chipova.jobs import docker_runner, engine, flows, flows_asic, profiles
from chipova.services import projects, revisions, signoff
from tests.conftest import ALICE

needs_osic = pytest.mark.skipif(
    not docker_runner.available() or profiles.installed(profiles.get("iic-osic-2026.10")) is None,
    reason="needs Docker and the chipova/eda-osic:2026.10-3 image",
)


async def _wait(run_id: str, timeout: float = 900) -> engine.Run:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        run = engine.get(run_id)
        if run.status.finished:
            return run
        await asyncio.sleep(1)
    raise AssertionError(f"run {run_id} still {engine.get(run_id).status}")


@pytest.mark.docker
@needs_osic
async def test_heartbeat_to_gds_then_drc_and_lvs():
    flows_asic.register()
    await engine.start()
    try:
        p = await projects.create("Beat ASIC", "digital_heartbeat", ALICE)
        asic = await _wait((await engine.submit(p.id, "asic_sc", ALICE)).id)
        assert asic.status == RunStatus.SUCCEEDED, asic.error
        s = asic.summary
        assert s["cells"] > 50 and s["setup_slack_ns"] > 0 and s["fmax_mhz"] > 50, s
        names = {a.name: a.kind for a in engine.artifacts_of(asic.id)}
        assert names.get("asic/final/heartbeat.full.gds") == "gds" and names.get("asic/final/heartbeat.vg") == "netlist", names
        nodes = [x for x in engine.steps_of(asic.id) if x.node.startswith("sc.")]
        assert len(nodes) >= 20 and all(x.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for x in nodes), [(x.node, x.status) for x in nodes]
        assert engine.tail(asic, "sc.place.global.0"), "the node's log is readable"
        pdk_data = engine.manifest_of(asic)["profile"]["versions"].get("pdk-data", "")
        assert "open_pdks=" in pdk_data and "lambdapdk-v" in pdk_data, pdk_data
        rev = revisions.get(p.id, asic.revision_id)
        checks = {c.category: c for c in signoff.checklist(p.id, rev.id)}
        # The build's own timing is one corner with estimated parasitics: STA waits for the signoff run.
        assert checks["sta"].status == SignoffStatus.NOT_RUN and checks["drc"].status == SignoffStatus.NOT_RUN
        drc = await _wait((await engine.submit(p.id, "signoff_drc", ALICE, source_run=asic.id)).id)
        lvs = await _wait((await engine.submit(p.id, "signoff_lvs", ALICE, source_run=asic.id)).id)
        sign = await _wait((await engine.submit(p.id, "signoff_openroad", ALICE, source_run=asic.id)).id)
        assert sign.status == RunStatus.SUCCEEDED, (sign.error, sign.summary)
        found = sign.summary["checks"]
        assert set(found) == {"pex", "sta", "power_ir", "antenna"} and all(c["pass"] for c in found.values()), found
        assert set(found["pex"]["corners"]) == {"min", "nom", "max"} and set(found["sta"]["corners"]) == {"slow", "typical", "fast"}, found
        assert sign.summary["setup_slack_ns"] > 0 and sign.summary["hold_slack_ns"] > 0 and sign.summary["antenna_violations"] == 0, sign.summary
        names = {a.name for a in engine.artifacts_of(sign.id)}
        assert {"signoff/pex/heartbeat.nom.spef", "signoff/sta/sta.json", "signoff/antenna/antenna.rpt"} <= names, names
        assert lvs.status == RunStatus.SUCCEEDED and lvs.summary["lvs_pass"], (lvs.error, lvs.summary)
        # KLayout's manufacturing deck flags the met3 area at the out pin (m3.6) on this layout.
        assert "violations" in drc.summary, (drc.error, drc.summary)
        checks = {c.category: c for c in signoff.checklist(p.id, rev.id)}
        assert checks["lvs"].status == SignoffStatus.PASS
        for c in ("sta", "pex", "power", "antenna"):
            assert checks[c].status == SignoffStatus.PASS and checks[c].run_id == sign.id, (c, checks[c].status, checks[c].summary)
        print("signoff:", sign.summary.get("headline"), "|", checks["sta"].summary, "|", checks["power"].summary)
        assert checks["drc"].status == (SignoffStatus.PASS if drc.summary["violations"] + drc.summary.get("magic_violations", 0) == 0 else SignoffStatus.FAIL)
        print("DRC:", drc.summary.get("headline"), drc.summary.get("rules"), "| LVS:", lvs.summary.get("final_result"), "| ASIC:", s.get("headline"))
    finally:
        await engine.stop()
        engine._loop_task = None


@pytest.mark.docker
@needs_osic
async def test_a_restarted_backend_follows_a_running_build_to_its_end():
    """The backend stops while a build runs (a redeploy, a crash): its container goes on, and the
    next start follows the same container to the end and collects its results."""
    flows_asic.register()
    await engine.start()
    try:
        p = await projects.create("Beat restart", "digital_heartbeat", ALICE)
        run = await engine.submit(p.id, "asic_sc", ALICE)
        end = asyncio.get_running_loop().time() + 120
        while not (engine.get(run.id).status == RunStatus.RUNNING and engine.get(run.id).container):
            assert asyncio.get_running_loop().time() < end, engine.get(run.id).status
            await asyncio.sleep(0.5)
        await asyncio.sleep(8)
        await engine.stop()
        engine._loop_task = None
        assert engine.get(run.id).status == RunStatus.RUNNING
        assert docker_runner.find(run.id) is not None, "the container goes on without the backend"
        await engine.start()
        done = await _wait(run.id)
        assert done.status == RunStatus.SUCCEEDED, done.error
        assert "asic/final/heartbeat.full.gds" in {a.name for a in engine.artifacts_of(done.id)}
        assert docker_runner.find(run.id) is None, "the finished container is removed"
    finally:
        await engine.stop()
        engine._loop_task = None


async def _signoff(pdk_id: str, rules_at_least: int, rc_corners: set[str]) -> None:
    """Build ASIC on ``pdk_id``, then its DRC, LVS and OpenROAD checks: all clean on the heartbeat."""
    flows_asic.register()
    await engine.start()
    try:
        p = await projects.create(f"Beat {pdk_id}", "digital_heartbeat", ALICE)
        run = await _wait((await engine.submit(p.id, "asic_sc", ALICE, params={"pdk": pdk_id})).id)
        assert run.status == RunStatus.SUCCEEDED, run.error
        assert run.summary["pdk"] == pdk_id and run.summary["cells"] > 0, run.summary
        assert "asic/final/heartbeat.full.gds" in {a.name for a in engine.artifacts_of(run.id)}
        drc = await _wait((await engine.submit(p.id, "signoff_drc", ALICE, source_run=run.id)).id)
        lvs = await _wait((await engine.submit(p.id, "signoff_lvs", ALICE, source_run=run.id)).id)
        sign = await _wait((await engine.submit(p.id, "signoff_openroad", ALICE, source_run=run.id)).id)
        assert drc.status == RunStatus.SUCCEEDED and drc.summary["violations"] == 0, (drc.error, drc.summary)
        assert drc.summary["rules_checked"] >= rules_at_least, drc.summary
        # A block has no fill: the chip-level density rules miss, shown and not counted.
        assert drc.summary["density_rules_missed"] > 0 and drc.summary["density"]["layers"], drc.summary
        assert lvs.status == RunStatus.SUCCEEDED and lvs.summary["lvs_pass"], (lvs.error, lvs.summary)
        assert sign.status == RunStatus.SUCCEEDED, (sign.error, sign.summary)
        assert set(sign.summary["checks"]["pex"]["corners"]) == rc_corners, sign.summary["checks"]["pex"]
        rev = revisions.get(p.id, run.revision_id)
        checks = {c.category: c for c in signoff.checklist(p.id, rev.id)}
        for c in ("drc", "lvs", "sta", "pex", "power", "antenna"):
            assert checks[c].status == SignoffStatus.PASS, (c, checks[c].status, checks[c].summary, checks[c].why)
        print(f"{pdk_id}:", run.summary.get("headline"), "| DRC:", drc.summary.get("headline"), drc.summary["rules_checked"], "rules",
              "| LVS:", lvs.summary.get("final_result"), "|", sign.summary.get("headline"), "|", checks["sta"].summary)
    finally:
        await engine.stop()
        engine._loop_task = None


@pytest.mark.docker
@needs_osic
async def test_heartbeat_signs_off_on_ihp_sg13g2():
    """IHP SG13G2: its own KLayout DRC (main rules) and LVS decks, Magic DRC, and the OpenROAD checks
    (one RC corner: IHP ships one OpenRCX deck)."""
    await _signoff("ihp130", 500, {"nom"})


@pytest.mark.docker
@needs_osic
async def test_heartbeat_signs_off_on_gf180():
    """GF180MCU: built offline with the baked SiliconCompiler data, the open_pdks KLayout DRC deck,
    Magic/Netgen LVS, and the OpenROAD checks at lambdapdk's three RC corners."""
    await _signoff("gf180", 500, {"min", "nom", "max"})
