"""Runs, from asking to the evidence they leave.

    submit ─► CREATED ─(no approval needed, or a person approved)─► QUEUED ─► RUNNING ─► SUCCEEDED
                │                                                                    ├► FAILED
                └─(an AI asked for a flow the project doesn't let it run alone)       ├► CANCELED
                   approval PROPOSED, until a person approves or rejects it          └► TIMED_OUT

A run always runs one snapshot (never the working copy) with one flow, in a container of the
first installed tool profile of that flow (:mod:`chipova.jobs.profiles`). At most
``CHIPOVA_MAX_PARALLEL_RUNS`` (2) run at once, the others wait in the queue in order.

While it runs, its output is followed live (``tail``); the runner's markers move its steps
through their states. When it ends, everything it wrote under /work/out is copied into
``<project>/runs/<run>/out``, its artifacts are recorded with their SHA-256, the tools' problems
are read from the logs, the flow's numbers are worked out, and ``manifest.json`` records exactly
what went in (snapshot, settings, parameters, image, tool versions, argv) and what came out.

The engine survives a restart of the app (a dev reload does that often): runs still RUNNING are
followed again from their container, which kept running, or failed when it is gone.
"""

from __future__ import annotations

import asyncio
import collections
import fnmatch
import hashlib
import json
import logging
import os
import platform
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from chipova import ids, paths
from chipova.db import db
from chipova.domain import machines, roles
from chipova.domain.models import ApprovalStatus, Artifact, Problem, Run, RunStatus, RunStep, Severity, StepStatus
from chipova.jobs import docker_runner, flows, parsers, profiles
from chipova.services import audit, projects, revisions, settings_file
from chipova.services.actors import Actor

logger = logging.getLogger(__name__)

MAX_PARALLEL = int(os.environ.get("CHIPOVA_MAX_PARALLEL_RUNS", "2") or 2)
MAX_WAITING_PER_PERSON = 20
RUNNER = Path(__file__).parent / "container" / "runner.py"
MARK = "@@chipova "

# Told (project id, run id) whenever a run or one of its steps changes state.
listeners: list[Callable[[str, str], None]] = []


@dataclass
class _Live:
    lines: collections.deque = field(default_factory=lambda: collections.deque(maxlen=4000))
    step: str = ""
    cancel_by: str = ""
    container: Any = None


_live: dict[str, _Live] = {}
_tasks: dict[str, asyncio.Task] = {}
_wake: asyncio.Event | None = None
_loop_task: asyncio.Task | None = None


# ------------------------------------------------------------ records


def get(run_id: str) -> Run | None:
    if not ids.is_run(run_id):
        return None
    row = db().one("SELECT * FROM runs WHERE id = ?", (run_id,))
    return Run.from_row(row) if row else None


def runs_of(project_id: str, limit: int = 50, flow_id: str = "", revision_id: str = "") -> list[Run]:
    sql, args = "SELECT * FROM runs WHERE project_id = ?", [project_id]
    if flow_id:
        sql += " AND flow_id = ?"
        args.append(flow_id)
    if revision_id:
        sql += " AND revision_id = ?"
        args.append(revision_id)
    rows = db().query(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit))
    return [Run.from_row(r) for r in rows]


def steps_of(run_id: str) -> list[RunStep]:
    rows = db().query("SELECT * FROM run_steps WHERE run_id = ? ORDER BY idx", (run_id,))
    return [RunStep.from_row(r) for r in rows]


def artifacts_of(run_id: str) -> list[Artifact]:
    rows = db().query("SELECT * FROM artifacts WHERE run_id = ? ORDER BY name", (run_id,))
    return [Artifact.from_row(r) for r in rows]


def problems_of(run: Run) -> list[Problem]:
    path = paths.run_dir(run.project_id, run.id) / "problems.json"
    try:
        return [Problem.model_validate(p) for p in json.loads(path.read_text("utf-8"))]
    except (OSError, ValueError):
        return []


def out_dir(run: Run) -> Path:
    return paths.run_dir(run.project_id, run.id) / "out"


