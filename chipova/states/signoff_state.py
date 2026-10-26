"""The Signoff and Release sections: a snapshot's checklist with its evidence and waivers, and
its releases (gate, approvals, the package)."""

from __future__ import annotations

import asyncio
import dataclasses

import reflex as rx

from chipova import ids
from chipova.domain.machines import InvalidTransition
from chipova.jobs import engine, flows, flows_chip
from chipova.services import artifacts, projects, releases, revisions, signoff
from chipova.states.ide import IdeState
from chipova.states.room import note, push_later
from chipova.states.ui_state import UiState


@dataclasses.dataclass
class CheckRow:
    category: str = ""
    title: str = ""
    status: str = ""
    required: bool = False
    summary: str = ""
    why: str = ""
    run: str = ""
    deck: str = ""
    waiver: str = ""


@dataclasses.dataclass
class WaiverRow:
    id: str = ""
    category: str = ""
    rule: str = ""
    reason: str = ""
    by: str = ""
    status: str = ""
    approved_by: str = ""
    mine: bool = False


@dataclasses.dataclass
class ReleaseRow:
    id: str = ""
    title: str = ""
    status: str = ""
    snapshot: str = ""
    by: str = ""
    at: float = 0.0
    gate_ok: bool = False
    missing: list[str] = dataclasses.field(default_factory=list)
    approvals: str = ""
    package: str = ""  # sha256 of the built package
    href: str = ""  # signed path of the package download
    mine: bool = False


