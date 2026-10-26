"""What an AI may do in Chipova, offered to the AI Hub (see reflex_ddns_auth.tools).

The AI is one more member of the team with fewer rights (blueprint 7): it reads files, runs and
reports; it proposes patches that a person accepts or rejects; it freezes snapshots and asks for
runs of the allowed flows, some of which wait for a person's approval first. It can't edit
files, approve, waive or release, and there is no tool that runs a command: a run is always one
of the flows. Every call is in the audit log, refusals too. A "room" is a project's id, as in
/p/<id>. ``ctx.user`` names the AI (the agent's token, or "assistant").
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import reflex as rx
from reflex_ddns_auth.tools import ToolContext, tool

from chipova import ids
from chipova.domain import roles
from chipova.domain.models import Run, RunStatus
from chipova.jobs import engine, flows, profiles, vcd
from chipova.services import artifacts, audit, projects, proposals, revisions
from chipova.services.actors import Actor, agent

ROOM = "The project's id, as in https://chipova.reflex-ddns.com/p/<id> (chipova.list_projects lists them)."
# How long a call waits for a run. Agents give up on a call after about a minute (Claude Code
# after 60 s), while an ASIC build takes minutes: the run goes on, and the AI asks again.
WAIT = 45.0

# Told (project id, the AI's actor, what it did) so the people on the project see the AI working.
activity: Callable[[str, Actor, str], None] | None = None

GUIDE = """\
Chipova is a chip design studio that people and AIs share. A project ("room") holds Verilog or
SystemVerilog sources (rtl/), testbenches (tb/), constraints and chipova.toml, its settings (top
module, testbench, RTL and testbench files, PDK, FPGA pins).

- You never edit files yourself. chipova.propose_patch proposes the whole new text of each file
  you change; a person accepts or rejects it in the project, and chipova.proposal_status tells you
  what they decided (with their reason when they reject). Keep a patch small and focused, and say
  why and how to verify it.
- Runs take a snapshot (the files frozen), never the text being typed. chipova.freeze_snapshot
  freezes the editors' text as it is now; chipova.run runs a flow on the latest snapshot (or one
  you name) and answers with its result.
- Flows (chipova.list_flows): rtl_lint (Verilator + Icarus), rtl_sim (the testbench prints PASS
  or FAIL; the waveform is kept), synth_yosys, fpga_ice40, ams_ngspice, asic_sc (RTL to GDSII) and
  signoff checks. When the project wants a person to approve a flow an AI asks for, the run waits
  ("waiting for approval") until someone does.
- chipova.run waits up to 45 s; a longer run goes on: call chipova.get_run with wait=true. Read the
  problems (file:line), chipova.read_log for a step's output, chipova.waveform for how signals changed.
- Say only what the tools showed. A check that didn't run did not pass. Signoff (DRC, LVS, STA)
  and tape-out readiness are decided by people with the foundry's rules; you can only report.
- A good loop: chipova.read_file → chipova.propose_patch → (a person accepts: a new snapshot) →
  chipova.run rtl_lint / rtl_sim → read the problems → propose a fix.