def tail(run: Run, step: str = "", lines: int = 400) -> list[str]:
    """The last lines of a run's output (a step's, or all of it), live while it runs."""
    live = _live.get(run.id)
    if live is not None and not run.status.finished:
        picked = [text for s, text in live.lines if not step or s == step]
        return picked[-lines:]
    if step:
        return _last_lines(out_dir(run) / "steps" / step / "stdout.log", lines)
    out: list[str] = []
    for s in steps_of(run.id):
        log = out_dir(run) / "steps" / s.node / "stdout.log"
        if log.is_file():
            out.append(f"── {s.title or s.node} ──")
            out.extend(_last_lines(log, lines))
    return out[-lines:]


def _last_lines(path: Path, n: int) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 400_000))
            data = fh.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()[-n:]


def _notify(project_id: str, run_id: str) -> None:
    for fn in list(listeners):
        try:
            fn(project_id, run_id)
        except Exception:  # noqa: BLE001
            logger.exception("A run listener failed")


def _set(run_id: str, **fields: Any) -> None:
    db().update("runs", {"id": run_id}, fields)


def _move(run: Run, new: RunStatus, **fields: Any) -> Run:
    machines.check_run(run.status, new, run.approval_status)
    _set(run.id, status=new.value, **fields)
    return get(run.id)  # type: ignore[return-value]


# ------------------------------------------------------------ asking for a run


def _snapshot_inputs(project_id: str, revision) -> tuple[Any, list[str]]:  # noqa: ANN001
    try:
        text = revisions.show(project_id, revision, settings_file.FILE).decode("utf-8")
    except RuntimeError:
        text = ""
    settings, error = settings_file.parse(text)
    if error:
        raise flows.FlowError(f"the snapshot's settings don't parse: {error}")
    return settings, [e["path"] for e in revision.files]


def _context(run: Run, flow: flows.Flow, revision, profile_id: str) -> flows.Context:  # noqa: ANN001
    settings, files = _snapshot_inputs(run.project_id, revision)
    source = get(run.source_run) if run.source_run else None
    source_files: dict[str, Path] = {}
    if source is not None:
        for a in artifacts_of(source.id):
            source_files[a.name] = out_dir(source) / a.name
    return flows.Context(revision=revision, settings=settings, files=files, params=run.params, profile_id=profile_id, source_run=source, source_files=source_files)


