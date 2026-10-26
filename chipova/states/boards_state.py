"""Asking one's own board helper to program a board with the selected FPGA run's bitstream
(:mod:`chipova.services.boards`), and following the job until it ends."""

from __future__ import annotations

import asyncio
import dataclasses
import time

import reflex as rx

from chipova.services import boards, projects
from chipova.states.ide import IdeState
from chipova.states.room import note
from chipova.states.runs_state import RunState, board_job_rows
from chipova.states.ui_state import UiState

WATCH_FOR = 900.0


@dataclasses.dataclass
class HelperRow:
    id: str = ""
    name: str = ""
    online: bool = False
    seen: float = 0.0
    boards: str = ""
    loader: str = ""


class BoardState(rx.State):
    open: bool = False
    helpers: list[HelperRow] = []
    helper_id: str = ""
    board: str = ""
    suggestions: list[str] = []

    async def _user(self) -> str:
        return (await self.get_state(UiState)).actor().user

    def _load_helpers(self, user: str) -> None:
        self.helpers = [
            HelperRow(h["id"], h["name"], h["online"], h["last_seen"], "; ".join(h["boards"])[:400], h["loader"])
            for h in (boards.helpers_of(user) if user else [])
        ]
        online = [h.id for h in self.helpers if h.online]
        if self.helper_id not in online:
            self.helper_id = online[0] if online else ""

    @rx.event
    async def ask(self):
        rs = await self.get_state(RunState)
        self.suggestions = boards.BOARDS.get(rs.flow, [])
        self.board = self.suggestions[0] if self.suggestions else ""
        self._load_helpers(await self._user())
        self.open = True

    @rx.event
    async def look_again(self):
        self._load_helpers(await self._user())

    @rx.event
    def close(self):
        self.open = False

    @rx.event
    def set_helper(self, value: str):
        self.helper_id = value

    @rx.event
    def set_board(self, value: str):
        self.board = value.strip()

    @rx.event
    async def program(self):
        rs = await self.get_state(RunState)
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        try:
            job = boards.request(ide.project_id, rs.selected, self.helper_id, self.board, actor)
        except (projects.Denied, projects.NotFound, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.open = False
        rs.board_jobs = board_job_rows(rs.selected)
        note(ide.project_id, actor.name, f"asked their board helper to program a {job['board']} with {rs.selected}", "run")
        return BoardState.watch(job["id"])

    @rx.event(background=True)
    async def watch(self, job_id: str):
        """Shows the job's progress on the run until it ends."""
        end, last = time.time() + WATCH_FOR, None
        while time.time() < end:
            j = boards.job(job_id)
            if j is None:
                return
            now = (j["status"], j["updated_at"])
            if now != last:
                last = now
                async with self:
                    rs = await self.get_state(RunState)
                    if rs.selected == j["run_id"]:
                        rs.board_jobs = board_job_rows(j["run_id"])
            if j["status"] in boards.FINAL:
                return
            await asyncio.sleep(1.0)
