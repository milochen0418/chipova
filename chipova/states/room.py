"""A project's room: what everybody on /p/<id> sees change live, pushed to all of them.

``ProjectRoom`` is a Reflex ``SharedState``: every tab on a project links its state to the
project's id. The files' text is not in it (it travels in the co-edited documents,
:mod:`chipova.services.collab`); the room carries what the page draws with Reflex: the file
list, the runs and their states, the AI's proposals, the latest snapshot and whether the editors
have changed since, the people here, the call, and the recent activity.

Anything that changes these (a run's step, a proposal, a saved file, someone arriving) calls
:func:`push_later`, which gathers the changes of a moment into one push per project.
"""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import logging
import time

import reflex as rx
from reflex_ddns_auth import rooms

from chipova import ids
from chipova.domain.models import Run, RunStatus
from chipova.jobs import engine, flows
from chipova.services import collab, presence, projects, proposals, revisions, templates

logger = logging.getLogger(__name__)

PUSH_DELAY = 0.25
ACTIVITY = 60


@dataclasses.dataclass
class FileRow:
    id: str = ""  # "" for a folder
    path: str = ""
    name: str = ""
    folder: str = ""
    depth: int = 0
    lang: str = ""
    editing: str = ""  # who has it open
    kind: str = "file"  # file | folder


@dataclasses.dataclass
class SnapRow:
    id: str = ""
    short: str = ""
    message: str = ""
    by: str = ""
    at: float = 0.0


@dataclasses.dataclass
class RunRow:
    id: str = ""
    flow: str = ""
    title: str = ""
    category: str = ""
    status: str = ""  # a RunStatus, or WAITING (for a person's approval)
    snapshot: str = ""
    by: str = ""
    via: str = ""
    created: float = 0.0
    started: float = 0.0
    ended: float = 0.0
    errors: int = 0
    warnings: int = 0
    summary: str = ""
    error: str = ""
    active: bool = False


@dataclasses.dataclass
class ProposalRow:
    id: str = ""
    title: str = ""
    agent: str = ""
    status: str = ""
    created: float = 0.0
    files: str = ""
    rationale: str = ""
    plan: str = ""
    base: str = ""
    decided_by: str = ""
    reason: str = ""
    applied: str = ""


@dataclasses.dataclass
class NoteRow:
    """A note pinned on a layout (µm, in the layout's own coordinates)."""

    id: str = ""
    artifact: str = ""
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    who: str = ""
    at: float = 0.0


@dataclasses.dataclass
class CommentRow:
    """A comment on a file's line (or a run, a snapshot), for everyone in the project."""

    id: str = ""
    kind: str = ""  # file | run | revision
    path: str = ""
    line: int = 0
    run: str = ""
    snapshot: str = ""
    where: str = ""
    text: str = ""
    who: str = ""
    at: float = 0.0
    resolved: bool = False


@dataclasses.dataclass
class ActivityRow:
    at: float = 0.0
    who: str = ""
    what: str = ""
    kind: str = ""  # edit | snapshot | run | ai | review | people


# Project id -> its recent activity (in memory: a log of the moment, the audit log keeps all).
_activity: dict[str, collections.deque] = {}
# Reflex's registration of the app (set by the app module): pushes started outside Reflex's own
# handlers (the co-editing socket, save timers, AI tool calls) run in a context that lacks it.
registration = None
_pending: dict[str, set[str]] = {}
_handles: dict[str, asyncio.TimerHandle] = {}
_tasks: set[asyncio.Task] = set()


def note(project_id: str, who: str, what: str, kind: str = "edit") -> None:
    """Adds a line to the project's activity, for everyone on it."""
    log = _activity.setdefault(project_id, collections.deque(maxlen=ACTIVITY))
    log.appendleft(ActivityRow(at=time.time(), who=who, what=what, kind=kind))
    push_later(project_id, "activity")


def run_summary(r: Run) -> str:
    """A run's result in a few words."""
    s = r.summary or {}
    if r.flow_id == "rtl_sim":
        if s.get("fail_lines"):
            return f"FAIL ×{s['fail_lines']}"
        if s.get("pass_lines"):
            return "PASS" + (f" ×{s['pass_lines']}" if s["pass_lines"] > 1 else "")
        return ""
    if r.flow_id == "synth_yosys" and s.get("cells") is not None:
        return f"{s['cells']} cells"
    if r.flow_id == "fpga_ice40":
        fmax = s.get("fmax") or {}
        if fmax:
            best = min(v["achieved_mhz"] for v in fmax.values())
            return f"Fmax {best:.1f} MHz"
    if r.flow_id == "ams_ngspice":
        m = s.get("measures") or {}
        if m:
            k, v = next(iter(m.items()))
            return f"{k} = {v:.3g}"
    if s.get("headline"):
        return str(s["headline"])
    return ""


