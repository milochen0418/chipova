"""Comments in a project: on a line of a file (where your cursor is), on a run, on a snapshot;
everyone in the project sees them at once, and anyone who may comment can resolve them. And
asking a private project's owner for access."""

from __future__ import annotations

import dataclasses
import time

import reflex as rx

from chipova import ids
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import Comment, Role
from chipova.services import audit, projects, revisions
from chipova.states.ide import IdeState
from chipova.states.room import note, push_later
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class AccessRequestRow:
    user: str = ""
    name: str = ""
    at: float = 0.0


class CommentsState(rx.State):
    text: str = ""
    requested: bool = False
    requests: list[AccessRequestRow] = []

    @rx.event
    def set_text(self, value: str):
        self.text = value

    async def _add(self, kind: str, anchor: dict) -> rx.event.EventSpec | None:
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        body = self.text.strip()
        if not body:
            return rx.toast.info("Write the comment first.", position="bottom-right")
        try:
            projects.require(ide.project_id, actor, roles.COMMENT)
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        latest = revisions.latest(ide.project_id)
        c = Comment(
            id=ids.new_id("cm"), project_id=ide.project_id, anchor_kind=kind, anchor=anchor,
            revision_id=latest.id if latest else "", author=actor.user, author_name=actor.name, body=body[:4000], created_at=time.time(),
        )
        db().insert("comments", c.model_dump(mode="json"))
        audit.record("comment.add", actor, ide.project_id, c.id, {"anchor": anchor})
        self.text = ""
        where = f"{anchor.get('path')}:{anchor.get('line')}" if anchor.get("path") else anchor.get("run", "the snapshot")
        note(ide.project_id, actor.name, f"commented on {where}: “{body[:60]}”", "review")
        push_later(ide.project_id, "notes")
        return None

    @rx.event
    async def on_line(self, line: int):
        """A comment on the open file, at the editor's line (``line`` comes from the editor)."""
        ide = await self.get_state(IdeState)
        if not ide.active_path:
            return rx.toast.info("Open a file first.", position="bottom-right")
        return await self._add("file", {"path": ide.active_path, "line": max(1, int(line or 1))})

    @rx.event
    async def on_run(self, run_id: str):
        return await self._add("run", {"run": run_id})

    @rx.event
    async def resolve(self, comment_id: str, resolved: bool):
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        try:
            projects.require(ide.project_id, actor, roles.COMMENT)
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        db().execute("UPDATE comments SET resolved = ? WHERE id = ? AND project_id = ?", (1 if resolved else 0, comment_id, ide.project_id))
        audit.record("comment.resolve" if resolved else "comment.reopen", actor, ide.project_id, comment_id)
        push_later(ide.project_id, "notes")
        return None

    # -------------------------------------------------------- asking for access

    @rx.event
    async def ask_access(self):
        """Someone without access to a private project asks its owner for it."""
        ui = await self.get_state(UiState)
        actor = await ui._identify()
        pid = str(self.router._page.params.get("project_id", "") or "")
        if projects.get(pid) is None:
            return None
        db().execute(
            "INSERT INTO access_requests(project_id, user, name, at) VALUES(?, ?, ?, ?) ON CONFLICT(project_id, user) DO UPDATE SET at = excluded.at",
            (pid, actor.user, actor.name, time.time()),
        )
        audit.record("access.request", actor, pid, pid)
        note(pid, actor.name, "asked for access to the project", "people")
        self.requested = True
        return None

    @rx.event
    async def load_requests(self):
        ide = await self.get_state(IdeState)
        rows = db().query("SELECT * FROM access_requests WHERE project_id = ? ORDER BY at", (ide.project_id,))
        self.requests = [AccessRequestRow(r["user"], r["name"], r["at"]) for r in rows]

    @rx.event
    async def grant(self, user: str, role: str):
        from chipova.states.settings_state import SettingsState  # noqa: PLC0415

        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        try:
            if role != "dismiss":
                projects.set_member(ide.project_id, user, Role(role), actor)
            else:
                projects.require(ide.project_id, actor, roles.MANAGE)
        except (projects.Denied, projects.Conflict, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        db().execute("DELETE FROM access_requests WHERE project_id = ? AND user = ?", (ide.project_id, user))
        await self.load_requests()
        return SettingsState.load
