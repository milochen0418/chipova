"""Xschem and CACE in real containers (needs Docker and chipova/eda-osic): a schematic netlisted
and simulated, and a datasheet checked at every corner, passing and then failing a tighter spec."""

from __future__ import annotations

import asyncio

import pytest

from chipova.domain.models import RunStatus, SignoffStatus
from chipova.jobs import docker_runner, engine, profiles
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


def _checks(project_id: str, revision_id: str) -> dict:
    return {c.category: c for c in signoff.checklist(project_id, revision_id)}


@pytest.mark.docker
@needs_osic
async def test_ihp_inverter_meets_its_specs_at_every_corner_then_fails_a_tighter_one():
    await engine.start()
    try:
        p = await projects.create("Corners IHP", "ams_corners_ihp", ALICE)
        rev = revisions.latest(p.id)
        assert _checks(p.id, rev.id)["ams_pvt"].status == SignoffStatus.NOT_RUN
        run = await _wait((await engine.submit(p.id, "ams_cace", ALICE)).id)
        assert run.status == RunStatus.SUCCEEDED, (run.error, run.summary)
        s = run.summary
        # 5 specs (2 delays, VM, 2 noise margins) at 5 corners x 3 supplies x 3 temperatures.
        assert s["cace_status"] == "PASS" and len(s["specs"]) == 5 and all(r["status"] == "PASS" for r in s["specs"]), s
        assert s["simulations"] >= 90, s
        kinds = {a.name: a.kind for a in engine.artifacts_of(run.id)}
        assert kinds.get("pictures/xschem__inverter_tb.svg") == "schematic", kinds
        assert any(k == "plot" for k in kinds.values()) and kinds.get("results/cace_results.json") == "json", kinds
        assert _checks(p.id, rev.id)["ams_pvt"].status == SignoffStatus.PASS
        # The rising delay may now be 60 ps at most: CACE fails it, and the check says FAIL.
        f = projects.file_by_path(p.id, "cace/inverter.yaml")
        text = projects.read(p.id, f.id)
        lines = text.splitlines(keepends=True)
        at = next(i for i, line in enumerate(lines) if line.strip() == "tpd_lh:")
        cap = next(i for i in range(at, len(lines)) if lines[i].strip() == "value: 150" and lines[i - 1].strip() == "maximum:")
        lines[cap] = lines[cap].replace("150", "60")
        projects.write(p.id, f.id, "".join(lines), ALICE)
        tighter = await revisions.freeze(p.id, "tpd_lh at most 60 ps", ALICE)
        failed = await _wait((await engine.submit(p.id, "ams_cace", ALICE, revision=tighter.id)).id)
        assert failed.status == RunStatus.FAILED and failed.summary["cace_status"] == "FAIL", (failed.error, failed.summary)
        assert "tpd_lh" in failed.error and failed.summary["breaking"].get("tpd"), (failed.error, failed.summary)
        check = _checks(p.id, tighter.id)["ams_pvt"]
        assert check.status == SignoffStatus.FAIL, (check.status, check.summary)
        assert _checks(p.id, rev.id)["ams_pvt"].status == SignoffStatus.PASS, "the first snapshot keeps its own result"
        print("CACE IHP:", s["headline"], "| tighter:", failed.error)
    finally:
        await engine.stop()
        engine._loop_task = None


@pytest.mark.docker
@needs_osic
@pytest.mark.parametrize("template", ["ams_corners_sky130", "ams_corners_ihp"])
async def test_xschem_netlists_the_testbench_and_ngspice_measures_it(template: str):
    await engine.start()
    try:
        p = await projects.create("Xschem sim", template, ALICE)
        run = await _wait((await engine.submit(p.id, "ams_xschem", ALICE)).id)
        assert run.status == RunStatus.SUCCEEDED, (run.error, [(x.node, x.status) for x in engine.steps_of(run.id)])
        m = run.summary["measures"]
        assert m["tpd_hl"] > 0 and m["tpd_lh"] > 0, m
        kinds = {a.name: a.kind for a in engine.artifacts_of(run.id)}
        assert kinds.get("ams/inverter_tb.spice") == "spice" and kinds.get("pictures/xschem__inverter_tb.svg") == "schematic", kinds
        assert {"ams/transient.csv", "ams/dc_transfer.csv"} <= set(kinds), kinds
        print(template, "measures:", m)
    finally:
        await engine.stop()
        engine._loop_task = None


@pytest.mark.docker
@needs_osic
async def test_sky130_inverter_meets_its_specs_at_every_corner():
    await engine.start()
    try:
        p = await projects.create("Corners SKY130", "ams_corners_sky130", ALICE)
        run = await _wait((await engine.submit(p.id, "ams_cace", ALICE)).id, timeout=1800)
        assert run.status == RunStatus.SUCCEEDED and run.summary["cace_status"] == "PASS", (run.error, run.summary)
        print("CACE SKY130:", run.summary["headline"], run.summary["specs"])
    finally:
        await engine.stop()
        engine._loop_task = None