async def submit(
    project_id: str,
    flow_id: str,
    actor: Actor,
    revision: str = "",
    params: dict | None = None,
    via: str = "ui",
    source_run: str = "",
) -> Run:
    """Asks for a run of ``flow_id`` on a snapshot (its id or short hash; "" = the latest).
    Refuses (FlowError, projects.Denied) anything the flow doesn't allow; the refusal is audited
    and no container is made."""
    project, _ = projects.require(project_id, actor, roles.RUN, flow_id)
    args = {"flow": flow_id, "revision": revision, "params": params or {}, "source_run": source_run}
    try:
        flow = flows.get(flow_id)
        if flow is None:
            raise flows.FlowError(f"there is no flow {flow_id!r}; the flows are: {', '.join(flows.FLOWS)}")
        if not flow.definition.enabled:
            raise flows.FlowError(f"{flow.definition.title} is not enabled: {flow.definition.disabled_reason}")
        rev = revisions.find(project_id, revision) if revision else revisions.latest(project_id)
        if rev is None:
            raise flows.FlowError(f"there is no snapshot {revision!r}: freeze one first" if revision else "the project has no snapshot yet: freeze one first")
        if flow.needs_source:
            src = get(source_run)
            if src is None or src.project_id != project_id or src.flow_id != flow.needs_source or src.status != RunStatus.SUCCEEDED:
                raise flows.FlowError(f"{flow.definition.title} checks the outputs of a succeeded {flow.needs_source} run: give its id")
            if src.revision_id != rev.id:
                rev = revisions.get(project_id, src.revision_id) or rev
        settings, files = _snapshot_inputs(project_id, rev)
        checked = flows.check_params(flow, params or {}, settings, files)
        profile = profiles.first_installed(flow.definition.profiles)
        if profile is None:
            names = ", ".join(p.title for p in (profiles.get(i) for i in flow.definition.profiles) if p)
            raise flows.FlowError(f"{flow.definition.title} needs a tool profile that isn't installed ({names}): install one on the Settings page")
        waiting = db().one("SELECT COUNT(*) AS n FROM runs WHERE requested_by = ? AND status IN ('CREATED', 'QUEUED')", (actor.user,))
        if waiting and waiting["n"] >= MAX_WAITING_PER_PERSON:
            raise flows.FlowError(f"{actor.name} already has {waiting['n']} runs waiting: let some finish first")
    except (flows.FlowError, projects.Denied) as e:
        audit.denied("run.submit", actor, project_id, flow_id, str(e), args)
        raise
    approval = ApprovalStatus.PROPOSED if actor.is_agent and flow_id not in project.ai_may_run else ApprovalStatus.NONE
    now = time.time()
    run = Run(
        id=ids.new_run_id(),
        project_id=project_id,
        revision_id=rev.id,
        flow_id=flow_id,
        flow_version=flow.definition.version,
        profile_id=profile.id,
        params=checked,
        status=RunStatus.CREATED,
        approval_status=approval,
        requested_by=actor.user,
        requested_by_name=actor.name,
        requested_via=via,
        source_run=source_run if flow.needs_source else "",
        created_at=now,
        image=profile.image,
    )
    try:
        spec = flow.build(_context(run, flow, rev, profile.id))
    except flows.FlowError as e:
        audit.denied("run.submit", actor, project_id, flow_id, str(e), args)
        raise
    db().insert("runs", run.model_dump(mode="json"))
    for i, step in enumerate(spec.steps):
        db().insert("run_steps", {
            "run_id": run.id, "idx": i, "node": step.id, "title": step.title, "status": StepStatus.PENDING.value,
            "command": step.argv, "command_digest": hashlib.sha256(json.dumps(step.argv).encode()).hexdigest() if step.argv else "",
        })
    audit.record("run.submit", actor, project_id, run.id, {**args, "params": checked, "approval": approval.value})
    if approval == ApprovalStatus.NONE:
        run = _move(run, RunStatus.QUEUED, queued_at=time.time())
        _poke()
    _notify(project_id, run.id)
    return run


async def approve(run_id: str, actor: Actor) -> Run:
    run = _must(run_id)
    projects.require(run.project_id, actor, roles.APPROVE_RUN, run_id)
    if run.approval_status != ApprovalStatus.PROPOSED:
        raise flows.FlowError(f"this run doesn't wait for an approval ({run.approval_status.value})")
    if actor.user == run.requested_by:
        raise projects.Denied("who asked for a run can't approve it")
    machines.check(machines.APPROVAL, run.approval_status, ApprovalStatus.APPROVED)
    _set(run_id, approval_status=ApprovalStatus.APPROVED.value, approval_by=actor.user, approval_at=time.time())
    run = _move(get(run_id), RunStatus.QUEUED, queued_at=time.time())  # type: ignore[arg-type]
    audit.record("run.approve", actor, run.project_id, run_id)
    _poke()
    _notify(run.project_id, run_id)
    return run


async def reject(run_id: str, actor: Actor, reason: str = "") -> Run:
    run = _must(run_id)
    projects.require(run.project_id, actor, roles.APPROVE_RUN, run_id)
    if run.approval_status != ApprovalStatus.PROPOSED:
        raise flows.FlowError(f"this run doesn't wait for an approval ({run.approval_status.value})")
    machines.check(machines.APPROVAL, run.approval_status, ApprovalStatus.REJECTED)
    _set(run_id, approval_status=ApprovalStatus.REJECTED.value, approval_by=actor.user, approval_at=time.time())
    run = _move(get(run_id), RunStatus.CANCELED, ended_at=time.time(), error=f"Rejected by {actor.name}" + (f": {reason}" if reason else ""))  # type: ignore[arg-type]
    audit.record("run.reject", actor, run.project_id, run_id, {"reason": reason})
    _notify(run.project_id, run_id)
    return run


