"""A snapshot looked at closely: what it changed from another one, its runs, the reviews of it
(they never carry over to another snapshot), and putting its files back for everyone."""

from __future__ import annotations

import asyncio
import dataclasses

import reflex as rx

from chipova import ids
from chipova.domain import roles
from chipova.jobs import engine, flows
from chipova.services import projects, revisions, reviews
from chipova.states.ide import IdeState
from chipova.states.review_state import DiffFile, diff_lines
from chipova.states.room import note, push_later, run_summary
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class SnapRun:
    id: str = ""
    title: str = ""
    status: str = ""
    summary: str = ""


@dataclasses.dataclass
class ReviewRow:
    reviewer: str = ""
    status: str = ""
    comment: str = ""
    at: float = 0.0


@dataclasses.dataclass
class CompareRow:
    what: str = ""
    a: str = ""
    b: str = ""
    same: bool = True


def _split_diff(text: str) -> list[DiffFile]:
    """A ``git diff`` as one DiffFile per file."""
    out: list[DiffFile] = []
    chunks = text.split("diff --git ")
    for chunk in chunks[1:]:
        head, _, body = chunk.partition("\n")
        path = head.split(" b/", 1)[-1].strip()
        op = "create" if "new file mode" in body[:200] else "delete" if "deleted file mode" in body[:200] else "modify"
        lines = body.splitlines()
        added = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
        removed = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
        hunks = "\n".join(x for x in lines if not x.startswith(("index ", "new file mode", "deleted file mode", "similarity", "rename ")))
        out.append(DiffFile(path=path, op=op, added=added, removed=removed, changed_since=False, lines=diff_lines(hunks)))
    return out


class SnapshotState(rx.State):
    open_id: str = ""
    short: str = ""
    message: str = ""
    by: str = ""
    at: float = 0.0
    files_count: int = 0
    base_id: str = ""  # what it is compared with ("" = its parent)
    base_short: str = ""
    files: list[DiffFile] = []
    runs: list[SnapRun] = []
    reviews: list[ReviewRow] = []
    review_comment: str = ""
    confirm_restore: bool = False
    # Comparing two runs.
    compare_a: str = ""
    compare_b: str = ""
    compare: list[CompareRow] = []

    @rx.event
    async def open(self, revision_id: str):
        ide = await self.get_state(IdeState)
        rev = revisions.get(ide.project_id, revision_id)
        if rev is None:
            return rx.toast.error("That snapshot is gone.", position="bottom-right")
        self.open_id = rev.id
        self.short, self.message, self.by, self.at = ids.short_revision(rev.id), rev.message, rev.created_by_name, rev.created_at
        self.files_count = len(rev.files)
        self.base_id = rev.parent
        self.review_comment = ""
        self.confirm_restore = False
        await self._load(ide.project_id)
        from chipova.states.review_state import ReviewState  # noqa: PLC0415

        (await self.get_state(ReviewState)).open_id = ""
        ide.view = "code"
        return None

    async def _load(self, project_id: str) -> None:
        rev = revisions.get(project_id, self.open_id)
        base = revisions.get(project_id, self.base_id) if self.base_id else None
        self.base_short = ids.short_revision(base.id) if base else ""
        if rev is not None and base is not None:
            text = await asyncio.to_thread(revisions.diff, project_id, base, rev)
            self.files = _split_diff(text)
        elif rev is not None:
            # The first snapshot: everything it holds is new.
            self.files = [DiffFile(path=e["path"], op="create", added=0, removed=0, changed_since=False, lines=[]) for e in rev.files]
        self.runs = []
        for r in engine.runs_of(project_id, limit=50, revision_id=self.open_id):
            f = flows.get(r.flow_id)
            waiting = r.status.value == "CREATED" and r.approval_status.value == "PROPOSED"
            self.runs.append(SnapRun(r.id, f.definition.title if f else r.flow_id, "WAITING" if waiting else r.status.value, run_summary(r)))
        self.reviews = [ReviewRow(x.reviewer_name or x.reviewer, x.status, x.comment, x.created_at) for x in reviews.of_revision(project_id, self.open_id)]

    @rx.event
    async def compare_with(self, revision_id: str):
        ide = await self.get_state(IdeState)
        self.base_id = revision_id
        await self._load(ide.project_id)

    @rx.event
    def close(self):
        self.open_id = ""
        self.files = []

    @rx.event
    def set_review_comment(self, value: str):
        self.review_comment = value

    @rx.event
    async def add_review(self, status: str):
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        try:
            reviews.review(ide.project_id, self.open_id, status, self.review_comment, actor)
        except (projects.Denied, projects.NotFound, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        words = {"approved": "approved", "changes_requested": "asked for changes on", "commented": "commented on"}[status]
        note(ide.project_id, actor.name, f"{words} snapshot {self.short}", "review")
        self.review_comment = ""
        await self._load(ide.project_id)
        return None

    @rx.event
    def ask_restore(self):
        self.confirm_restore = True

    @rx.event
    def cancel_restore(self):
        self.confirm_restore = False

    @rx.event
    async def restore(self):
        """Puts the snapshot's files back in the editors, for everyone (and freezes that)."""
        self.confirm_restore = False
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        pid = ide.project_id
        try:
            projects.require(pid, actor, roles.EDIT)
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        rev = revisions.get(pid, self.open_id)
        if rev is None:
            return None
        files = await asyncio.to_thread(revisions.files_of, pid, rev)
        wanted = {p: b.decode("utf-8", errors="replace") for p, b in files.items()}
        for entry in projects.files(pid):
            if entry.path not in wanted:
                projects.delete_file(pid, entry.id, actor)
        for path, text in wanted.items():
            entry = projects.file_by_path(pid, path)
            if entry is None:
                projects.add_file(pid, path, text, actor)
            elif projects.read(pid, entry.id) != text:
                projects.write(pid, entry.id, text, actor)
        back = await revisions.freeze(pid, f"Back to snapshot {self.short}", actor)
        note(pid, actor.name, f"put the files back to snapshot {self.short}", "snapshot")
        push_later(pid, "files", "latest")
        return rx.toast.success(f"The files are as in {self.short} again (snapshot {ids.short_revision(back.id)}).", position="bottom-right")

    # -------------------------------------------------------- runs side by side

    @rx.event
    def set_compare_b(self, run_id: str):
        self.compare_b = run_id

    @rx.event
    async def compare_runs(self, run_a: str):
        """What differs between two runs: snapshot, settings, image, tools, artifacts."""
        ide = await self.get_state(IdeState)
        a = engine.get(run_a)
        b = engine.get(self.compare_b)
        if a is None or b is None or a.project_id != ide.project_id or b.project_id != ide.project_id:
            return rx.toast.info("Pick another run of this project to compare with.", position="bottom-right")
        self.compare_a = a.id
        self.compare = [CompareRow(r["what"], _text(r["a"]), _text(r["b"]), bool(r["same"])) for r in engine.compare(a, b)]
        return None

    @rx.event
    def close_compare(self):
        self.compare = []
        self.compare_a = ""


def _text(v) -> str:  # noqa: ANN001
    if v is None:
        return "—"
    if isinstance(v, dict):
        return ", ".join(f"{k}={x}" for k, x in v.items())[:300]
    return str(v)[:300]
