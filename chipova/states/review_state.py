"""One tab's look at the AI's proposals: a proposal's files and their diffs, and deciding on it
(accept: applied for everyone and frozen as a snapshot; reject: with a reason the AI reads)."""

from __future__ import annotations

import dataclasses

import reflex as rx

from chipova import ids
from chipova.domain.machines import InvalidTransition
from chipova.services import projects, proposals
from chipova.states.ide import IdeState
from chipova.states.room import note, push_later
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class DiffLine:
    kind: str = ""  # add | del | ctx | hunk
    old: str = ""
    new: str = ""
    text: str = ""


@dataclasses.dataclass
class DiffFile:
    path: str = ""
    op: str = ""
    added: int = 0
    removed: int = 0
    changed_since: bool = False
    lines: list[DiffLine] = dataclasses.field(default_factory=list)


def diff_lines(diff: str, limit: int = 3000) -> list[DiffLine]:
    """A unified diff as numbered lines for the page."""
    out: list[DiffLine] = []
    old = new = 0
    for raw in diff.splitlines():
        if raw.startswith(("---", "+++")):
            continue
        if raw.startswith("@@"):
            try:
                a, b = raw.split(" ")[1:3]
                old = int(a.lstrip("-").split(",")[0])
                new = int(b.lstrip("+").split(",")[0])
            except (ValueError, IndexError):
                pass
            out.append(DiffLine("hunk", "", "", raw))
        elif raw.startswith("+"):
            out.append(DiffLine("add", "", str(new), raw[1:]))
            new += 1
        elif raw.startswith("-"):
            out.append(DiffLine("del", str(old), "", raw[1:]))
            old += 1
        else:
            out.append(DiffLine("ctx", str(old), str(new), raw[1:] if raw.startswith(" ") else raw))
            old += 1
            new += 1
        if len(out) >= limit:
            out.append(DiffLine("hunk", "", "", "… (cut: the diff is longer)"))
            break
    return out


class ReviewState(rx.State):
    open_id: str = ""
    title: str = ""
    agent: str = ""
    status: str = ""
    rationale: str = ""
    plan: str = ""
    base: str = ""
    decided_by: str = ""
    reason: str = ""
    applied: str = ""
    files: list[DiffFile] = []
    # Rejecting: the proposal and the reason being typed.
    reject_id: str = ""
    reject_reason: str = ""
    busy: bool = False

    @rx.event
    async def open(self, action_id: str):
        ide = await self.get_state(IdeState)
        a = proposals.get(action_id)
        if a is None or a.project_id != ide.project_id:
            return rx.toast.error("That proposal is gone.", position="bottom-right")
        from chipova.states.snapshot_state import SnapshotState  # noqa: PLC0415

        (await self.get_state(SnapshotState)).open_id = ""
        self.open_id = a.id
        self.title, self.agent, self.status = a.title, a.agent.removeprefix("agent:"), a.status.value
        self.rationale, self.plan, self.base = a.rationale, a.plan, ids.short_revision(a.base_revision)
        self.decided_by, self.reason, self.applied = a.decided_by_name, a.reason, ids.short_revision(a.applied_revision)
        self.files = [
            DiffFile(path=d["path"], op=d["op"], added=d["added"], removed=d["removed"], changed_since=d["changed_since"], lines=diff_lines(d["diff"]))
            for d in proposals.diffs(a)
        ]
        ide.view = "code"
        return None

    @rx.event
    def close(self):
        self.open_id = ""
        self.files = []

    async def _actor(self):
        return (await self.get_state(UiState)).actor()

    @rx.event
    async def accept(self, action_id: str):
        actor = await self._actor()
        self.busy = True
        try:
            a = await proposals.accept(action_id, actor)
        except (projects.Denied, projects.Conflict, projects.NotFound, InvalidTransition, ValueError) as e:
            self.busy = False
            return rx.toast.error(str(e), position="bottom-right", duration=10000)
        self.busy = False
        note(a.project_id, actor.name, f"accepted the AI's “{a.title}” → snapshot {ids.short_revision(a.applied_revision)}", "ai")
        push_later(a.project_id, "proposals", "latest", "files")
        done = rx.toast.success(f"Applied for everyone, snapshot {ids.short_revision(a.applied_revision)}", position="bottom-right")
        # Back to the code, on the first file it changed: the change is there for everyone now.
        self.open_id, self.files = "", []
        first = next((f["path"] for f in a.payload.get("files", []) if f["op"] != "delete"), "")
        entry = projects.file_by_path(a.project_id, first) if first else None
        if entry is not None:
            return [IdeState.open_file(entry.id), done]
        return done

    @rx.event
    def ask_reject(self, action_id: str):
        self.reject_id, self.reject_reason = action_id, ""

    @rx.event
    def set_reject_reason(self, value: str):
        self.reject_reason = value

    @rx.event
    def cancel_reject(self):
        self.reject_id = ""

    @rx.event
    async def reject(self):
        actor = await self._actor()
        action_id = self.reject_id
        try:
            a = proposals.reject(action_id, actor, self.reject_reason)
        except (projects.Denied, projects.NotFound, InvalidTransition, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.reject_id = ""
        note(a.project_id, actor.name, f"rejected the AI's “{a.title}”: {a.reason}", "ai")
        push_later(a.project_id, "proposals")
        if self.open_id == action_id:
            await self.open(action_id)
        return None