async def cancel(run_id: str, actor: Actor) -> Run:
    run = _must(run_id)
    projects.require(run.project_id, actor, roles.RUN, run_id)
    if run.status in (RunStatus.CREATED, RunStatus.QUEUED):
        run = _move(run, RunStatus.CANCELED, ended_at=time.time(), error=f"Canceled by {actor.name}")
    elif run.status == RunStatus.RUNNING:
        live = _live.setdefault(run_id, _Live())
        live.cancel_by = actor.name
        container = live.container or await asyncio.to_thread(docker_runner.find, run_id)
        if container is not None:
            await asyncio.to_thread(docker_runner.stop, container)
    audit.record("run.cancel", actor, run.project_id, run_id)
    _notify(run.project_id, run_id)
    return get(run_id)  # type: ignore[return-value]


def _must(run_id: str) -> Run:
    run = get(run_id)
    if run is None:
        raise projects.NotFound(f"there is no run {run_id!r}")
    return run


# ------------------------------------------------------------ the queue


def _poke() -> None:
    if _wake is not None:
        _wake.set()


async def start() -> None:
    """Starts the queue (app start): follows again the runs a restart left running."""
    global _wake, _loop_task
    if _loop_task is not None and not _loop_task.done():
        return
    _wake = asyncio.Event()
    for row in db().query("SELECT id FROM runs WHERE status = 'RUNNING'"):
        run = get(row["id"])
        if run is not None:
            _tasks[run.id] = asyncio.create_task(_execute(run, again=True))
    _loop_task = asyncio.create_task(_scheduler())
    await asyncio.to_thread(docker_runner.remove_stale_probes)


async def stop() -> None:
    """The app stops: the queue stops taking runs; containers keep running and are followed
    again at the next start."""
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _loop_task = None
    for task in list(_tasks.values()):
        task.cancel()


async def _scheduler() -> None:
    while True:
        try:
            await asyncio.wait_for(_wake.wait(), timeout=3)  # type: ignore[union-attr]
        except asyncio.TimeoutError:
            pass
        _wake.clear()  # type: ignore[union-attr]
        try:
            free = MAX_PARALLEL - len([t for t in _tasks.values() if not t.done()])
            if free <= 0:
                continue
            rows = db().query("SELECT id FROM runs WHERE status = 'QUEUED' ORDER BY queued_at LIMIT ?", (free,))
            for row in rows:
                run = get(row["id"])
                if run is not None and run.id not in _tasks:
                    _tasks[run.id] = asyncio.create_task(_execute(run))
        except Exception:  # noqa: BLE001
            logger.exception("The run queue failed")


def queue_position(run: Run) -> int:
    if run.status != RunStatus.QUEUED:
        return 0
    row = db().one("SELECT COUNT(*) AS n FROM runs WHERE status = 'QUEUED' AND queued_at < ?", (run.queued_at,))
    return (row["n"] if row else 0) + 1


# ------------------------------------------------------------ running one