"""


def _actor(ctx: ToolContext) -> Actor:
    return agent(ctx.user or "AI")


def _project(room: str, actor: Actor, action: str = roles.VIEW):
    room = (room or "").strip()
    if not ids.is_project(room):
        raise ValueError(f"there is no project {room!r}: chipova.list_projects lists them")
    project, _ = projects.require(room, actor, action)
    return project


def _show(room: str, actor: Actor, what: str) -> None:
    if activity is not None:
        try:
            activity(room, actor, what)
        except Exception:  # noqa: BLE001
            pass


def _audit(ctx: ToolContext, name: str, room: str, args: dict[str, Any]) -> None:
    audit.record(f"tool.{name}", _actor(ctx), room if ids.is_project(room) else "", name, args)


# ------------------------------------------------------------ reading


async def guide(ctx: ToolContext) -> dict:
    """Read this first: how Chipova works for an AI, and what it may do."""
    return {"guide": GUIDE, "flows": [f.id for f in flows.definitions()]}


async def list_projects(ctx: ToolContext) -> dict:
    """The projects this AI may see, the most recently changed first."""
    actor = _actor(ctx)
    out = []
    for p in projects.visible_to(actor.user):
        rev = revisions.latest(p.id)
        out.append({"room": p.id, "title": p.title, "kind": p.kind.value, "owner": p.owner_name, "latest_snapshot": ids.short_revision(rev.id) if rev else ""})
    return {"projects": out[:100]}


async def get_project(ctx: ToolContext, room: str) -> dict:
    """A project: its files, settings, latest snapshot, recent runs and pending proposals."""
    actor = _actor(ctx)
    p = _project(room, actor)
    settings, error, _ = projects.settings(p.id)
    rev = revisions.latest(p.id)
    working = projects.working_copy(p.id)
    return {
        "room": p.id,
        "title": p.title,
        "kind": p.kind.value,
        "files": [{"path": path, "lines": text.count("\n") + 1, "chars": len(text)} for path, text in sorted(working.items())],
        "settings": settings.model_dump(),
        "settings_error": error,
        "latest_snapshot": {"id": rev.id, "short": ids.short_revision(rev.id), "message": rev.message, "by": rev.created_by_name} if rev else None,
        "working_copy_changed_since_snapshot": revisions.differs_from_working(p.id, rev, working),
        "recent_runs": [_run_brief(r) for r in engine.runs_of(p.id, limit=10)],
        "pending_proposals": [{"proposal": a.id, "title": a.title, "by": a.agent} for a in proposals.of_project(p.id) if a.status.value == "PROPOSED"],
        "ai_may_run_without_approval": p.ai_may_run,
    }


async def read_file(ctx: ToolContext, room: str, path: str) -> dict:
    """A file's text as it is in the editors right now."""
    actor = _actor(ctx)
    p = _project(room, actor)
    text = projects.read_path(p.id, path)
    _show(p.id, actor, f"reads {path}")
    rev = revisions.latest(p.id)
    return {"room": p.id, "path": ids.clean_path(path), "text": text, "latest_snapshot": ids.short_revision(rev.id) if rev else ""}


async def history(ctx: ToolContext, room: str) -> dict:
    """The project's snapshots, newest first."""
    p = _project(room, _actor(ctx))
    return {"snapshots": [
        {"id": r.id, "short": ids.short_revision(r.id), "message": r.message, "by": r.created_by_name, "at": int(r.created_at), "files": len(r.files)}
        for r in revisions.history(p.id, 50)
    ]}


async def diff(ctx: ToolContext, room: str, old: str, new: str = "") -> dict:
    """What changed between two snapshots (ids or short hashes); without ``new``, from ``old`` to the latest."""
    p = _project(room, _actor(ctx))
    a = revisions.find(p.id, old)
    b = revisions.find(p.id, new) if new else revisions.latest(p.id)
    if a is None or b is None:
        raise ValueError("name two snapshots by id or short hash (chipova.history lists them)")
    text = await asyncio.to_thread(revisions.diff, p.id, a, b)
    return {"from": ids.short_revision(a.id), "to": ids.short_revision(b.id), "diff": text[:200_000]}


async def list_flows(ctx: ToolContext, room: str = "") -> dict:
    """The flows a run can be, their parameters, and whether their tools are installed."""
    out = []
    p = projects.get(room) if room else None
    for d in flows.definitions():
        prof = profiles.first_installed(d.profiles)
        out.append({
            "flow": d.id, "title": d.title, "category": d.category, "description": d.description,
            "params": [{"name": x.name, "kind": x.kind, "default": x.default, "choices": x.choices} for x in d.params],
            "installed": prof is not None,
            "ai_runs_without_approval": bool(p and d.id in p.ai_may_run),
        })
    return {"flows": out}


