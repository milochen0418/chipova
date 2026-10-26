"""The Layout section: the GDS files the project's runs made, one of them open in the viewer
(assets/chipova/layout.js), its layers and cells, notes pinned on it (everyone sees them), and
showing others where you look."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time

import reflex as rx

from chipova import ids
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import Comment
from chipova.jobs import engine, layout
from chipova.services import artifacts, audit, projects
from chipova.states.ide import IdeState
from chipova.states.room import ProjectRoom, note, push_later
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class GdsRow:
    id: str = ""
    run: str = ""
    name: str = ""
    flow: str = ""
    snapshot: str = ""
    at: float = 0.0
    size: str = ""


@dataclasses.dataclass
class MarkerRow:
    """A DRC violation on the layout: its rule and box (µm)."""

    rule: str = ""
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    box: str = ""  # [x0, y0, x1, y1] as JSON, for the viewer


@dataclasses.dataclass
class LayerRow:
    key: str = ""
    name: str = ""
    color: str = ""
    hidden: bool = False


def gds_rows(project_id: str) -> list[GdsRow]:
    out = []
    for run in engine.runs_of(project_id, limit=100):
        for a in engine.artifacts_of(run.id):
            if a.kind in ("gds", "oas"):
                out.append(GdsRow(a.id, run.id, a.name, run.flow_id, ids.short_revision(run.revision_id), a.created_at, f"{a.size / 1024:.0f} KB"))
    return out


class LayoutState(rx.State):
    gds: list[GdsRow] = []
    selected: str = ""
    url: str = ""  # signed path of the layout endpoint
    top: str = ""
    bbox: list[float] = []
    cells: list[str] = []
    cell_count: int = 0
    layers: list[LayerRow] = []
    error: str = ""
    note_text: str = ""
    adding_note: bool = False
    # The violations the latest DRC of this layout's run found.
    markers: list[MarkerRow] = []
    drc_run: str = ""

    @rx.var
    def hidden_keys(self) -> str:
        return ",".join(x.key for x in self.layers if x.hidden)

    @rx.var
    def markers_json(self) -> str:
        return json.dumps([{"rule": m.rule, "box": [m.x0, m.y0, m.x1, m.y1]} for m in self.markers])

    @rx.var
    def size_text(self) -> str:
        if len(self.bbox) != 4:
            return ""
        return f"{self.bbox[2] - self.bbox[0]:.2f} × {self.bbox[3] - self.bbox[1]:.2f} µm"

    @rx.event
    async def load(self):
        ide = await self.get_state(IdeState)
        self.gds = gds_rows(ide.project_id)
        if not self.selected and self.gds:
            return LayoutState.open(self.gds[0].id)
        return None

    @rx.event
    async def open(self, artifact_id: str):
        ide = await self.get_state(IdeState)
        a = artifacts.get(artifact_id)
        if a is None or a.project_id != ide.project_id:
            return None
        user = (await self.get_state(UiState)).me.get("user", "")
        self.selected = a.id
        self.url = artifacts.LAYOUT_PATH.format(artifact_id=a.id) + "?" + artifacts.query(a.id, user)
        lyp = next((x for x in engine.artifacts_of(a.run_id) if x.name.endswith(".lyp")), None)
        info = await asyncio.to_thread(layout.info, artifacts.file_of(a), artifacts.file_of(lyp) if lyp else None)
        if not info.get("ok"):
            self.error = info.get("error", "can't read the layout")
            return None
        self.error = ""
        self.top = info["top"]
        self.bbox = info["bbox"]
        self.cells = info["cells"]
        self.cell_count = info["cell_count"]
        self.layers = [LayerRow(x["key"], x["name"], x["color"], False) for x in info["layers"]]
        drc = next((r for r in engine.runs_of(ide.project_id, limit=200, flow_id="signoff_drc") if r.source_run == a.run_id and r.status.finished), None)
        self.drc_run = drc.id if drc else ""
        self.markers = [
            MarkerRow(m["rule"], *m["box"], box=json.dumps(m["box"]))
            for m in ((drc.summary or {}).get("markers") or [] if drc else [])
        ]
        return None

    @rx.event
    def toggle_layer(self, key: str):
        self.layers = [dataclasses.replace(x, hidden=not x.hidden) if x.key == key else x for x in self.layers]

    @rx.event
    def all_layers(self, visible: bool):
        self.layers = [dataclasses.replace(x, hidden=not visible) for x in self.layers]

    @rx.event
    def set_note_text(self, value: str):
        self.note_text = value

    @rx.event
    def toggle_adding_note(self):
        self.adding_note = not self.adding_note

    @rx.event
    async def add_note(self, x: float, y: float):
        """A click on the layout while adding a note pins it there (µm)."""
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        text = self.note_text.strip()
        self.adding_note = False
        if not text or not self.selected:
            return rx.toast.info("Write the note first, then click where it goes.", position="bottom-right")
        try:
            projects.require(ide.project_id, actor, roles.COMMENT)
        except projects.Denied as e:
            return rx.toast.error(str(e), position="bottom-right")
        a = artifacts.get(self.selected)
        run = engine.get(a.run_id) if a else None
        c = Comment(
            id=ids.new_id("cm"), project_id=ide.project_id, anchor_kind="layout",
            anchor={"artifact": self.selected, "x": round(float(x), 4), "y": round(float(y), 4)},
            revision_id=run.revision_id if run else "", author=actor.user, author_name=actor.name, body=text[:2000], created_at=time.time(),
        )
        db().insert("comments", c.model_dump(mode="json"))
        audit.record("comment.layout", actor, ide.project_id, c.id, {"x": x, "y": y})
        self.note_text = ""
        note(ide.project_id, actor.name, f"pinned a note on {a.name if a else 'the layout'}: “{text[:60]}”", "review")
        push_later(ide.project_id, "notes")
        return None

    @rx.event
    async def share_view(self, x0: float, y0: float, x1: float, y1: float):
        """Shows the others in the project where this tab looks (they can jump there)."""
        ide = await self.get_state(IdeState)
        me = (await self.get_state(UiState)).me
        room = await self.get_state(ProjectRoom)
        room.shared_view = {"who": me.get("name", ""), "artifact": self.selected, "box": json.dumps([x0, y0, x1, y1]), "at": str(time.time())}
        note(ide.project_id, me.get("name", ""), "shared their view of the layout", "review")
        return rx.toast.success("Everyone in the project can jump to your view now.", position="bottom-right")
