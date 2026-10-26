"""Full chip in a real container (needs Docker and chipova/eda-osic; about 5 minutes and 3 GB):
JKU's IHP chip template built from scratch with the project's sources and checked, and the Full
chip check, which says what passed and why that isn't PASS."""

from __future__ import annotations

import asyncio

import pytest

from chipova.domain.models import RunStatus, SignoffStatus, StepStatus
from chipova.jobs import docker_runner, engine, flows_asic, profiles
from chipova.services import projects, revisions, signoff
from tests.conftest import ALICE

needs_osic = pytest.mark.skipif(
    not docker_runner.available() or profiles.installed(profiles.get("iic-osic-2026.10")) is None,
    reason="needs Docker and the chipova/eda-osic:2026.10-3 image",
)


async def _wait(run_id: str, timeout: float) -> engine.Run:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        run = engine.get(run_id)
        if run.status.finished:
            return run
        await asyncio.sleep(2)
    raise AssertionError(f"run {run_id} still {engine.get(run_id).status}")


@pytest.mark.docker
@needs_osic
async def test_the_ihp_chip_is_built_and_checked_but_never_passes():
    flows_asic.register()
    await engine.start()
    try:
        p = await projects.create("Chip", "ams_chip_ihp", ALICE)
        run = await _wait((await engine.submit(p.id, "fullchip_ihp", ALICE)).id, timeout=3600)
        steps = {s.node: s.status for s in engine.steps_of(run.id)}
        for node, status in steps.items():
            if status == StepStatus.FAILED:
                print(f"--- {node} ---", *engine.tail(run, node, 40), sep="\n")
        assert run.status == RunStatus.SUCCEEDED, (run.error, steps)
        assert all(v == StepStatus.SUCCEEDED for v in steps.values()), steps
        s = run.summary
        # 32 pads, 7 macros (counter, inverters, logos), clean chip DRC and gate-level LVS, timing met.
        assert s["io_count"] == 32 and s["macros"] == 7 and s["chip_drc_violations"] == 0 and s["lvs_errors"] == 0, s
        assert s["setup_slack_ns"] > 0 and s["hold_slack_ns"] > 0 and s["failed_parts"] == [], s
        kinds = {a.name: a.kind for a in engine.artifacts_of(run.id)}
        assert kinds.get("chip/chip_top.gds.gz") == "gds" and kinds.get("chip/ihp130.lyp") == "lyp", kinds
        check = {c.category: c for c in signoff.checklist(p.id, revisions.latest(p.id).id)}["fullchip"]
        assert check.status == SignoffStatus.BLOCKED and check.run_id == run.id and "top-level LVS" in check.why, (check.status, check.why)
        print("Full chip:", s["headline"], "| setup", s["setup_slack_ns"], "ns | template", s["template"])
    finally:
        await engine.stop()
        engine._loop_task = None