async def _execute(run: Run, again: bool = False) -> None:
    live = _live.setdefault(run.id, _Live())
    loop = asyncio.get_running_loop()
    try:
        flow = flows.get(run.flow_id)
        rev = revisions.get(run.project_id, run.revision_id)
        profile = profiles.get(run.profile_id)
        if flow is None or rev is None or profile is None:
            raise RuntimeError("its flow, snapshot or tool profile is gone")
        spec = flow.build(_context(run, flow, rev, profile.id))
        container = None
        if again:
            container = await asyncio.to_thread(docker_runner.find, run.id)
            if container is None:
                await _finish(run, RunStatus.FAILED, error="The run's container is gone (the app restarted while it ran)")
                return
        else:
            run = _move(run, RunStatus.RUNNING, started_at=time.time())
            _notify(run.project_id, run.id)
            # The image's tool versions, read once per image (a hand-built one too).
            await asyncio.to_thread(profiles.versions_of, profile)
            job = {
                "run": run.id,
                "env": spec.env,
                "steps": [s.job() for s in spec.steps if not s.virtual],
            }
            src = await asyncio.to_thread(revisions.archive, run.project_id, rev)
            scripts = {f"job/{k}": v for k, v in spec.scripts.items()}
            scripts["runner.py"] = RUNNER.read_bytes()
            scripts["job.json"] = json.dumps(job, indent=1).encode()
            workspace = await asyncio.to_thread(docker_runner.workspace_tar, src, scripts, spec.inputs)
            container = await asyncio.to_thread(docker_runner.create, run.id, run.project_id, profile.image, spec.limits, workspace)
            rec = profiles.record(profile.id)
            _set(run.id, container=container.name, image=profile.image, image_digest=rec.get("image_id", "") or (docker_runner.image_info(profile.image) or {}).get("id", ""))
            await asyncio.to_thread(container.start)
        live.container = container
        stop_follow = threading.Event()

        def on_line(line: str) -> None:
            loop.call_soon_threadsafe(_on_line, run, live, line)

        follower = threading.Thread(target=docker_runner.follow, args=(container, on_line, stop_follow), daemon=True)
        follower.start()
        started = run.started_at or time.time()
        remaining = max(5.0, spec.limits.timeout - (time.time() - started))
        code = await asyncio.to_thread(docker_runner.wait, container, remaining)
        timed_out = code is None
        if timed_out:
            await asyncio.to_thread(docker_runner.stop, container)
            await asyncio.to_thread(docker_runner.wait, container, 30)
        await asyncio.to_thread(follower.join, 10)
        stop_follow.set()
        run = get(run.id)  # type: ignore[assignment]
        await _collect(run, spec, container, code, timed_out, live)
    except asyncio.CancelledError:
        raise  # the app stops: the container goes on, and the next start follows it again
    except Exception as e:  # noqa: BLE001
        logger.exception("Run %s failed to run", run.id)
        current = get(run.id)
        if current is not None and not current.status.finished:
            await _finish(current, RunStatus.FAILED, error=f"Chipova couldn't run it: {e}")
            if live.container is not None:
                await asyncio.to_thread(docker_runner.remove, live.container)
    finally:
        _tasks.pop(run.id, None)
        _poke()


def _on_line(run: Run, live: _Live, line: str) -> None:
    if line.startswith(MARK):
        parts = line[len(MARK):].split()
        if len(parts) >= 2:
            kind, node = parts[0], parts[1]
            now = time.time()
            if kind == "step-start":
                live.step = node
                db().update("run_steps", {"run_id": run.id, "node": node}, {"status": StepStatus.RUNNING.value, "started_at": now})
            elif kind == "step-end":
                rc = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else -1
                status = StepStatus.SUCCEEDED if rc == 0 else StepStatus.FAILED
                fields = {"status": status.value, "ended_at": now, "exit_code": rc}
                # The runner timed the step: the log comes in bursts, so arrival times aren't it.
                try:
                    fields["started_at"] = now - float(parts[3])
                except (IndexError, ValueError):
                    pass
                db().update("run_steps", {"run_id": run.id, "node": node}, fields)
            elif kind == "step-skip":
                db().update("run_steps", {"run_id": run.id, "node": node}, {"status": StepStatus.SKIPPED.value})
            elif kind in ("node-start", "node-end"):
                # A node of the tool's own flow (step/index), shown as a virtual step.
                step, _, index = node.rpartition("/")
                vid = f"sc.{step}.{index or '0'}"
                if kind == "node-start":
                    db().update("run_steps", {"run_id": run.id, "node": vid}, {"status": StepStatus.RUNNING.value, "started_at": now})
                else:
                    db().update("run_steps", {"run_id": run.id, "node": vid}, {"status": StepStatus.SUCCEEDED.value, "ended_at": now})
            _notify(run.project_id, run.id)
        return
    if line == "" and live.lines and live.lines[-1][1] == "":
        return
    live.lines.append((live.step, line))