# ------------------------------------------------------------ proposing


async def propose_patch(ctx: ToolContext, room: str, title: str, changes: list[dict], rationale: str = "", plan: str = "") -> dict:
    """Proposes a change for people to accept or reject. changes = [{"path": ..., "content":
    the whole new text}] (a new path makes a file; {"path": ..., "delete": true} deletes one)."""
    actor = _actor(ctx)
    p = _project(room, actor, roles.COMMENT)
    a = proposals.propose(p.id, actor, title, changes, rationale, plan)
    _show(p.id, actor, f"proposed “{a.title}”")
    return {
        "proposal": a.id,
        "status": a.status.value,
        "files": [f["path"] for f in a.payload["files"]],
        "based_on_snapshot": ids.short_revision(a.base_revision),
        "next": "People see it in the project's AI panel and accept or reject it; chipova.proposal_status tells you which.",
    }


async def proposal_status(ctx: ToolContext, room: str, proposal: str) -> dict:
    """What people decided about a proposal (and the snapshot it made, or why it was rejected)."""
    p = _project(room, _actor(ctx))
    a = proposals.get(proposal)
    if a is None or a.project_id != p.id:
        raise ValueError(f"there is no proposal {proposal!r} in this project")
    proposals.expire_old(p.id)
    a = proposals.get(proposal)
    return {
        "proposal": a.id, "title": a.title, "status": a.status.value, "decided_by": a.decided_by_name,
        "reason": a.reason, "snapshot": a.applied_revision, "snapshot_short": ids.short_revision(a.applied_revision),
    }


async def freeze_snapshot(ctx: ToolContext, room: str, message: str) -> dict:
    """Freezes the files as they are in the editors now, as a snapshot runs can take."""
    actor = _actor(ctx)
    p = _project(room, actor, roles.SNAPSHOT)
    rev = await revisions.freeze(p.id, message, actor)
    _show(p.id, actor, f"froze snapshot {ids.short_revision(rev.id)}")
    return {"snapshot": rev.id, "short": ids.short_revision(rev.id), "message": rev.message}


# ------------------------------------------------------------ running


def _run_brief(r: Run) -> dict:
    return {"run": r.id, "flow": r.flow_id, "status": _status(r), "snapshot": ids.short_revision(r.revision_id), "by": r.requested_by_name}


def _status(r: Run) -> str:
    if r.status == RunStatus.CREATED and r.approval_status.value == "PROPOSED":
        return "WAITING_FOR_APPROVAL"
    return r.status.value


def _run_view(r: Run) -> dict:
    found = engine.problems_of(r)
    out: dict[str, Any] = {
        "run": r.id,
        "flow": r.flow_id,
        "status": _status(r),
        "snapshot": r.revision_id,
        "snapshot_short": ids.short_revision(r.revision_id),
        "params": r.params,
        "error": r.error,
        "summary": r.summary,
        "problems": r.problems,
        "first_problems": [
            {"severity": x.severity.value, "file": x.file, "line": x.line, "column": x.column, "code": x.code, "message": x.message[:300], "step": x.step}
            for x in found[:40]
        ],
        "steps": [{"step": s.node, "title": s.title, "status": s.status.value, "exit_code": s.exit_code} for s in engine.steps_of(r.id)],
        "artifacts": [{"name": a.name, "kind": a.kind, "sha256": a.sha256, "bytes": a.size} for a in engine.artifacts_of(r.id) if a.kind != "log"],
    }
    if r.status == RunStatus.QUEUED:
        out["queue_position"] = engine.queue_position(r)
    return out


async def _wait(run_id: str, seconds: float) -> Run:
    end = time.monotonic() + seconds
    r = engine.get(run_id)
    while r is not None and not r.status.finished and not (r.status == RunStatus.CREATED) and time.monotonic() < end:
        await asyncio.sleep(0.5)
        r = engine.get(run_id)
    return r  # type: ignore[return-value]


