"""The project list (/): the projects you may see, who is in each now, their last run, and
making projects from templates and deleting them."""

from __future__ import annotations

import dataclasses

import reflex as rx

from chipova.domain import roles
from chipova.jobs import engine, flows
from chipova.services import presence, projects, revisions, templates
from chipova.states.room import run_summary
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class Person:
    name: str = ""
    initials: str = ""
    color: str = ""
    avatar: str = ""


@dataclasses.dataclass
class ProjectRow:
    id: str = ""
    title: str = ""
    kind: str = ""
    owner: str = ""
    updated: float = 0.0
    snapshot: str = ""
    last_run: str = ""
    last_status: str = ""
    private: bool = False
    may_delete: bool = False
    people: list[Person] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class TemplateRow:
    id: str = ""
    title: str = ""
    kind: str = ""
    description: str = ""


KIND_LABEL = {"digital_asic": "Digital ASIC", "fpga": "FPGA", "ams": "Analog / AMS"}


def _rows(user: str) -> list[ProjectRow]:
    watching = presence.watching()
    out = []
    for p in projects.visible_to(user):
        rev = revisions.latest(p.id)
        last = engine.runs_of(p.id, limit=1)
        run = last[0] if last else None
        flow = flows.get(run.flow_id) if run else None
        access = projects.access(p.id, user)
        out.append(ProjectRow(
            id=p.id,
            title=p.title,
            kind=KIND_LABEL.get(p.kind.value, p.kind.value),
            owner=p.owner_name,
            updated=p.updated_at,
            snapshot=rev.id.split(":", 1)[-1][:7] if rev else "",
            last_run=(f"{flow.definition.title if flow else run.flow_id}" + (f" · {run_summary(run)}" if run_summary(run) else "")) if run else "",
            last_status=run.status.value if run else "",
            private=p.link_access.value == "none",
            may_delete=bool(access and access.can(roles.MANAGE)),
            people=[
                Person(name=x["name"], initials=presence.initials(x["name"], x["user"]), color=x["color"], avatar=x["avatar"])
                for x in watching.get(p.id, [])
            ],
        ))
    return out


class HomeState(rx.State):
    rows: list[ProjectRow] = []
    loaded: bool = False
    query: str = ""
    new_open: bool = False
    new_title: str = ""
    new_template: str = templates.DEFAULT
    busy: bool = False
    confirm_id: str = ""
    confirm_title: str = ""

    @rx.var
    def shown(self) -> list[ProjectRow]:
        q = self.query.strip().lower()
        return [r for r in self.rows if q in r.title.lower() or q in r.owner.lower() or q in r.kind.lower()] if q else list(self.rows)

    @rx.var
    def template_rows(self) -> list[TemplateRow]:
        return [TemplateRow(t.id, t.title, KIND_LABEL.get(t.kind, t.kind), t.description) for t in templates.templates()]

    @rx.event
    async def refresh(self):
        ui = await self.get_state(UiState)
        actor = await ui._identify()
        self.rows = _rows(actor.user)
        self.loaded = True

    @rx.event
    def set_query(self, value: str):
        self.query = value

    @rx.event
    def open_new(self):
        self.new_open, self.new_title, self.new_template = True, "", templates.DEFAULT

    @rx.event
    def set_new_open(self, value: bool):
        self.new_open = value

    @rx.event
    def set_new_title(self, value: str):
        self.new_title = value

    @rx.event
    def set_new_template(self, value: str):
        self.new_template = value

    @rx.event
    async def create(self):
        ui = await self.get_state(UiState)
        actor = await ui._identify()
        self.busy = True
        try:
            p = await projects.create(self.new_title, self.new_template, actor)
        except ValueError as e:
            self.busy = False
            return rx.toast.error(str(e), position="bottom-center")
        self.busy = False
        self.new_open = False
        return rx.redirect(f"/p/{p.id}")

    @rx.event
    def ask_delete(self, project_id: str, title: str):
        self.confirm_id, self.confirm_title = project_id, title

    @rx.event
    def cancel_delete(self):
        self.confirm_id = ""

    @rx.event
    async def delete(self):
        project_id, self.confirm_id = self.confirm_id, ""
        ui = await self.get_state(UiState)
        actor = await ui._identify()
        try:
            projects.delete(project_id, actor)
        except (projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-center")
        from chipova.states.room import push_later  # noqa: PLC0415

        push_later(project_id, "project")
        return HomeState.refresh