async def _collect(run: Run, spec: flows.JobSpec, container, code: int | None, timed_out: bool, live: _Live) -> None:  # noqa: ANN001
    rdir = paths.run_dir(run.project_id, run.id)
    out = rdir / "out"
    error = ""
    try:
        await asyncio.to_thread(docker_runner.fetch_out, container, out)
    except Exception as e:  # noqa: BLE001
        error = f"Its outputs couldn't be copied out: {e}"
    await asyncio.to_thread(docker_runner.remove, container)
    live.container = None
    result = _read_json(out / "result.json")
    step_results = {s["id"]: s for s in (result.get("steps") or [])}
    steps = steps_of(run.id)
    virtual = {st.id for st in spec.steps if st.virtual}
    # Steps the runner never reached (stopped, timed out) are canceled.
    for s in steps:
        if s.node in virtual:
            continue
        r = step_results.get(s.node)
        if r is None:
            if s.status in (StepStatus.PENDING, StepStatus.RUNNING):
                db().update("run_steps", {"run_id": run.id, "node": s.node}, {"status": StepStatus.CANCELED.value})
        else:
            db().update("run_steps", {"run_id": run.id, "node": s.node}, {
                "status": r["status"], "exit_code": r.get("exit_code"),
                "started_at": r.get("started", 0) or 0, "ended_at": r.get("ended", 0) or 0,
            })
    steps = steps_of(run.id)
    spec_steps = {s.id: s for s in spec.steps}
    # Problems, step by step, from the tools' own logs.
    found: list[Problem] = []
    for s in steps:
        log = out / "steps" / s.node / "stdout.log"
        if log.is_file() and s.node in spec_steps:
            text = log.read_bytes().decode("utf-8", errors="replace").splitlines()
            found.extend(parsers.problems(spec_steps[s.node].tool, s.node, text))
    (rdir / "problems.json").write_text(json.dumps([p.model_dump(mode="json") for p in found], indent=1), "utf-8")
    counts = {
        "errors": sum(1 for p in found if p.severity == Severity.ERROR),
        "warnings": sum(1 for p in found if p.severity == Severity.WARNING),
    }
    summary = _metrics(run, out, steps)
    for s in steps:
        if s.node in summary.get("_steps", {}):
            db().update("run_steps", {"run_id": run.id, "node": s.node}, {"metrics": summary["_steps"][s.node]})
    summary.pop("_steps", None)
    arts = await asyncio.to_thread(_register_artifacts, run, out, spec)
    # The verdict: every required step succeeded, and no testbench said FAIL/ERROR.
    required_failed = [
        s.node for s in steps
        if s.status != StepStatus.SUCCEEDED and s.node in spec_steps and not spec_steps[s.node].optional and not spec_steps[s.node].virtual
    ]
    verdict_failed = run.flow_id == "rtl_sim" and summary.get("fail_lines", 0) > 0
    if live.cancel_by:
        status, error = RunStatus.CANCELED, error or f"Canceled by {live.cancel_by}"
    elif timed_out:
        status, error = RunStatus.TIMED_OUT, error or f"Stopped after {spec.limits.timeout} s, its time limit"
    elif error or required_failed or verdict_failed or code is None:
        status = RunStatus.FAILED
        if not error:
            error = summary.get("error_text") or (
                "The testbench reported a failure" if verdict_failed and not required_failed else f"Failed in: {', '.join(required_failed)}"
            )
    else:
        status = RunStatus.SUCCEEDED
    run = get(run.id)  # type: ignore[assignment]
    await _finish(run, status, error=error, exit_code=code, summary=summary, problems=counts, artifacts=arts, spec=spec)


