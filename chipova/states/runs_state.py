"""One tab's look at one run: its steps, output, problems, numbers and artifacts, followed live
while it runs; and deciding on runs (approve, reject, cancel)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time

import reflex as rx

from chipova import ids
from chipova.domain.models import Run, RunStatus
from chipova.jobs import engine, flows
from chipova.services import artifacts, boards, projects
from chipova.states.ide import IdeState
from chipova.states.room import note, push_later, run_summary
from chipova.states.ui_state import UiState

FOLLOW_EVERY = 0.7
LOG_LINES = 600


@dataclasses.dataclass
class StepRow:
    node: str = ""
    title: str = ""
    status: str = ""
    exit_code: str = ""
    seconds: str = ""
    command: str = ""
    metrics: str = ""


@dataclasses.dataclass
class ProblemRow:
    severity: str = ""
    tool: str = ""
    step: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    code: str = ""
    message: str = ""
    where: str = ""


@dataclasses.dataclass
class ArtifactRow:
    id: str = ""
    name: str = ""
    kind: str = ""
    size: str = ""
    sha: str = ""
    sha_full: str = ""
    href: str = ""  # a signed path on the backend (components.links.backend_url makes it a URL)
    inline: bool = False


@dataclasses.dataclass
class Fact:
    label: str = ""
    value: str = ""


@dataclasses.dataclass
class BoardJobRow:
    """A board asked to be programmed with this run's bitstream (chipova.services.boards)."""

    id: str = ""
    board: str = ""
    helper: str = ""
    status: str = ""
    by: str = ""
    at: float = 0.0
    log: str = ""


def board_job_rows(run_id: str) -> list[BoardJobRow]:
    names: dict[str, str] = {}
    rows = []
    for j in boards.jobs_of_run(run_id):
        if j["helper_id"] not in names:
            names[j["helper_id"]] = (boards.helper(j["helper_id"]) or {}).get("name", "")
        rows.append(BoardJobRow(j["id"], j["board"], names[j["helper_id"]], j["status"], j["requested_by_name"], j["updated_at"], (j["log"] or "")[-4000:]))
    return rows


@dataclasses.dataclass
class Chart:
    """A table a run wrote (ngspice's wrdata), as a line chart: x and up to three y series."""

    title: str = ""
    x_label: str = ""
    names: list[str] = dataclasses.field(default_factory=list)
    data: list[dict[str, float]] = dataclasses.field(default_factory=list)