def run_row(r: Run) -> RunRow:
    flow = flows.get(r.flow_id)
    waiting = r.status == RunStatus.CREATED and r.approval_status.value == "PROPOSED"
    return RunRow(
        id=r.id,
        flow=r.flow_id,
        title=flow.definition.title if flow else r.flow_id,
        category=flow.definition.category if flow else "",
        status="WAITING" if waiting else r.status.value,
        snapshot=ids.short_revision(r.revision_id),
        by=r.requested_by_name,
        via=r.requested_via,
        created=r.created_at,
        started=r.started_at,
        ended=r.ended_at,
        errors=int((r.problems or {}).get("errors", 0) or 0),
        warnings=int((r.problems or {}).get("warnings", 0) or 0),
        summary=run_summary(r),
        error=r.error,
        active=r.status in (RunStatus.QUEUED, RunStatus.RUNNING) or waiting,
    )


def file_rows(project_id: str) -> list[FileRow]:
    """The project's files as an explorer shows them: each folder, then its files."""
    editing = collab.editors_of(project_id)
    names = {t["user"]: t["name"] for t in presence.tabs(project_id)}
    files = []
    for f in projects.files(project_id):
        folder, _, name = f.path.rpartition("/")
        who = sorted({names.get(u, "") for u in editing.get(f.id, set())} - {""})
        files.append(FileRow(id=f.id, path=f.path, name=name, folder=folder, depth=f.path.count("/"), lang=templates.language(f.path), editing=", ".join(who)))
    out: list[FileRow] = []
    shown: set[str] = set()
    # Folders first (with their files), then the files at the top, like an explorer.
    for f in sorted(files, key=lambda x: (x.folder == "", x.folder.split("/"), x.name)):
        parts = f.folder.split("/") if f.folder else []
        for i in range(len(parts)):
            folder = "/".join(parts[: i + 1])
            if folder not in shown:
                shown.add(folder)
                out.append(FileRow(path=folder, name=parts[i], folder="/".join(parts[:i]), depth=i, kind="folder"))
        out.append(f)
    return out


def note_rows(project_id: str) -> list[NoteRow]:
    from chipova.db import db  # noqa: PLC0415
    from chipova.domain.models import Comment  # noqa: PLC0415

    rows = db().query("SELECT * FROM comments WHERE project_id = ? AND anchor_kind = 'layout' ORDER BY created_at", (project_id,))
    out = []
    for r in rows:
        c = Comment.from_row(r)
        out.append(NoteRow(c.id, str(c.anchor.get("artifact", "")), float(c.anchor.get("x", 0)), float(c.anchor.get("y", 0)), c.body, c.author_name, c.created_at))
    return out


def comment_rows(project_id: str) -> list[CommentRow]:
    from chipova.db import db  # noqa: PLC0415
    from chipova.domain.models import Comment  # noqa: PLC0415

    rows = db().query("SELECT * FROM comments WHERE project_id = ? AND anchor_kind != 'layout' ORDER BY created_at DESC LIMIT 200", (project_id,))
    out = []
    for r in rows:
        c = Comment.from_row(r)
        a = c.anchor or {}
        path, line, run = str(a.get("path", "")), int(a.get("line", 0) or 0), str(a.get("run", ""))
        where = f"{path}:{line}" if path else (run or ids.short_revision(c.revision_id))
        out.append(CommentRow(c.id, c.anchor_kind, path, line, run, ids.short_revision(c.revision_id), where, c.body, c.author_name, c.created_at, c.resolved))
    return out


def proposal_rows(project_id: str) -> list[ProposalRow]:
    out = []
    for a in proposals.of_project(project_id, 30):
        out.append(ProposalRow(
            id=a.id, title=a.title, agent=a.agent.removeprefix("agent:"), status=a.status.value, created=a.created_at,
            files=", ".join(f["path"] for f in a.payload.get("files", [])), rationale=a.rationale, plan=a.plan,
            base=ids.short_revision(a.base_revision), decided_by=a.decided_by_name, reason=a.reason,
            applied=ids.short_revision(a.applied_revision),
        ))
    return out