async def _finish(run: Run, status: RunStatus, error: str = "", exit_code: int | None = None, summary: dict | None = None,
                  problems: dict | None = None, artifacts: list[Artifact] | None = None, spec: flows.JobSpec | None = None) -> None:
    fields: dict[str, Any] = {"ended_at": time.time(), "error": error}
    if exit_code is not None:
        fields["exit_code"] = exit_code
    if summary is not None:
        fields["summary"] = summary
    if problems is not None:
        fields["problems"] = problems
    run = _move(run, status, **fields)
    try:
        await asyncio.to_thread(write_manifest, run, artifacts or artifacts_of(run.id), spec)
    except Exception:  # noqa: BLE001
        logger.exception("Writing the manifest of %s failed", run.id)
    audit.record("run.end", None, run.project_id, run.id, {"status": status.value, "error": error})
    _live.pop(run.id, None)
    _notify(run.project_id, run.id)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _register_artifacts(run: Run, out: Path, spec: flows.JobSpec) -> list[Artifact]:
    picked: dict[str, str] = {}
    for f in sorted(out.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(out).as_posix()
        if rel.startswith("steps/") and rel.endswith("/stdout.log"):
            picked[rel] = "log"
            continue
        for pattern, kind in spec.artifacts:
            if fnmatch.fnmatch(rel, pattern):
                picked.setdefault(rel, kind)
    db().execute("DELETE FROM artifacts WHERE run_id = ?", (run.id,))
    out_list = []
    now = time.time()
    for rel, kind in picked.items():
        f = out / rel
        a = Artifact(id=ids.new_id("af"), run_id=run.id, project_id=run.project_id, kind=kind, name=rel, sha256=_sha256(f), size=f.stat().st_size, created_at=now)
        db().insert("artifacts", a.model_dump(mode="json"))
        out_list.append(a)
    return out_list


def _metrics(run: Run, out: Path, steps: list[RunStep]) -> dict:
    """The flow's numbers (and the steps' own under "_steps")."""
    summary: dict[str, Any] = {"_steps": {}}

    def log_lines(node: str) -> list[str]:
        p = out / "steps" / node / "stdout.log"
        return p.read_bytes().decode("utf-8", errors="replace").splitlines() if p.is_file() else []

    if run.flow_id == "rtl_sim":
        lines = log_lines("run")
        verdict = parsers.sim_verdict(lines)
        summary.update(verdict)
        for line in lines:
            if "$finish called at" in line:
                summary["finished_at"] = line.split("$finish called at", 1)[1].strip()
        summary["_steps"]["run"] = verdict
    elif run.flow_id == "synth_yosys":
        stat = out / "synth" / "stat.json"
        if stat.is_file():
            s = parsers.yosys_stat(stat.read_text("utf-8"))
            summary.update({k: v for k, v in s.items() if k != "cell_types"})
            summary["cell_types"] = s.get("cell_types", {})
            summary["_steps"]["yosys"] = {k: v for k, v in s.items() if k != "cell_types"}
    elif run.flow_id == "fpga_ice40":
        rep = out / "fpga" / "report.json"
        if rep.is_file():
            r = parsers.nextpnr_report(rep.read_text("utf-8"))
            summary.update(r)
            summary["_steps"]["pnr"] = r
    elif run.flow_id == "ams_ngspice":
        m = parsers.spice_measures(log_lines("ngspice"))
        summary["measures"] = m
        summary["_steps"]["ngspice"] = m
        summary["tables"] = sorted(p.name for p in (out / "ams").glob("*.csv")) if (out / "ams").is_dir() else []
    from chipova.jobs import flows_asic  # noqa: PLC0415 — the ASIC flows add their own numbers

    flows_asic.metrics(run, out, summary)
    return summary


def write_manifest(run: Run, artifacts: list[Artifact], spec: flows.JobSpec | None = None) -> Path:
    """``manifest.json``: what went into the run and what came out (blueprint 9.2, 13)."""
    rev = revisions.get(run.project_id, run.revision_id)
    project = projects.get(run.project_id)
    profile = profiles.get(run.profile_id)
    rec = profiles.record(run.profile_id) if profile else {}
    steps = steps_of(run.id)
    settings = None
    if rev is not None:
        try:
            settings, _ = settings_file.parse(revisions.show(run.project_id, rev, settings_file.FILE).decode("utf-8"))
        except RuntimeError:
            pass
    out = out_dir(run)
    manifest = {
        "schema": "chipova.run-manifest/1",
        "run": {
            "id": run.id, "flow": run.flow_id, "flow_version": run.flow_version, "status": run.status.value,
            "requested_by": run.requested_by, "requested_via": run.requested_via,
            "approval": {"status": run.approval_status.value, "by": run.approval_by, "at": run.approval_at},
            "created_at": run.created_at, "started_at": run.started_at, "ended_at": run.ended_at,
            "exit_code": run.exit_code, "error": run.error, "source_run": run.source_run,
        },
        "project": {"id": run.project_id, "title": project.title if project else ""},
        "revision": {
            "id": run.revision_id, "git_commit": rev.git_commit if rev else "", "source_sha": rev.source_sha if rev else "",
            "files": rev.files if rev else [],
        },
        "settings": settings.model_dump() if settings else None,
        "params": run.params,
        "profile": {
            "id": run.profile_id, "image": run.image, "image_id": run.image_digest or rec.get("image_id", ""),
            "base": profile.base if profile else "", "base_digest": rec.get("digest", ""), "versions": rec.get("versions", {}),
        },
        "limits": spec.limits.__dict__ if spec else None,
        "isolation": {"network": "none", "user": docker_runner.JOB_USER, "capabilities": "all dropped", "no_new_privileges": True},
        "steps": [
            {
                "id": s.node, "title": s.title, "argv": s.command, "command_digest": s.command_digest,
                "status": s.status.value, "exit_code": s.exit_code, "started_at": s.started_at, "ended_at": s.ended_at,
                "metrics": s.metrics,
            }
            for s in steps
        ],
        "artifacts": [{"id": a.id, "name": a.name, "kind": a.kind, "sha256": a.sha256, "size": a.size} for a in artifacts],
        "summary": run.summary,
        "problems": run.problems,
        "host": {"platform": platform.platform(), "python": platform.python_version()},
    }
    path = paths.run_dir(run.project_id, run.id) / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, sort_keys=False, default=str), "utf-8")
    if out.is_dir():
        pass
    return path