def read_chart(path, name: str, limit: int = 400) -> Chart | None:  # noqa: ANN001
    """An ngspice ``wrdata`` table (``set wr_vecnames``: a header of vector names; with
    ``wr_singlescale`` one x column first) as a chart."""
    try:
        lines = [ln.split() for ln in path.read_text("utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    if len(lines) < 3:
        return None
    header = lines[0]
    try:
        float(header[0])
        header, rows = [f"c{i}" for i in range(len(lines[0]))], lines
    except ValueError:
        rows = lines[1:]
    values = []
    for r in rows:
        try:
            values.append([float(x) for x in r])
        except ValueError:
            continue
    if not values or len(header) < 2:
        return None
    step = max(1, len(values) // limit)
    data = [{"x": round(v[0], 15), **{f"y{i}": v[i] for i in range(1, min(len(v), 4))}} for v in values[::step]]
    return Chart(title=name.rsplit("/", 1)[-1].removesuffix(".csv").replace("_", " "), x_label=header[0], names=header[1:4], data=data)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _seconds(a: float, b: float) -> str:
    if not a:
        return ""
    s = (b or time.time()) - a
    return f"{s:.1f} s" if s < 60 else f"{int(s // 60)}:{int(s % 60):02d}"


def _num(v) -> str:  # noqa: ANN001
    """A number as people read it (4 significant digits for floats)."""
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _connected(token: str) -> bool:
    try:
        from reflex.utils.prerequisites import get_app

        ns = get_app().app.event_namespace
        return ns is None or token in ns.token_to_sid
    except Exception:  # noqa: BLE001
        return True


def facts(run: Run) -> list[Fact]:
    """The run's numbers, as label / value pairs."""
    s = run.summary or {}
    out: list[Fact] = []
    head = run_summary(run)
    if head:
        out.append(Fact("Result", head))
    for key, label in (("cells", "Cells"), ("wires", "Wires"), ("finished_at", "Simulation ended at")):
        if s.get(key) not in (None, ""):
            out.append(Fact(label, str(s[key])))
    for clock, v in (s.get("fmax") or {}).items():
        out.append(Fact(f"Fmax {clock}", f"{v['achieved_mhz']} MHz (target {v['constraint_mhz']} MHz)"))
    for kind, v in (s.get("utilization") or {}).items():
        out.append(Fact(kind, f"{v['used']} / {v['available']}"))
    for name, v in (s.get("measures") or {}).items():
        out.append(Fact(name, f"{v:.4g}"))
    for key, label in (s.get("_labels") or {}).items():
        if s.get(key) not in (None, ""):
            out.append(Fact(label, _num(s[key])))
    for row in s.get("specs") or []:
        limits = " … ".join(str(row.get(k)) for k in ("min_limit", "max_limit"))
        out.append(Fact(str(row.get("display")), f"{row.get('status')}: min {row.get('min_value')}, typical {row.get('typ_value')}, max {row.get('max_value')} (limits {limits})"))
    for rule, n in list((s.get("rules") or {}).items())[:12]:
        out.append(Fact(f"Rule {rule}", f"{n} violation{'s' if n != 1 else ''}"))
    for corner, v in ((s.get("checks") or {}).get("sta") or {}).get("corners", {}).items():
        out.append(Fact(f"STA {corner}", f"setup slack {_num(v.get('setup_ws_ns'))} ns, hold slack {_num(v.get('hold_ws_ns'))} ns"))
    for corner, v in ((s.get("checks") or {}).get("power_ir") or {}).get("corners", {}).items():
        out.append(Fact(f"Power/IR {corner}", f"{_num(v.get('power_mw'))} mW, IR drop {_num(v.get('ir_drop_total_mv'))} mV"))
    for layer, v in list(((s.get("density") or {}).get("layers") or {}).items())[:12]:
        limits = ", ".join(f"{k} {v[f'{k}_pct']:g} %" for k in ("min", "max") if v.get(f"{k}_pct") is not None)
        out.append(Fact(f"Density {layer}", f"{_num(v.get('density_pct'))} %" + (f" ({limits})" if limits else "")))
    return out


class RunState(rx.State):
    selected: str = ""
    flow: str = ""
    title: str = ""
    status: str = ""
    snapshot: str = ""
    snapshot_full: str = ""
    by: str = ""
    via: str = ""
    error: str = ""
    params: str = ""
    profile: str = ""
    image: str = ""
    created: float = 0.0
    duration: str = ""
    queue_position: int = 0
    facts: list[Fact] = []
    cell_types: list[Fact] = []
    charts: list[Chart] = []
    steps: list[StepRow] = []
    problems: list[ProblemRow] = []
    problems_json: str = "[]"
    errors: int = 0
    warnings: int = 0
    log: list[str] = []
    log_step: str = ""
    artifacts: list[ArtifactRow] = []
    wave_url: str = ""  # signed path of the run's waveform data
    picture: str = ""  # signed path of a picture to show (schematic)
    manifest: str = ""
    board_jobs: list[BoardJobRow] = []
    _following: bool = False

    async def _user(self) -> str:
        return (await self.get_state(UiState)).me.get("user", "")

    def _load(self, run: Run, user: str, full: bool = True) -> None:
        flow = flows.get(run.flow_id)
        self.flow = run.flow_id
        self.title = flow.definition.title if flow else run.flow_id
        waiting = run.status == RunStatus.CREATED and run.approval_status.value == "PROPOSED"
        self.status = "WAITING" if waiting else run.status.value
        self.snapshot = ids.short_revision(run.revision_id)
        self.snapshot_full = run.revision_id
        self.by = run.requested_by_name
        self.via = run.requested_via
        self.error = run.error
        self.created = run.created_at
        self.duration = _seconds(run.started_at, run.ended_at)
        self.queue_position = engine.queue_position(run)
        self.steps = [
            StepRow(
                node=s.node, title=s.title or s.node, status=s.status.value,
                exit_code="" if s.exit_code is None else str(s.exit_code),
                seconds=_seconds(s.started_at, s.ended_at) if s.started_at else "",
                command=" ".join(s.command)[:2000],
                metrics=", ".join(f"{k}: {_num(v)}" for k, v in (s.metrics or {}).items() if not isinstance(v, (dict, list)))[:300],
            )
            for s in engine.steps_of(run.id)
        ]
        self.log = engine.tail(run, self.log_step, LOG_LINES)
        if not full:
            return
        self.params = ", ".join(f"{k} = {v}" for k, v in (run.params or {}).items())
        self.profile = run.profile_id
        self.image = run.image_digest or run.image
        self.facts = facts(run)
        self.cell_types = [Fact(k, str(v)) for k, v in sorted((run.summary or {}).get("cell_types", {}).items(), key=lambda kv: -int(kv[1]))][:24]
        found = engine.problems_of(run)
        self.problems = [
            ProblemRow(
                severity=p.severity.value, tool=p.tool, step=p.step, file=p.file, line=p.line, column=p.column,
                code=p.code, message=p.message[:500],
                where=(f"{p.file}:{p.line}" + (f":{p.column}" if p.column else "")) if p.file else p.step,
            )
            for p in found
        ]
        self.problems_json = json.dumps([
            {"file": p.file, "line": p.line, "column": p.column, "severity": p.severity.value, "message": p.message[:300], "code": p.code}
            for p in found if p.file
        ])
        self.errors = int((run.problems or {}).get("errors", 0) or 0)
        self.warnings = int((run.problems or {}).get("warnings", 0) or 0)
        rows, wave, picture = [], "", ""
        for a in engine.artifacts_of(run.id):
            href = artifacts.link(a.id, user)
            rows.append(ArtifactRow(id=a.id, name=a.name, kind=a.kind, size=human_size(a.size), sha=a.sha256[:12], sha_full=a.sha256, href=href, inline=a.name.endswith((".svg", ".png"))))
            if a.kind == "vcd" and not wave:
                wave = artifacts.WAVE_PATH.format(artifact_id=a.id) + "?" + artifacts.query(a.id, user)
            if a.kind == "schematic" or (a.kind == "image" and not picture):  # the run's own schematic first
                picture = href + "&inline=1"
        self.artifacts = rows
        self.wave_url = wave
        self.picture = picture
        charts = []
        for a in engine.artifacts_of(run.id):
            if a.kind == "table" and a.size < 5_000_000:
                c = read_chart(engine.out_dir(run) / a.name, a.name)
                if c is not None:
                    charts.append(c)
        self.charts = charts[:6]
        self.manifest = f"/_chipova/manifest/{run.id}?" + artifacts.query(run.id, user) if run.status.finished else ""
        self.board_jobs = board_job_rows(run.id) if run.flow_id in flows.FPGA_FLOWS else []

    def _clear(self) -> None:
        self.selected = ""
        self.steps, self.problems, self.log, self.artifacts, self.facts, self.charts = [], [], [], [], [], []
        self.problems_json, self.wave_url, self.picture, self.error = "[]", "", "", ""
        self.board_jobs = []

    @rx.event
    async def select(self, run_id: str):
        ide = await self.get_state(IdeState)
        run = engine.get(run_id)
        if run is None or run.project_id != ide.project_id:
            return None
        self.selected = run_id
        self.log_step = ""
        self._load(run, await self._user())
        if not run.status.finished:
            return RunState.follow
        return None

    @rx.event
    async def select_latest(self):
        ide = await self.get_state(IdeState)
        if self.selected:
            run = engine.get(self.selected)
            if run is not None and run.project_id == ide.project_id:
                return RunState.select(run.id)
        self._clear()
        latest = engine.runs_of(ide.project_id, limit=1)
        if latest:
            return RunState.select(latest[0].id)
        return None

    @rx.event
    async def select_for(self, view: str):
        """Opening a section shows a run of its kind (the selected one, or its latest)."""
        kinds = {"verify": ("verify",), "implement": ("implement", "ams")}.get(view)
        if not kinds:
            return None
        ide = await self.get_state(IdeState)
        current = engine.get(self.selected) if self.selected else None
        if current is not None and current.project_id == ide.project_id:
            f = flows.get(current.flow_id)
            if f is not None and f.definition.category in kinds:
                return None
        for run in engine.runs_of(ide.project_id, limit=100):
            f = flows.get(run.flow_id)
            if f is not None and f.definition.category in kinds:
                return RunState.select(run.id)
        self._clear()
        return None

    @rx.event
    async def refresh(self):
        if self.selected:
            run = engine.get(self.selected)
            if run is not None:
                self._load(run, await self._user())

    @rx.event
    async def set_log_step(self, node: str):
        self.log_step = "" if node == self.log_step else node
        run = engine.get(self.selected)
        if run is not None:
            self.log = engine.tail(run, self.log_step, LOG_LINES)

    @rx.event(background=True)
    async def follow(self):
        """Keeps the selected run's steps and output up to date while it runs."""
        async with self:
            if self._following:
                return
            self._following = True
            rid = self.selected
            token = self.router.session.client_token
        try:
            while True:
                await asyncio.sleep(FOLLOW_EVERY)
                if not _connected(token):
                    return
                async with self:
                    if self.selected != rid:
                        return
                    run = engine.get(rid)
                    if run is None:
                        return
                    user = (await self.get_state(UiState)).me.get("user", "")
                    if run.status.finished:
                        self._load(run, user)
                        return
                    self._load(run, user, full=False)
        finally:
            async with self:
                self._following = False

    # -------------------------------------------------------- deciding

    async def _actor(self):
        return (await self.get_state(UiState)).actor()

    @rx.event
    async def approve(self, run_id: str):
        actor = await self._actor()
        try:
            run = await engine.approve(run_id, actor)
        except (projects.Denied, flows.FlowError, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        note(run.project_id, actor.name, f"approved the {run.flow_id} run the AI asked for", "run")
        push_later(run.project_id, "runs")
        return RunState.select(run_id)

    @rx.event
    async def reject(self, run_id: str):
        actor = await self._actor()
        try:
            run = await engine.reject(run_id, actor, "not approved")
        except (projects.Denied, flows.FlowError, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        note(run.project_id, actor.name, f"rejected the {run.flow_id} run the AI asked for", "run")
        push_later(run.project_id, "runs")
        return RunState.select(run_id)

    @rx.event
    async def cancel(self, run_id: str):
        actor = await self._actor()
        try:
            run = await engine.cancel(run_id, actor)
        except (projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        note(run.project_id, actor.name, f"stopped run {run.id}", "run")
        push_later(run.project_id, "runs")
        return RunState.refresh

    @rx.event
    async def verify(self, artifact_id: str):
        a = artifacts.get(artifact_id)
        ide = await self.get_state(IdeState)
        if a is None or a.project_id != ide.project_id:
            return None
        ok = await asyncio.to_thread(artifacts.verify, a)
        if ok:
            return rx.toast.success(f"{a.name}: SHA-256 matches ({a.sha256[:16]}…)", position="bottom-right")
        return rx.toast.error(f"{a.name}: the file no longer matches its recorded SHA-256", position="bottom-right")

    @rx.event
    async def rerun(self):
        """Runs the same flow with the same parameters on the same snapshot again."""
        run = engine.get(self.selected)
        if run is None:
            return None
        ide = await self.get_state(IdeState)
        return await ide._submit(run.flow_id, run.revision_id, run.params)