async def run(ctx: ToolContext, room: str, flow: str, revision: str = "", params: dict | None = None) -> dict:
    """Runs a flow on a snapshot (the latest when not named) and answers with its result, waiting
    up to 45 s; a run that takes longer goes on (chipova.get_run with wait=true)."""
    actor = _actor(ctx)
    p = _project(room, actor, roles.RUN)
    r = await engine.submit(p.id, flow, actor, revision=revision, params=params or {}, via="ai")
    _show(p.id, actor, f"started {flow} on {ids.short_revision(r.revision_id)}")
    if r.status == RunStatus.CREATED:
        return {**_run_view(r), "next": "This flow waits for a person to approve it when an AI asks: they see it in the project's Runs; call chipova.get_run later."}
    r = await _wait(r.id, WAIT)
    view = _run_view(r)
    if not r.status.finished:
        view["next"] = "Still running: call chipova.get_run with wait=true to wait for it."
    return view


async def get_run(ctx: ToolContext, room: str, run: str, wait: bool = False) -> dict:
    """A run's status, steps, problems, numbers and artifacts (waiting up to 45 s for it to end
    when wait is true)."""
    p = _project(room, _actor(ctx))
    r = engine.get(run)
    if r is None or r.project_id != p.id:
        raise ValueError(f"there is no run {run!r} in this project")
    if wait and not r.status.finished:
        r = await _wait(r.id, WAIT)
    return _run_view(r)


async def cancel_run(ctx: ToolContext, room: str, run: str) -> dict:
    """Stops a run that is waiting or running."""
    actor = _actor(ctx)
    p = _project(room, actor, roles.RUN)
    r = engine.get(run)
    if r is None or r.project_id != p.id:
        raise ValueError(f"there is no run {run!r} in this project")
    r = await engine.cancel(r.id, actor)
    return {"run": r.id, "status": _status(r)}


async def read_log(ctx: ToolContext, room: str, run: str, step: str = "", lines: int = 200) -> dict:
    """The last lines of a run's output (one step's, or all of them)."""
    p = _project(room, _actor(ctx))
    r = engine.get(run)
    if r is None or r.project_id != p.id:
        raise ValueError(f"there is no run {run!r} in this project")
    lines = max(10, min(int(lines or 200), 2000))
    return {"run": r.id, "step": step, "lines": engine.tail(r, step, lines)}


async def waveform(ctx: ToolContext, room: str, run: str, signals: list[str] | None = None) -> dict:
    """How signals changed in a simulation run's waveform: each one's first changes (time, value;
    buses in hex). Without signals, the testbench's top-level ones."""
    p = _project(room, _actor(ctx))
    r = engine.get(run)
    if r is None or r.project_id != p.id:
        raise ValueError(f"there is no run {run!r} in this project")
    wave = next((a for a in engine.artifacts_of(r.id) if a.kind == "vcd"), None)
    if wave is None:
        raise ValueError("this run kept no waveform (rtl_sim runs do)")
    w = await asyncio.to_thread(vcd.load, artifacts.file_of(wave))
    names = signals or [s.name for s in w.signals if s.name.count(".") <= 1][:20]
    return {"run": r.id, "timescale": w.timescale, "end": w.end, "signals": vcd.summary(w, names)}


def _audited(name: str, fn, writes: bool = False):  # noqa: ANN001, ANN202
    """A tool every call of which leaves a line in the audit log: a reading tool's here, a writing
    tool's from the service it calls (a proposal, a run); refusals of runs and permissions come
    from the services too, and this catches the rest (bad paths, say)."""
    import functools

    @functools.wraps(fn)
    async def wrapper(ctx: ToolContext, *args, **kwargs):  # noqa: ANN002, ANN003
        room = str(kwargs.get("room", ""))
        try:
            result = await fn(ctx, *args, **kwargs)
        except (flows.FlowError, projects.Denied):
            raise
        except Exception as e:
            audit.record(f"tool.{name}", _actor(ctx), room if ids.is_project(room) else "", name, {k: v for k, v in kwargs.items() if k != "changes"},
                         decision="denied" if isinstance(e, (ValueError, projects.NotFound)) else "error", detail=f"{type(e).__name__}: {e}")
            raise
        if not writes:
            _audit(ctx, name, room, kwargs)
        return result

    return wrapper


