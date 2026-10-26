"""Real runs in real containers (needs Docker and the chipova/eda-base:1 image)."""

from __future__ import annotations

import asyncio

import pytest

from chipova.domain.models import ApprovalStatus, RunStatus, SignoffStatus, StepStatus
from chipova.jobs import docker_runner, engine, flows, profiles
from chipova.services import artifacts, projects, releases, revisions, signoff
from chipova.services.actors import agent
from tests.conftest import ALICE

needs_docker = pytest.mark.skipif(
    not docker_runner.available() or profiles.installed(profiles.get("eda-base-1")) is None,
    reason="needs Docker and the chipova/eda-base:1 image",
)


async def _wait(run_id: str, timeout: float = 240) -> engine.Run:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        run = engine.get(run_id)
        if run.status.finished:
            return run
        await asyncio.sleep(0.3)
    raise AssertionError(f"run {run_id} still {engine.get(run_id).status}")


@pytest.fixture
async def queue():
    await engine.start()
    yield
    await engine.stop()
    engine._loop_task = None


@pytest.mark.docker
@needs_docker
async def test_lint_sim_synth_on_the_heartbeat(queue):
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    lint = await _wait((await engine.submit(p.id, "rtl_lint", ALICE)).id)
    assert lint.status == RunStatus.SUCCEEDED, lint.error
    assert all(s.status == StepStatus.SUCCEEDED for s in engine.steps_of(lint.id))
    sim = await _wait((await engine.submit(p.id, "rtl_sim", ALICE)).id)
    assert sim.status == RunStatus.SUCCEEDED, sim.error
    assert sim.summary["pass_lines"] == 1 and sim.summary["fail_lines"] == 0
    names = {a.name: a for a in engine.artifacts_of(sim.id)}
    assert "sim/wave.vcd" in names and len(names["sim/wave.vcd"].sha256) == 64
    manifest = engine.manifest_of(sim)
    assert manifest["revision"]["id"] == sim.revision_id and manifest["profile"]["versions"]["iverilog"].startswith("Icarus")
    assert manifest["isolation"]["network"] == "none"
    synth = await _wait((await engine.submit(p.id, "synth_yosys", ALICE)).id)
    assert synth.status == RunStatus.SUCCEEDED, synth.error
    assert synth.summary["cells"] > 0


@pytest.mark.docker
@needs_docker
async def test_a_syntax_error_fails_the_lint_with_its_line(queue):
    p = await projects.create("", "digital_heartbeat", ALICE)
    f = projects.file_by_path(p.id, "rtl/heartbeat.v")
    projects.write(p.id, f.id, projects.read(p.id, f.id).replace("count <= count + 1'b1;", "count <= count + 1'b1"), ALICE)
    await revisions.freeze(p.id, "broken", ALICE)
    run = await _wait((await engine.submit(p.id, "rtl_lint", ALICE)).id)
    assert run.status == RunStatus.FAILED
    errors = [x for x in engine.problems_of(run) if x.severity.value == "error" and x.file == "rtl/heartbeat.v"]
    assert errors and errors[0].line > 0
    assert engine.tail(run, "verilator")


@pytest.mark.docker
@needs_docker
async def test_an_ai_asking_for_synthesis_waits_for_a_person(queue):
    p = await projects.create("", "digital_heartbeat", ALICE)
    bot = agent("tester", on_behalf_of=ALICE.user)
    run = await engine.submit(p.id, "synth_yosys", bot, via="ai")
    assert run.status == RunStatus.CREATED and run.approval_status == ApprovalStatus.PROPOSED
    await asyncio.sleep(1)
    assert engine.get(run.id).status == RunStatus.CREATED  # not queued by itself
    rejected = await engine.reject(run.id, ALICE, "not now")
    assert rejected.status == RunStatus.CANCELED and "not now" in rejected.error


async def test_unknown_flows_and_parameters_are_refused_without_a_container():
    p = await projects.create("", "digital_heartbeat", ALICE)
    bot = agent("tester", on_behalf_of=ALICE.user)
    with pytest.raises(flows.FlowError):
        await engine.submit(p.id, "shell", bot, params={"cmd": "rm -rf /"})
    with pytest.raises(flows.FlowError):
        await engine.submit(p.id, "rtl_lint", bot, params={"top": "x; rm -rf /"})
    with pytest.raises(flows.FlowError):
        await engine.submit(p.id, "rtl_lint", bot, params={"extra_args": "--foo"})
    assert engine.runs_of(p.id) == []


@pytest.mark.docker
@needs_docker
async def test_a_failing_analog_run_keeps_its_log_and_nothing_says_ready(queue):
    """AC-12, as far as Chipova's analog flow goes: a deck ngspice can't run fails its run, its log
    is kept, no analog check passes, and a release of that snapshot is held at its gate."""
    p = await projects.create("Inverter", "ams_inverter", ALICE)
    deck = projects.file_by_path(p.id, "spice/inverter.spice")
    text = projects.read(p.id, deck.id)
    projects.write(p.id, deck.id, text.replace("mn out in 0 0 nmos_l1", "xmn out in 0 0 no_such_cell"), ALICE)
    rev = await revisions.freeze(p.id, "a cell that doesn't exist", ALICE)
    run = await _wait((await engine.submit(p.id, "ams_ngspice", ALICE)).id)
    assert run.status == RunStatus.FAILED and run.revision_id == rev.id, (run.status, run.error)
    logs = [a for a in engine.artifacts_of(run.id) if a.kind == "log"]
    assert logs and "no_such_cell" in artifacts.read_text(logs[0]).lower()
    checks = {c.category: c for c in signoff.checklist(p.id, rev.id)}
    assert checks["ams_pvt"].status == SignoffStatus.BLOCKED
    assert not any(c.status == SignoffStatus.PASS for c in checks.values() if c.required)
    r = releases.create(p.id, rev.id, "", ALICE)
    passed, missing = releases.gate(r)
    assert not passed and missing
    with pytest.raises((projects.Conflict, ValueError, projects.Denied)):
        releases.mark_foundry_ready(r.id, ALICE, "This is my statement that it was all checked by hand.")