def manifest_of(run: Run) -> dict:
    return _read_json(paths.run_dir(run.project_id, run.id) / "manifest.json")


def compare(a: Run, b: Run) -> list[dict]:
    """What differs between two runs' inputs and outputs (blueprint AC-06)."""
    ma, mb = manifest_of(a), manifest_of(b)
    rows = []

    def row(what: str, va: Any, vb: Any) -> None:
        rows.append({"what": what, "a": va, "b": vb, "same": va == vb})

    row("Snapshot", ma.get("revision", {}).get("id"), mb.get("revision", {}).get("id"))
    row("Flow", f"{a.flow_id} v{a.flow_version}", f"{b.flow_id} v{b.flow_version}")
    row("Parameters", ma.get("params"), mb.get("params"))
    row("Settings", ma.get("settings"), mb.get("settings"))
    row("Image", ma.get("profile", {}).get("image_id"), mb.get("profile", {}).get("image_id"))
    va, vb = ma.get("profile", {}).get("versions", {}), mb.get("profile", {}).get("versions", {})
    for tool in sorted(set(va) | set(vb)):
        row(f"{tool} version", va.get(tool), vb.get(tool))
    # The numbers each run reported: a build's PPA (cells, area, slack, Fmax, power…).
    labels = {**(b.summary or {}).get("_labels", {}), **(a.summary or {}).get("_labels", {})}
    na, nb = _numbers(a.summary), _numbers(b.summary)
    for key in sorted(set(na) | set(nb)):
        row(labels.get(key, key), na.get(key), nb.get(key))
    aa = {x["name"]: x["sha256"] for x in ma.get("artifacts", []) if x.get("kind") != "log"}
    ab = {x["name"]: x["sha256"] for x in mb.get("artifacts", []) if x.get("kind") != "log"}
    for name in sorted(set(aa) | set(ab)):
        row(f"Artifact {name}", (aa.get(name) or "")[:12], (ab.get(name) or "")[:12])
    return rows


def _numbers(summary: dict | None) -> dict:
    """A run summary's single values (not its headline, error text or tables)."""
    return {
        k: v for k, v in (summary or {}).items()
        if not k.startswith("_") and k not in ("headline", "error_text") and isinstance(v, (int, float, str)) and not isinstance(v, bool)
    }