class ProjectRoom(rx.SharedState):
    project_id: str = ""
    title: str = ""
    kind: str = ""
    link_access: str = ""
    owner_name: str = ""
    gone: bool = False
    files: list[FileRow] = []
    latest_id: str = ""
    latest_short: str = ""
    latest_message: str = ""
    latest_by: str = ""
    latest_at: float = 0.0
    snapshots: list[SnapRow] = []
    # The editors' text differs from the latest snapshot.
    dirty: bool = False
    runs: list[RunRow] = []
    proposals: list[ProposalRow] = []
    activity: list[ActivityRow] = []
    # Notes pinned on layouts, and the view someone shared (Layout section).
    layout_notes: list[NoteRow] = []
    comments: list[CommentRow] = []
    shared_view: dict[str, str] = {}
    settings: dict[str, str] = {}
    settings_error: str = ""
    # One entry per tab on the project: {"id", "user", "name", "avatar", "color"}.
    peers: list[dict[str, str]] = []
    # The project's call (chipova.services.call).
    call_count: int = 0
    call_ringing_from: str = ""
    call_invited: list[str] = []
    call_responded: list[str] = []

    @rx.var
    def people(self) -> list[dict[str, str]]:
        """One entry per person: several tabs of one person count once."""
        out: list[dict[str, str]] = []
        seen = set()
        for p in self.peers:
            user = p.get("user") or p.get("id")
            if user in seen:
                continue
            seen.add(user)
            name = p.get("name", "") or "?"
            out.append({
                "id": p.get("id", ""), "user": user, "name": name, "initials": presence.initials(name, user),
                "color": p.get("color", ""), "avatar": p.get("avatar", ""),
            })
        return out

    @rx.var
    def people_count(self) -> int:
        return len({p.get("user") or p.get("id") for p in self.peers})

    @rx.var
    def pending_proposals(self) -> int:
        return sum(1 for p in self.proposals if p.status == "PROPOSED")

    @rx.var
    def open_comments(self) -> int:
        return sum(1 for c in self.comments if not c.resolved)

    @rx.var
    def comment_lines(self) -> str:
        """The lines with open comments, per file (for the editor's marks): JSON."""
        import json as _json  # noqa: PLC0415

        out: dict[str, list[int]] = {}
        for c in self.comments:
            if c.path and c.line and not c.resolved:
                out.setdefault(c.path, []).append(c.line)
        return _json.dumps(out)

    @rx.var
    def waiting_runs(self) -> int:
        return sum(1 for r in self.runs if r.status == "WAITING")

    @rx.var
    def active_runs(self) -> int:
        return sum(1 for r in self.runs if r.status in ("QUEUED", "RUNNING"))


def publish(room: ProjectRoom, project_id: str, what: set[str]) -> None:
    """Shows the project as it is now to everyone on it (only what changed)."""
    p = projects.get(project_id)
    if p is None:
        if not room.gone:
            room.gone = True
        return
    if "project" in what:
        for k, v in (("title", p.title), ("kind", p.kind.value), ("link_access", p.link_access.value), ("owner_name", p.owner_name)):
            if getattr(room, k) != v:
                setattr(room, k, v)
    if "files" in what:
        rows = file_rows(project_id)
        if list(room.files) != rows:
            room.files = rows
    if "latest" in what:
        rev = revisions.latest(project_id)
        values = {
            "latest_id": rev.id if rev else "",
            "latest_short": ids.short_revision(rev.id) if rev else "",
            "latest_message": rev.message if rev else "",
            "latest_by": rev.created_by_name if rev else "",
            "latest_at": rev.created_at if rev else 0.0,
            "dirty": revisions.differs_from_working(project_id, rev, projects.working_copy(project_id)),
        }
        for k, v in values.items():
            if getattr(room, k) != v:
                setattr(room, k, v)
        snaps = [SnapRow(r.id, ids.short_revision(r.id), r.message, r.created_by_name, r.created_at) for r in revisions.history(project_id, 12)]
        if list(room.snapshots) != snaps:
            room.snapshots = snaps
        s, error, _ = projects.settings(project_id)
        settings = {k: (", ".join(v) if isinstance(v, list) else str(v)) for k, v in s.model_dump().items()}
        if room.settings != settings:
            room.settings = settings
        if room.settings_error != error:
            room.settings_error = error
    if "runs" in what:
        rows = [run_row(r) for r in engine.runs_of(project_id, limit=40)]
        if list(room.runs) != rows:
            room.runs = rows
    if "proposals" in what:
        rows = proposal_rows(project_id)
        if list(room.proposals) != rows:
            room.proposals = rows
    if "notes" in what:
        notes = note_rows(project_id)
        if list(room.layout_notes) != notes:
            room.layout_notes = notes
        comments = comment_rows(project_id)
        if list(room.comments) != comments:
            room.comments = comments
    if "activity" in what:
        rows = list(_activity.get(project_id, ()))
        if list(room.activity) != rows:
            room.activity = rows
    if "people" in what:
        peers = presence.tabs(project_id)
        if list(room.peers) != peers:
            room.peers = peers
        from chipova.services import call  # noqa: PLC0415 — call imports this module

        call.sync_room(room, project_id)


EVERYTHING = {"project", "files", "latest", "runs", "proposals", "notes", "activity", "people"}


def push_later(project_id: str, *what: str) -> None:
    """``publish`` from outside the tabs' own events, gathered over PUSH_DELAY."""
    if not ids.is_project(project_id):
        return
    _pending.setdefault(project_id, set()).update(what or EVERYTHING)
    if project_id in _handles:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _handles[project_id] = loop.call_later(PUSH_DELAY, _start_push, project_id)


def _start_push(project_id: str) -> None:
    _handles.pop(project_id, None)
    what = _pending.pop(project_id, set())
    task = asyncio.create_task(push(project_id, what))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def push(project_id: str, what: set[str]) -> None:
    if registration is not None:
        from reflex_base.registry import RegistrationContext  # noqa: PLC0415

        RegistrationContext.set(registration)  # this task's own context only
    try:
        async with rooms.change(ProjectRoom, project_id) as room:
            publish(room, project_id, what)
    except Exception as e:  # noqa: BLE001
        logger.warning("Cannot show project %s to its people: %s", project_id, e)