def register(app: rx.App) -> None:
    """Offers Chipova's tools on ``app``'s backend."""
    tool(app, "chipova.guide", title="How Chipova works for an AI")(_audited("chipova.guide", guide))
    tool(app, "chipova.list_projects", title="List the projects")(_audited("chipova.list_projects", list_projects))
    tool(app, "chipova.get_project", title="Look at a project", params={"room": ROOM})(_audited("chipova.get_project", get_project))
    tool(app, "chipova.read_file", title="Read a file", params={"room": ROOM, "path": "The file's path in the project, e.g. rtl/heartbeat.v."})(_audited("chipova.read_file", read_file))
    tool(app, "chipova.history", title="List the snapshots", params={"room": ROOM})(_audited("chipova.history", history))
    tool(app, "chipova.diff", title="Compare snapshots", params={"room": ROOM, "old": "A snapshot (id or short hash).", "new": "Another one (default: the latest)."})(_audited("chipova.diff", diff))
    tool(app, "chipova.list_flows", title="List the flows", params={"room": ROOM})(_audited("chipova.list_flows", list_flows))
    tool(
        app, "chipova.propose_patch", title="Propose a change", kind="write",
        params={
            "room": ROOM,
            "title": "What the change does, in a few words.",
            "changes": 'The files: [{"path": "rtl/x.v", "content": "<the whole new text>"}], or {"path": ..., "delete": true}.',
            "rationale": "Why: what is wrong now and how this fixes it.",
            "plan": "How to check it: the runs to do and what they should show.",
        },
    )(_audited("chipova.propose_patch", propose_patch, writes=True))
    tool(app, "chipova.proposal_status", title="What people decided", params={"room": ROOM, "proposal": "The proposal's id (ap-…)."})(_audited("chipova.proposal_status", proposal_status))
    tool(app, "chipova.freeze_snapshot", title="Freeze a snapshot", kind="write", params={"room": ROOM, "message": "What the snapshot is."})(_audited("chipova.freeze_snapshot", freeze_snapshot, writes=True))
    tool(
        app, "chipova.run", title="Run a flow", kind="write",
        params={
            "room": ROOM,
            "flow": "The flow's id (chipova.list_flows): rtl_lint, rtl_sim, synth_yosys, fpga_ice40, ams_ngspice, asic_sc, …",
            "revision": "The snapshot (id or short hash); the latest when left out.",
            "params": "The flow's parameters (chipova.list_flows); left out, they come from chipova.toml.",
        },
    )(_audited("chipova.run", run, writes=True))
    tool(app, "chipova.get_run", title="Look at a run", params={"room": ROOM, "run": "The run's id (run-…).", "wait": "Wait up to 45 s for it to end."})(_audited("chipova.get_run", get_run))
    tool(app, "chipova.cancel_run", title="Stop a run", kind="write", params={"room": ROOM, "run": "The run's id (run-…)."})(_audited("chipova.cancel_run", cancel_run, writes=True))
    tool(app, "chipova.read_log", title="Read a run's output", params={"room": ROOM, "run": "The run's id.", "step": "One step's (default: all).", "lines": "How many of the last lines (10 to 2000)."})(_audited("chipova.read_log", read_log))
    tool(app, "chipova.waveform", title="Read a waveform", params={"room": ROOM, "run": "A simulation run's id.", "signals": "Signal names (tb.dut.count or count); default: the testbench's own."})(_audited("chipova.waveform", waveform))
