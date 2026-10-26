"""The phone layout's own bits: a file to read (not to edit: that needs a wider screen) and the
line a comment goes on."""

from __future__ import annotations

import reflex as rx

from chipova.domain import roles
from chipova.services import projects
from chipova.states.ide import IdeState
from chipova.states.ui_state import UiState

MAX_LINES = 5000


class PhoneState(rx.State):
    file_id: str = ""
    path: str = ""
    lines: list[str] = []
    line: int = 0

    @rx.event
    async def read(self, file_id: str):
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        try:
            projects.require(ide.project_id, actor, roles.VIEW)
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-center")
        entry = projects.file_by_id(ide.project_id, file_id)
        if entry is None:
            return rx.toast.error("That file is gone.", position="bottom-center")
        self.file_id, self.path, self.line = entry.id, entry.path, 0
        self.lines = projects.read(ide.project_id, entry.id).splitlines()[:MAX_LINES]
        # Comments made here go on this file.
        ide.active_file, ide.active_path = entry.id, entry.path
        return None

    @rx.event
    def pick_line(self, line: int):
        self.line = line

    @rx.event
    def close(self):
        self.file_id, self.lines, self.line = "", [], 0