class SignoffState(rx.State):
    revision: str = ""
    revision_short: str = ""
    checks: list[CheckRow] = []
    waivers: list[WaiverRow] = []
    waiver_category: str = ""
    waiver_rule: str = ""
    waiver_reason: str = ""
    releases: list[ReleaseRow] = []
    new_release_open: bool = False
    new_release_title: str = ""
    decision_id: str = ""
    decision_kind: str = ""  # approve | reject | foundry_ready
    decision_text: str = ""

    async def _actor(self):
        return (await self.get_state(UiState)).actor()

    @rx.event
    async def load(self, revision: str = ""):
        ide = await self.get_state(IdeState)
        pid = ide.project_id
        rev = revisions.get(pid, revision) if revision else (revisions.get(pid, self.revision) if self.revision else None)
        rev = rev or revisions.latest(pid)
        if rev is None:
            self.checks, self.revision = [], ""
            return
        self.revision = rev.id
        self.revision_short = ids.short_revision(rev.id)
        me = (await self.get_state(UiState)).me.get("user", "")
        rows = []
        for c in signoff.checklist(pid, rev.id):
            w = c.waivers[0] if c.waivers else None
            rows.append(CheckRow(
                category=c.category, title=c.title, status=c.status.value, required=c.required, summary=c.summary,
                why=c.why, run=c.run_id, deck=c.rule_deck,
                waiver=f"{w.rule_id}: {w.reason} (approved by {w.approved_by_name})" if w else "",
            ))
        self.checks = rows
        self.waivers = [
            WaiverRow(w.id, w.category, w.rule_id, w.reason, w.requested_by_name, w.status, w.approved_by_name, w.requested_by == me)
            for w in signoff.waivers(pid, rev.id)
        ]
        await self._load_releases(pid, me)

    async def _load_releases(self, pid: str, me: str) -> None:
        out = []
        for r in releases.of_project(pid):
            ok, missing = releases.gate(r)
            href = ""
            if r.package_artifact and releases.package_path(r).is_file():
                href = f"/_chipova/release/{r.id}?" + artifacts.query(r.id, me)
            out.append(ReleaseRow(
                id=r.id, title=r.title, status=r.status.value, snapshot=ids.short_revision(r.revision_id), by=r.requested_by_name,
                at=r.created_at, gate_ok=ok, missing=missing,
                approvals=", ".join(f"{a.get('name')}: {a.get('decision')}" for a in r.approvals), package=r.package_artifact[:16],
                href=href, mine=r.requested_by == me,
            ))
        self.releases = out

    @rx.event
    async def pick_revision(self, revision_id: str):
        await self.load(revision_id)

    @rx.event
    async def run_checks(self):
        """Starts the signoff flows this snapshot can run (each on its latest Build ASIC run)."""
        ide = await self.get_state(IdeState)
        actor = await self._actor()
        started, problems = [], []
        asic = next((r for r in engine.runs_of(ide.project_id, limit=200, flow_id="asic_sc", revision_id=self.revision) if r.status.value == "SUCCEEDED"), None)
        rev = revisions.get(ide.project_id, self.revision)
        has_plan = rev is not None and set(flows.PACKAGE_FILES) <= {e["path"] for e in rev.files}
        is_chip = rev is not None and set(flows_chip.MARKERS) <= {e["path"] for e in rev.files}
        # The layout's checks are for chips, not for an FPGA project.
        kind = projects.must(ide.project_id).kind.value
        layout = kind in ("digital_asic", "ams")
        for flow_id in ("rtl_lint", "rtl_sim", *(("signoff_drc", "signoff_lvs", "signoff_openroad") if layout else ()), *(("ams_cace",) if kind == "ams" else ()),
                        *(("package_check",) if has_plan else ()), *(("fullchip_ihp",) if is_chip else ())):
            f = flows.get(flow_id)
            if f is None:
                continue
            if f.needs_source and asic is None:
                problems.append(f"{f.definition.title}: needs a succeeded Build ASIC run on this snapshot")
                continue
            try:
                await engine.submit(ide.project_id, flow_id, actor, revision=self.revision, source_run=asic.id if (f.needs_source and asic) else "")
                started.append(f.definition.title)
            except (flows.FlowError, projects.Denied) as e:
                problems.append(f"{f.definition.title}: {e}")
        if started:
            note(ide.project_id, actor.name, f"started the checks of {self.revision_short}: {', '.join(started)}", "run")
            push_later(ide.project_id, "runs")
        await self.load(self.revision)
        msg = ("Started: " + ", ".join(started) + ". ") if started else ""
        if problems:
            return rx.toast.warning(msg + "Not started: " + "; ".join(problems), position="bottom-right", duration=12000)
        return rx.toast.success(msg or "Nothing to start.", position="bottom-right")

    # -------------------------------------------------------- waivers

    @rx.event
    def ask_waiver(self, category: str):
        self.waiver_category, self.waiver_rule, self.waiver_reason = category, "", ""

    @rx.event
    def cancel_waiver(self):
        self.waiver_category = ""

    @rx.event
    def set_waiver_rule(self, value: str):
        self.waiver_rule = value

    @rx.event
    def set_waiver_reason(self, value: str):
        self.waiver_reason = value

    @rx.event
    async def request_waiver(self):
        ide = await self.get_state(IdeState)
        actor = await self._actor()
        try:
            signoff.request_waiver(ide.project_id, self.revision, self.waiver_category, self.waiver_rule, self.waiver_reason, actor)
        except (ValueError, projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        note(ide.project_id, actor.name, f"asked to waive {self.waiver_category} on {self.revision_short}", "review")
        self.waiver_category = ""
        await self.load(self.revision)
        return None

    @rx.event
    async def decide_waiver(self, waiver_id: str, approve: bool):
        ide = await self.get_state(IdeState)
        actor = await self._actor()
        try:
            w = signoff.decide_waiver(waiver_id, approve, actor)
        except (ValueError, projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        note(ide.project_id, actor.name, f"{'approved' if approve else 'rejected'} the {w.category} waiver", "review")
        await self.load(self.revision)
        return None

    # -------------------------------------------------------- releases

    @rx.event
    def open_new_release(self):
        self.new_release_open, self.new_release_title = True, ""

    @rx.event
    def set_new_release_open(self, value: bool):
        self.new_release_open = value

    @rx.event
    def set_new_release_title(self, value: str):
        self.new_release_title = value

    @rx.event
    async def create_release(self):
        ide = await self.get_state(IdeState)
        actor = await self._actor()
        try:
            r = releases.create(ide.project_id, self.revision, self.new_release_title, actor)
        except (projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.new_release_open = False
        note(ide.project_id, actor.name, f"started release “{r.title}” of {self.revision_short}", "review")
        await self.load(self.revision)
        return None

    async def _do(self, fn, *args):  # noqa: ANN001, ANN002
        ide = await self.get_state(IdeState)
        try:
            r = fn(*args)
        except (projects.Denied, projects.Conflict, projects.NotFound, InvalidTransition, ValueError) as e:
            return None, rx.toast.error(str(e), position="bottom-right", duration=12000)
        await self.load(self.revision)
        return r, None

    @rx.event
    async def request_review(self, release_id: str):
        actor = await self._actor()
        r, err = await self._do(releases.request_review, release_id, actor)
        if r is not None:
            ide = await self.get_state(IdeState)
            note(ide.project_id, actor.name, f"asked for a review of release “{r.title}”", "review")
        return err

    @rx.event
    async def reopen(self, release_id: str):
        _, err = await self._do(releases.reopen, release_id, await self._actor())
        return err

    @rx.event
    def ask_decision(self, release_id: str, kind: str):
        self.decision_id, self.decision_kind, self.decision_text = release_id, kind, ""

    @rx.event
    def cancel_decision(self):
        self.decision_id = ""

    @rx.event
    def set_decision_text(self, value: str):
        self.decision_text = value

    @rx.event
    async def decide(self):
        actor = await self._actor()
        rid, kind, text = self.decision_id, self.decision_kind, self.decision_text
        fn = {"approve": releases.approve, "reject": releases.reject, "foundry_ready": releases.mark_foundry_ready}[kind]
        r, err = await self._do(fn, rid, actor, text)
        if r is not None:
            self.decision_id = ""
            ide = await self.get_state(IdeState)
            note(ide.project_id, actor.name, f"{kind.replace('_', ' ')}: release “{r.title}”", "review")
        return err

    @rx.event
    async def build_package(self, release_id: str):
        actor = await self._actor()
        try:
            r = await asyncio.to_thread(releases.build_package, release_id, actor)
        except (projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        await self.load(self.revision)
        return rx.toast.success(f"Package built: SHA-256 {r.package_artifact[:16]}…", position="bottom-right")

