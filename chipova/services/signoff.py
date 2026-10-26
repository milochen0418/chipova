"""The signoff checklist of a snapshot (blueprint 10.1), worked out from its runs every time.

Each check is NOT_CONFIGURED, NOT_RUN, RUNNING, PASS, FAIL, WAIVED or BLOCKED, from the runs on
that snapshot and nothing else:

- a check passes only when a run of its flow on that very snapshot reported so (a lint of an
  older snapshot proves nothing about this one);
- a check that is required but can't run here (no rule deck for the PDK, no tool, no layout yet)
  is BLOCKED, with the reason; an optional one that isn't set up is NOT_CONFIGURED;
- a waiver turns a check into WAIVED (never PASS) and needs a reason, the rule it covers, and
  an approver other than whoever asked for it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from chipova import ids
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import ProjectKind, Run, RunStatus, SignoffCheck, SignoffStatus, Waiver
from chipova.jobs import engine, flows, profiles
from chipova.services import audit, projects, revisions, settings_file
from chipova.services.actors import Actor


@dataclass(frozen=True)
class Check:
    category: str
    title: str
    kinds: tuple[str, ...]  # the project kinds it applies to
    required: tuple[str, ...]  # the kinds a release needs it for
    evidence: str  # what it needs: the text shown in the table


CHECKS: tuple[Check, ...] = (
    Check("lint", "RTL lint", ("digital_asic", "fpga"), (), "A clean rtl_lint run (Verilator, Icarus)"),
    Check("sim", "Functional simulation", ("digital_asic", "fpga"), ("digital_asic", "fpga"), "An rtl_sim run whose testbench printed PASS and no FAIL/ERROR"),
    Check("fpga_timing", "FPGA timing", ("fpga",), ("fpga",), "A Build FPGA run (iCE40, ECP5 or Gowin) meeting the target clock on every clock"),
    Check("drc", "DRC", ("digital_asic", "ams"), ("digital_asic", "ams"), "The PDK's DRC deck run on the GDS of a Build ASIC run: 0 violations"),
    Check("lvs", "LVS", ("digital_asic", "ams"), ("digital_asic", "ams"), "Layout vs. netlist with the PDK's LVS setup: circuits match"),
    Check("sta", "STA", ("digital_asic",), ("digital_asic",), "Setup and hold met at every corner: OpenSTA with each RC corner's extracted parasitics (Run checks)"),
    Check("pex", "PEX", ("digital_asic", "ams"), (), "OpenRCX with the PDK's rules: one SPEF per RC corner, every routed net in it"),
    Check("power", "Power / IR", ("digital_asic",), (), "Power and static IR drop (PDNSim) at every corner: the drop under 5 % of VDD"),
    Check("antenna", "Antenna", ("digital_asic",), ("digital_asic",), "OpenROAD's antenna check with the PDK's LEF rules: no violating net or pin"),
    Check("ams_pvt", "AMS PVT corners", ("ams",), ("ams",), "A CACE run of this snapshot's datasheet: every spec met at every process corner, supply and temperature"),
    Check("package", "Package & pinout", ("digital_asic", "ams"), ("digital_asic",), "A package_check run of this snapshot: every port on one pin, the pins within the package, power and ground pins"),
    Check("fullchip", "Full chip", ("digital_asic", "ams"), (), "A Full chip run of the IHP chip template: padframe, seal ring, macros, the chip's DRC and gate-level LVS"),
)

# category -> how its status is worked out (the default: not set up in Chipova yet).
Resolver = Callable[["_Ctx", Check], SignoffCheck]
_resolvers: dict[str, Resolver] = {}


def resolver(category: str):
    def deco(fn: Resolver) -> Resolver:
        _resolvers[category] = fn
        return fn

    return deco


@dataclass
class _Ctx:
    project_id: str
    kind: str
    revision_id: str
    runs: list[Run]
    pdk: str
    testbench: str
    files: tuple[str, ...] = ()  # the snapshot's
    cace: str = ""  # its CACE datasheet (chipova.toml [ams] cace)

    def latest(self, flow_id: str, source_run: str = "") -> Run | None:
        for r in self.runs:  # newest first
            if r.flow_id == flow_id and (not source_run or r.source_run == source_run):
                if r.status == RunStatus.CANCELED and r.approval_status.value == "REJECTED":
                    continue
                return r
        return None


def _from_run(check: Check, run: Run | None, passed: Callable[[Run], tuple[bool, str]], deck: str = "") -> SignoffCheck:
    base = {"category": check.category, "title": check.title, "rule_deck": deck}
    if run is None:
        return SignoffCheck(**base, status=SignoffStatus.NOT_RUN, why=check.evidence)
    evidence = [{"run": run.id, "flow": run.flow_id, "status": run.status.value}]
    if run.status in (RunStatus.QUEUED, RunStatus.RUNNING) or (run.status == RunStatus.CREATED):
        return SignoffCheck(**base, status=SignoffStatus.RUNNING, run_id=run.id, evidence=evidence, summary="running" if run.status == RunStatus.RUNNING else "waiting")
    if run.status != RunStatus.SUCCEEDED:
        return SignoffCheck(**base, status=SignoffStatus.FAIL, run_id=run.id, evidence=evidence, summary=run.error or run.status.value)
    ok, summary = passed(run)
    return SignoffCheck(**base, status=SignoffStatus.PASS if ok else SignoffStatus.FAIL, run_id=run.id, evidence=evidence, summary=summary)


@resolver("lint")
def _lint(ctx: _Ctx, check: Check) -> SignoffCheck:
    def passed(r: Run) -> tuple[bool, str]:
        e, w = int(r.problems.get("errors", 0) or 0), int(r.problems.get("warnings", 0) or 0)
        return e == 0, f"{e} errors, {w} warnings"

    return _from_run(check, ctx.latest("rtl_lint"), passed)


@resolver("sim")
def _sim(ctx: _Ctx, check: Check) -> SignoffCheck:
    if not ctx.testbench:
        return SignoffCheck(category=check.category, title=check.title, status=SignoffStatus.BLOCKED, why="The snapshot's chipova.toml names no testbench.")

    def passed(r: Run) -> tuple[bool, str]:
        s = r.summary or {}
        ok = s.get("pass_lines", 0) > 0 and s.get("fail_lines", 0) == 0
        return ok, f"PASS lines {s.get('pass_lines', 0)}, FAIL/ERROR lines {s.get('fail_lines', 0)}"

    return _from_run(check, ctx.latest("rtl_sim"), passed)


@resolver("fpga_timing")
def _fpga(ctx: _Ctx, check: Check) -> SignoffCheck:
    def passed(r: Run) -> tuple[bool, str]:
        fmax = (r.summary or {}).get("fmax") or {}
        if not fmax:
            return False, "nextpnr reported no clock"
        bad = [f"{c}: {v['achieved_mhz']} < {v['constraint_mhz']} MHz" for c, v in fmax.items() if v["achieved_mhz"] < v["constraint_mhz"]]
        return not bad, "; ".join(bad) or ", ".join(f"{c}: {v['achieved_mhz']} MHz ≥ {v['constraint_mhz']} MHz" for c, v in fmax.items())

    builds = [r for r in (ctx.latest(f) for f in flows.FPGA_FLOWS) if r is not None]
    return _from_run(check, max(builds, key=lambda r: r.created_at) if builds else None, passed)


@resolver("ams_pvt")
def _ams(ctx: _Ctx, check: Check) -> SignoffCheck:
    if not ctx.cace or ctx.cace not in ctx.files:
        return SignoffCheck(category=check.category, title=check.title, status=SignoffStatus.BLOCKED,
                            why="The snapshot has no CACE datasheet: chipova.toml's [ams] cace names it (the corner templates have one).")

    def passed(r: Run) -> tuple[bool, str]:
        s = r.summary or {}
        return s.get("cace_status") == "PASS", s.get("headline", "")

    return _from_run(check, ctx.latest("ams_cace"), passed, deck=f"CACE, {ctx.cace}")


@resolver("package")
def _package(ctx: _Ctx, check: Check) -> SignoffCheck:
    if not all(f in ctx.files for f in flows.PACKAGE_FILES):
        return SignoffCheck(category=check.category, title=check.title, status=SignoffStatus.BLOCKED,
                            why="The snapshot has no package plan (package/package.toml and package/pins.csv).")

    def passed(r: Run) -> tuple[bool, str]:
        s = r.summary or {}
        return bool(s.get("ok")), "; ".join([s.get("headline", ""), *(s.get("plan_problems") or [])[:3]])

    return _from_run(check, ctx.latest("package_check"), passed)


def _not_set_up(ctx: _Ctx, check: Check) -> SignoffCheck:
    required = ctx.kind in check.required
    return SignoffCheck(
        category=check.category,
        title=check.title,
        status=SignoffStatus.BLOCKED if required else SignoffStatus.NOT_CONFIGURED,
        required=required,
        why="Not set up in Chipova for this PDK yet: " + check.evidence + ".",
    )


def checklist(project_id: str, revision_id: str) -> list[SignoffCheck]:
    """The checks of a snapshot, as its runs and waivers make them now."""
    from chipova.jobs import flows_asic  # noqa: PLC0415 — adds the layout checks' rules

    flows_asic.register()
    p = projects.must(project_id)
    rev = revisions.get(project_id, revision_id)
    if rev is None:
        raise projects.NotFound(f"there is no snapshot {revision_id!r}")
    try:
        settings, _ = settings_file.parse(revisions.show(project_id, rev, settings_file.FILE).decode("utf-8"))
    except RuntimeError:
        settings, _ = settings_file.parse("")
    ctx = _Ctx(project_id, p.kind.value, revision_id, engine.runs_of(project_id, limit=500, revision_id=revision_id), settings.pdk, settings.testbench,
               tuple(e["path"] for e in rev.files), settings.cace)
    waived = {w.category: w for w in waivers(project_id, revision_id) if w.status == "APPROVED"}
    out = []
    for check in CHECKS:
        if ctx.kind not in check.kinds:
            continue
        fn = _resolvers.get(check.category, _not_set_up)
        result = fn(ctx, check)
        result.required = ctx.kind in check.required
        if result.status in (SignoffStatus.BLOCKED, SignoffStatus.NOT_CONFIGURED) and not result.why:
            result.why = check.evidence
        w = waived.get(check.category)
        if w is not None and result.status != SignoffStatus.PASS:
            result.status = SignoffStatus.WAIVED
            result.waivers = [w]
        out.append(result)
    return out


# ------------------------------------------------------------ waivers


def waivers(project_id: str, revision_id: str = "") -> list[Waiver]:
    sql, args = "SELECT * FROM waivers WHERE project_id = ?", [project_id]
    if revision_id:
        sql += " AND revision_id = ?"
        args.append(revision_id)
    return [Waiver.from_row(r) for r in db().query(sql + " ORDER BY created_at DESC", args)]


def request_waiver(project_id: str, revision_id: str, category: str, rule_id: str, reason: str, actor: Actor) -> Waiver:
    projects.require(project_id, actor, roles.COMMENT, category)
    if actor.is_agent:
        raise projects.Denied("An AI agent may not ask for waivers")
    if category not in {c.category for c in CHECKS}:
        raise ValueError(f"no check {category!r}")
    if revisions.get(project_id, revision_id) is None:
        raise projects.NotFound("no such snapshot")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValueError("a waiver needs a real reason (what is waived and why it is safe)")
    w = Waiver(
        id=ids.new_id("wv"), project_id=project_id, revision_id=revision_id, category=category, rule_id=(rule_id or "").strip()[:200] or "all",
        reason=reason[:4000], requested_by=actor.user, requested_by_name=actor.name, status="PROPOSED", created_at=time.time(),
    )
    db().insert("waivers", w.model_dump(mode="json"))
    audit.record("waiver.request", actor, project_id, w.id, {"category": category, "rule": w.rule_id, "revision": revision_id, "reason": reason})
    return w


def decide_waiver(waiver_id: str, approve: bool, actor: Actor) -> Waiver:
    row = db().one("SELECT * FROM waivers WHERE id = ?", (waiver_id,))
    if row is None:
        raise projects.NotFound("no such waiver")
    w = Waiver.from_row(row)
    projects.require(w.project_id, actor, roles.APPROVE_WAIVER, waiver_id)
    if w.status != "PROPOSED":
        raise ValueError(f"this waiver is {w.status} already")
    if actor.user == w.requested_by:
        raise projects.Denied("who asked for a waiver can't approve it")
    status = "APPROVED" if approve else "REJECTED"
    db().update("waivers", {"id": waiver_id}, {"status": status, "approved_by": actor.user, "approved_by_name": actor.name, "decided_at": time.time()})
    audit.record(f"waiver.{status.lower()}", actor, w.project_id, waiver_id, {"category": w.category, "revision": w.revision_id})
    return Waiver.from_row(db().one("SELECT * FROM waivers WHERE id = ?", (waiver_id,)))


def profile_ready(profile_id: str) -> bool:
    p = profiles.get(profile_id)
    return p is not None and profiles.installed(p) is not None


def flow_ready(flow_id: str) -> tuple[bool, str]:
    f = flows.get(flow_id)
    if f is None:
        return False, f"the {flow_id} flow isn't available"
    if profiles.first_installed(f.definition.profiles) is None:
        return False, "its tool profile isn't installed (Settings page)"
    return True, ""
