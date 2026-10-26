"""One person's Xschem desktop on the project (chipova.services.desktops): starting it, showing it
in the page, opening a schematic in it, saving its files back, closing it."""

from __future__ import annotations

import asyncio

import reflex as rx

from chipova.jobs import docker_runner
from chipova.services import desktops, projects
from chipova.states.ide import IdeState
from chipova.states.room import note, push_later
from chipova.states.ui_state import UiState

SCHEMATIC = (".sch", ".sym")


class DesktopState(rx.State):
    sid: str = ""
    url: str = ""  # noVNC's page for this person, on the backend
    shown: bool = False
    starting: bool = False

    @rx.event(background=True)
    async def open(self, path: str = ""):
        """Shows the person's desktop (starting it when needed), with ``path`` open in Xschem."""
        async with self:
            ide = await self.get_state(IdeState)
            actor = (await self.get_state(UiState)).actor()
            pid = ide.project_id
            ide.bottom_open = False  # the desktop wants the room
            self.shown, self.starting = True, self.url == ""
        try:
            pdk = projects.settings(pid)[0].pdk
            d = await asyncio.to_thread(desktops.start, pid, actor, pdk)
            if path.endswith(SCHEMATIC):
                await asyncio.to_thread(desktops.open_file, d.id, actor, path)
        except (projects.Denied, projects.NotFound, ValueError, RuntimeError, docker_runner.DockerUnavailable) as e:
            async with self:
                self.shown = self.url != ""
                self.starting = False
            yield rx.toast.error(f"The desktop didn't start: {e}", position="bottom-right", duration=10000)
            return
        ticket = desktops.ticket(d.id, actor.user)
        base = f"/_chipova/desktop/{d.id}/{ticket}"
        async with self:
            self.sid = d.id
            # noVNC finds its WebSocket ("websockify") next to its page: {base}/websockify.
            self.url = f"{base}/vnc.html?autoconnect=1&resize=remote&reconnect=1&password={d.password}"
            self.starting = False

    @rx.event
    def hide(self):
        self.shown = False

    @rx.event
    async def save(self):
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        try:
            files, skipped = await asyncio.to_thread(desktops.fetch, self.sid, actor)
            got = desktops.save(self.sid, actor, files, skipped)
        except (projects.Denied, projects.NotFound, docker_runner.DockerUnavailable) as e:
            return rx.toast.error(str(e), position="bottom-right")
        parts = []
        if got["changed"]:
            parts.append("changed: " + ", ".join(got["changed"]))
        if got["added"]:
            parts.append("added: " + ", ".join(got["added"]))
        if parts:
            note(ide.project_id, actor.name, "saved from Xschem: " + "; ".join(parts), "edit")
            push_later(ide.project_id, "files", "latest")
        if got["conflicts"]:
            return rx.toast.warning(
                "Saved " + ("; ".join(parts) or "nothing new") + ". Left alone, as they changed in the project meanwhile: " + ", ".join(got["conflicts"]),
                position="bottom-right", duration=15000,
            )
        return rx.toast.success("Saved to the project: " + ("; ".join(parts) or "nothing had changed"), position="bottom-right")

    @rx.event
    async def close(self):
        actor = (await self.get_state(UiState)).actor()
        try:
            await asyncio.to_thread(desktops.stop, self.sid, actor)
        except projects.NotFound:
            pass
        self.sid, self.url, self.shown = "", "", False
