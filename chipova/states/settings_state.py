"""A project's settings page: its runs' settings (``chipova.toml``, saved only when nobody changed
it meanwhile), who may do what (members, the link), what an AI may run without asking, its name,
and deleting it."""

from __future__ import annotations

import dataclasses

import reflex as rx

from chipova.domain.models import LinkAccess, ProjectSettings, Role
from chipova.jobs import flows
from chipova.services import projects
from chipova.states.ide import IdeState
from chipova.states.room import note, push_later
from chipova.states.ui_state import UiState

FIELDS = ("top", "testbench", "rtl", "sim", "sdc", "clock_port", "clock_period_ns", "pdk", "fpga_device", "fpga_package", "pcf", "spice")
LISTS = ("rtl", "sim")


@dataclasses.dataclass
class MemberRow:
    user: str = ""
    name: str = ""
    role: str = ""
    owner: bool = False


def _shown(user: str, owner: str, owner_name: str) -> str:
    """How a member shows: their e-mail, or a guest's (or an AI's) name."""
    if user == owner and owner_name:
        return owner_name if not user.startswith("guest-") else f"{owner_name} (guest)"
    if user.startswith("agent:"):
        return "AI · " + user.removeprefix("agent:")
    return "a guest" if user.startswith("guest-") else user


@dataclasses.dataclass
class FlowChoice:
    id: str = ""
    title: str = ""
    allowed: bool = False


class SettingsState(rx.State):
    form: dict[str, str] = {}
    sha: str = ""
    error: str = ""
    conflict: str = ""
    title: str = ""
    link_access: str = "editor"
    members: list[MemberRow] = []
    new_member: str = ""
    new_role: str = "editor"
    ai_flows: list[FlowChoice] = []
    confirm_delete: bool = False

    @rx.event
    async def load(self):
        ide = await self.get_state(IdeState)
        pid = ide.project_id
        p = projects.get(pid)
        if p is None:
            return
        s, error, sha = projects.settings(pid)
        self.form = {k: (", ".join(v) if k in LISTS else str(v)) for k, v in s.model_dump().items() if k in FIELDS}
        self.sha, self.error, self.conflict = sha, error, ""
        self.title = p.title
        self.link_access = p.link_access.value
        self.members = [MemberRow(m.user, _shown(m.user, p.owner, p.owner_name), m.role.value, m.user == p.owner) for m in projects.members(pid)]
        self.ai_flows = [FlowChoice(d.id, d.title, d.id in p.ai_may_run) for d in flows.definitions()]

    @rx.event
    def set_field(self, name: str, value: str):
        if name in FIELDS:
            self.form = {**self.form, name: value}

    async def _actor(self):
        return (await self.get_state(UiState)).actor()

    @rx.event
    async def save(self):
        ide = await self.get_state(IdeState)
        values: dict = {}
        for k, v in self.form.items():
            if k in LISTS:
                values[k] = [x.strip() for x in v.replace("\n", ",").split(",") if x.strip()]
            else:
                values[k] = v.strip()
        try:
            new = ProjectSettings.model_validate(values)
        except Exception as e:  # noqa: BLE001 — a wrong number, say
            return rx.toast.error(f"Check the values: {e}", position="bottom-right")
        actor = await self._actor()
        try:
            self.sha = projects.save_settings(ide.project_id, new, self.sha, actor)
        except projects.Conflict as e:
            self.conflict = str(e)
            return None
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.conflict = ""
        note(ide.project_id, actor.name, "changed the project's settings")
        push_later(ide.project_id, "latest")
        return rx.toast.success("Settings saved (chipova.toml); the next snapshot takes them.", position="bottom-right")

    @rx.event
    def set_title(self, value: str):
        self.title = value

    @rx.event
    async def rename(self):
        ide = await self.get_state(IdeState)
        try:
            projects.rename(ide.project_id, self.title, await self._actor())
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        push_later(ide.project_id, "project")
        return rx.toast.success("Renamed.", position="bottom-right")

    @rx.event
    async def set_link_access(self, value: str):
        ide = await self.get_state(IdeState)
        try:
            projects.set_link_access(ide.project_id, LinkAccess(value), await self._actor())
        except (projects.Denied, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.link_access = value
        push_later(ide.project_id, "project")
        return None

    @rx.event
    def set_new_member(self, value: str):
        self.new_member = value

    @rx.event
    def set_new_role(self, value: str):
        self.new_role = value

    @rx.event
    async def add_member(self):
        ide = await self.get_state(IdeState)
        try:
            projects.set_member(ide.project_id, self.new_member, Role(self.new_role), await self._actor())
        except (projects.Denied, projects.Conflict, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.new_member = ""
        return SettingsState.load

    @rx.event
    async def change_role(self, user: str, role: str):
        ide = await self.get_state(IdeState)
        try:
            projects.set_member(ide.project_id, user, None if role == "remove" else Role(role), await self._actor())
        except (projects.Denied, projects.Conflict, ValueError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        return SettingsState.load

    @rx.event
    async def toggle_ai_flow(self, flow_id: str):
        ide = await self.get_state(IdeState)
        allowed = {f.id for f in self.ai_flows if f.allowed}
        allowed ^= {flow_id}
        try:
            projects.set_ai_may_run(ide.project_id, sorted(allowed), await self._actor())
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.ai_flows = [dataclasses.replace(f, allowed=f.id in allowed) for f in self.ai_flows]
        return None

    @rx.event
    def ask_delete(self):
        self.confirm_delete = True

    @rx.event
    def cancel_delete(self):
        self.confirm_delete = False

    @rx.event
    async def delete_project(self):
        ide = await self.get_state(IdeState)
        self.confirm_delete = False
        try:
            projects.delete(ide.project_id, await self._actor())
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        push_later(ide.project_id, "project")
        return rx.redirect("/")
