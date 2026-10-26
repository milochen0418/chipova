"""The Lab page's measurements (chipova.services.lab): the records of real chips, uploaded here or
sent by a bench computer, and the comparison with the spec and the design's own values."""

from __future__ import annotations

import dataclasses
import json

import reflex as rx

from chipova import ids
from chipova.services import lab, projects
from chipova.states.ide import IdeState
from chipova.states.room import note
from chipova.states.runs_state import _num
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class MeasureRow:
    name: str = ""
    value: str = ""
    unit: str = ""
    outcome: str = ""
    limits: str = ""


@dataclasses.dataclass
class LabRow:
    id: str = ""
    dut: str = ""
    outcome: str = ""
    simulated: bool = False
    test: str = ""
    station: str = ""
    snapshot: str = ""
    by: str = ""
    at: float = 0.0
    measures: list[MeasureRow] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class CompareRow:
    name: str = ""
    unit: str = ""
    spec: str = ""
    pre: str = ""
    source: str = ""
    chips: int = 0
    passed: int = 0
    spread: str = ""
    simulated: int = 0
    verdict: str = ""  # in spec | out of spec | not measured


def _limits(low, high) -> str:  # noqa: ANN001
    if low is not None and high is not None:
        return f"{_num(low)} … {_num(high)}"
    if high is not None:
        return f"≤ {_num(high)}"
    if low is not None:
        return f"≥ {_num(low)}"
    return ""


class LabState(rx.State):
    results: list[LabRow] = []
    compare: list[CompareRow] = []

    @rx.event
    async def load(self):
        pid = (await self.get_state(IdeState)).project_id
        if not pid:
            return
        self.results = [
            LabRow(
                r["id"], r["dut"], r["outcome"], r["simulated"], r["test"], r["station"], ids.short_revision(r["revision_id"]),
                r["uploaded_by_name"], r["created_at"],
                [MeasureRow(m["name"], _num(m["value"]) if m["value"] is not None else m["text"], m["unit"], m["outcome"], _limits(m["min"], m["max"])) for m in r["measurements"]],
            )
            for r in lab.results(pid)
        ]
        rows = []
        for c in lab.compare(pid):
            if not c["chips"]:
                verdict = "not measured"
            elif c["passed"] == c["chips"] and (c["min"] is None or c["low"] is None or c["low"] >= c["min"]) and (c["max"] is None or c["high"] is None or c["high"] <= c["max"]):
                verdict = "in spec"
            else:
                verdict = "out of spec"
            spread = "" if c["low"] is None else f"{_num(c['low'])} / {_num(c['mean'])} / {_num(c['high'])}"
            rows.append(CompareRow(c["name"], c["unit"], _limits(c["min"], c["max"]), "" if c["pre_silicon"] is None else _num(c["pre_silicon"]),
                                   c["source"], c["chips"], c["passed"], spread, c["simulated"], verdict))
        self.compare = rows

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        ide = await self.get_state(IdeState)
        actor = (await self.get_state(UiState)).actor()
        added = []
        for f in files[:5]:
            data = b""
            while chunk := await f.read(1024 * 1024):
                data += chunk
                if len(data) > lab.MAX_RECORD:
                    return rx.toast.error("That file is too big for a test record (2 MB at most).", position="bottom-right")
            try:
                r = lab.add(ide.project_id, "", json.loads(data), actor)
            except (ValueError, projects.Denied, projects.NotFound) as e:
                return rx.toast.error(f"{f.filename}: {e}", position="bottom-right")
            added.append(r)
        await self.load()
        for r in added:
            note(ide.project_id, actor.name, f"added the {'simulated ' if r['simulated'] else ''}test record of {r['dut'] or 'a chip'}: {r['outcome']}", "review")
        return rx.toast.success(f"{len(added)} test record(s) added.", position="bottom-right")
