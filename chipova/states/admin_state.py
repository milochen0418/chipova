"""The Tools & settings page (/settings): the tool profiles (installed or not, their tools'
versions, installing one), the PDKs, the run limits, and how Chipova connects to the platform."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import threading

import reflex as rx

from chipova.jobs import docker_runner, engine, flows, pdks, profiles
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class Version:
    tool: str = ""
    version: str = ""


@dataclasses.dataclass
class PdkRow:
    id: str = ""
    title: str = ""
    flow: bool = False
    drc: str = ""
    lvs: str = ""
    status: str = ""


@dataclasses.dataclass
class ProfileRow:
    id: str = ""
    title: str = ""
    description: str = ""
    image: str = ""
    base: str = ""
    size: str = ""
    installed: bool = False
    image_id: str = ""
    status: str = ""  # "" | installing | done | error
    line: str = ""
    flows: str = ""
    versions: list[Version] = dataclasses.field(default_factory=list)


def _rows() -> list[ProfileRow]:
    out = []
    for p in profiles.PROFILES:
        info = profiles.installed(p)
        prog = profiles.progress.get(p.id, {})
        rec = profiles.record(p.id)
        out.append(ProfileRow(
            id=p.id, title=p.title, description=p.description, image=p.image, base=p.base, size=p.size,
            installed=info is not None, image_id=(info or {}).get("id", "")[:19],
            status=prog.get("status", ""), line=prog.get("line", "") or (rec.get("detail", "") if rec.get("status") == "error" else ""),
            flows=", ".join(f.definition.title for f in flows.FLOWS.values() if p.id in f.definition.profiles),
            versions=[Version(k, v) for k, v in sorted((rec.get("versions") or {}).items())] if info is not None else [],
        ))
    return out


class AdminState(rx.State):
    rows: list[ProfileRow] = []
    pdks: list[PdkRow] = [PdkRow(p.id, p.title, p.flow, p.drc, p.lvs, p.status) for p in pdks.PDKS.values()]
    docker_ok: bool = False
    docker_error: str = ""
    max_parallel: int = engine.MAX_PARALLEL
    _watching: bool = False

    @rx.event
    async def load(self):
        await (await self.get_state(UiState))._identify()
        try:
            await asyncio.to_thread(docker_runner.client)
            self.docker_ok, self.docker_error = True, ""
        except docker_runner.DockerUnavailable as e:
            self.docker_ok, self.docker_error = False, str(e)
        self.rows = await asyncio.to_thread(_rows)
        # An image built by hand (or before this install) has no recorded versions: read them.
        for r in self.rows:
            if r.installed and not r.versions and r.status != "installing":
                profiles.probe_in_background(r.id)
        self.rows = await asyncio.to_thread(_rows)
        if any(r.status == "installing" for r in self.rows):
            return AdminState.watch
        return None

    @rx.event
    async def install(self, profile_id: str):
        """Builds a profile's image in the background (pulling its base first when needed)."""
        if profiles.get(profile_id) is None:
            return None
        if profiles.progress.get(profile_id, {}).get("status") == "installing":
            return AdminState.watch
        profiles.progress[profile_id] = {"status": "installing", "line": "Starting…"}
        threading.Thread(target=profiles.install, args=(profile_id,), daemon=True, name=f"install-{profile_id}").start()
        self.rows = await asyncio.to_thread(_rows)
        return AdminState.watch

    @rx.event
    async def probe(self, profile_id: str):
        p = profiles.get(profile_id)
        if p is None:
            return None
        try:
            await asyncio.to_thread(profiles.probe, p)
        except Exception as e:  # noqa: BLE001
            return rx.toast.error(str(e), position="bottom-right")
        self.rows = await asyncio.to_thread(_rows)
        return rx.toast.success("Versions read again.", position="bottom-right")

    @rx.event(background=True)
    async def watch(self):
        """Shows an install's progress until it ends."""
        async with self:
            if self._watching:
                return
            self._watching = True
        try:
            while True:
                await asyncio.sleep(1.0)
                rows = await asyncio.to_thread(_rows)
                async with self:
                    self.rows = rows
                if not any(r.status == "installing" for r in rows):
                    return
        finally:
            async with self:
                self._watching = False

    @rx.var
    def hub_address(self) -> str:
        return f"https://ai.{os.environ.get('SERVICE_ZONE', 'reflex-ddns.com')}/api/mcp"
