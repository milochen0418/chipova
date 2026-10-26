"""The ASIC flows on the IIC-OSIC-TOOLS profile: Build ASIC (SiliconCompiler, RTL to GDSII) and
the signoff checks of its layout (DRC, LVS), plus what the Signoff page makes of them.

Build ASIC runs ``sc_flow.py`` (in ``container/asic``), which drives SiliconCompiler 0.38's new
API offline (the PDK data is baked into the image): Yosys, then OpenROAD through floorplan,
placement, clock tree and routing, then KLayout's GDS export. SiliconCompiler's flow nodes are
shown as steps of the run, live while it runs (the driver's markers) and with their own numbers
and logs once it ends. Its SKY130 GDS holds LEF abstracts of the standard cells, so the driver
also writes ``<top>.full.gds`` with the real cell layouts: that is the layout the checks and the
Layout page use.

DRC (KLayout's sky130A_mr deck and Magic) and LVS (Magic extraction, Netgen) check the layout of
a succeeded Build ASIC run, given to them read-only under /work/in. Only SKY130 has them here
(see :mod:`chipova.jobs.pdks`). A check that finds violations fails its run, with the rules it
found broken.
"""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from chipova.db import db
from chipova.domain.models import FlowDefinition, Run, RunStatus, SignoffCheck, SignoffStatus, StepStatus
from chipova.jobs import flows, pdks
from chipova.jobs.docker_runner import Limits
from chipova.jobs.flows import JOB, OSIC, OUT, SRC, Context, Flow, FlowError, JobSpec, Step, _need, _p, rtl_files

ASIC_DIR = Path(__file__).parent / "container" / "asic"
SC_BUILD = "/work/tmp/sc"
THREADS = 6

# SiliconCompiler 0.38's ASIC flow, in its order (shown before the run reports its own).
SC_NODES = [
    "elaborate", "synthesis", "cleanup.clean", "synthesis.timing", "floorplan.init", "floorplan.macro_placement",
    "floorplan.tapcell", "floorplan.power_grid", "floorplan.pin_placement", "place.global", "place.repair_design",
    "place.detailed", "cts.clock_tree_synthesis", "cts.repair_timing", "cts.fillcell", "route.global",
    "route.repair_timing", "route.antenna_repair", "route.detailed", "route.detailed_antenna_repair",
    "dfm.metal_fill", "write.gds", "write.views",
]

ASIC_LABELS = {
    "pdk": "PDK",
    "cellarea_um2": "Cell area (µm²)",
    "totalarea_um2": "Die area (µm²)",
    "utilization_pct": "Utilisation (%)",
    "setup_slack_ns": "Setup slack (ns)",
    "hold_slack_ns": "Hold slack (ns)",
    "fmax_mhz": "Fmax (MHz)",
    "power_mw": "Peak power (mW, estimate)",
    "wirelength_um": "Wire length (µm)",
    "router_drcs": "Router DRC count",
    "drvs": "Electrical violations",
    "sc_version": "SiliconCompiler",
}


def _scripts() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(ASIC_DIR.iterdir()) if p.is_file() and p.suffix in (".py", ".sh", ".tcl")}


def node_id(step: str, index: str = "0") -> str:
    return f"sc.{step}.{index}"


# ------------------------------------------------------------ Build ASIC


def _asic(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    pdk = pdks.get(ctx.params["pdk"])
    if pdk is None or not pdk.flow:
        raise FlowError(f"Build ASIC doesn't work for {ctx.params['pdk']!r} here: {pdk.status if pdk else 'no such PDK'}")
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    scripts = _scripts()
    if ctx.settings.sdc:
        if ctx.settings.sdc not in ctx.files:
            raise FlowError(f"chipova.toml names the constraints {ctx.settings.sdc}, which the snapshot doesn't have")
        sdc = f"{SRC}/{ctx.settings.sdc}"
    else:
        # No constraints file: the clock from the settings.
        port = ctx.settings.clock_port
        if not flows.IDENT.match(port or ""):
            raise FlowError("set the clock port in Settings (or a .sdc file)")
        period = float(ctx.settings.clock_period_ns)
        scripts["auto.sdc"] = (
            f"create_clock -name {port} -period {period:g} [get_ports {{{port}}}]\n"
            f"set_input_delay -clock {port} 0 [all_inputs]\nset_output_delay -clock {port} 0 [all_outputs]\n"
        ).encode()
        sdc = f"{JOB}/auto.sdc"
    argv = ["python3", f"{JOB}/sc_flow.py", "--top", top]
    for f in files:
        argv += ["--src", f"{SRC}/{f}"]
    argv += [
        "--sdc", sdc, "--pdk", pdk.sc_target, "--threads", str(THREADS), "--png-res", "1024", "--full-png", "1024",
        "--builddir", f"{SC_BUILD}/build", "--out", f"{OUT}/asic/result.json", "--collect", f"{OUT}/asic/final",
    ]
    if ctx.params["density"] > 0:
        argv += ["--density", f"{ctx.params['density']:g}"]
    steps = [
        Step("flow", "SiliconCompiler RTL → GDSII", "siliconcompiler", argv, cwd="/work/tmp", timeout=3500),
        Step("lyp", "Layer colours", "generic", ["cp", pdk.lyp, f"{OUT}/asic/final/{pdk.id}.lyp"], timeout=60, optional=True),
        *[Step(node_id(s), s, "openroad", [], virtual=True) for s in SC_NODES],
    ]
    return JobSpec(
        steps=steps,
        scripts=scripts,
        artifacts=[
            ("asic/final/*.full.gds", "gds"),
            ("asic/final/*.gds.gz", "gds_abstract"),
            ("asic/final/*.lyp", "lyp"),
            ("asic/final/*.full.png", "image"),
            ("asic/final/*.png", "image"),
            ("asic/final/*.def.gz", "def"),
            ("asic/final/*.lvs.vg", "netlist"),
            ("asic/final/*.vg", "netlist"),
            ("asic/final/*.spef", "spef"),
            ("asic/final/*.sdc", "sdc"),
            ("asic/final/*.lef", "lef"),
            ("asic/final/job.log", "log"),
            ("asic/final/logs/*.log", "log"),
            ("asic/result.json", "report"),
        ],
        limits=Limits(cpus=THREADS, memory_mb=6144, pids=4096, timeout=3600),
        # UTC: the image's own TZ is Vienna, and SiliconCompiler records local times.
        env={"PYTHONPYCACHEPREFIX": "/work/tmp/pycache", "TZ": "UTC"},
    )


# ------------------------------------------------------------ DRC and LVS


def _layout_of(ctx: Context, what: str) -> tuple[str, pdks.Pdk, Path]:
    src = ctx.source_run
    if src is None:
        raise FlowError(f"{what} checks the layout of a succeeded Build ASIC run: give its id")
    pdk = pdks.get(str(src.params.get("pdk", "")))
    deck = (pdk.drc if what == "DRC" else pdk.lvs) if pdk else ""
    if not deck:
        raise FlowError(f"no {what} is set up for {src.params.get('pdk')!r} in Chipova (SKY130 has one)")
    top = str(src.params.get("top", ""))
    gds = ctx.source_files.get(f"asic/final/{top}.full.gds")
    if gds is None or not gds.is_file():
        raise FlowError("that Build ASIC run kept no full GDS")
    return top, pdk, gds


def _drc(ctx: Context) -> JobSpec:
    top, _, gds = _layout_of(ctx, "DRC")
    layout = f"/work/in/{top}.full.gds"
    return JobSpec(
        steps=[
            Step("klayout", "KLayout DRC (sky130A_mr)", "klayout_drc", ["bash", f"{JOB}/drc_klayout.sh", layout, top, f"{OUT}/drc/klayout", "4"],
                 env={"STDCELL_GDS": "none"}, timeout=3600, continue_on_fail=True),
            Step("magic", "Magic DRC", "magic_drc", ["bash", f"{JOB}/drc_magic.sh", layout, top, f"{OUT}/drc/magic"],
                 env={"STDCELL_GDS": "none"}, timeout=3600),
        ],
        scripts=_scripts(),
        inputs={f"{top}.full.gds": gds},
        artifacts=[
            ("drc/klayout/drc.lyrdb", "report"), ("drc/klayout/drc.json", "json"), ("drc/klayout/markers.json", "json"),
            ("drc/magic/magic_drc.rpt", "report"), ("drc/magic/magic_drc.json", "json"),
        ],
        limits=Limits(cpus=4, memory_mb=4096, timeout=3600),
    )


def _lvs(ctx: Context) -> JobSpec:
    top, _, gds = _layout_of(ctx, "LVS")
    netlist = ctx.source_files.get(f"asic/final/{top}.vg")
    if netlist is None or not netlist.is_file():
        raise FlowError("that Build ASIC run kept no gate-level netlist")
    return JobSpec(
        steps=[Step("lvs", "Magic extraction + Netgen LVS", "netgen",
                    ["bash", f"{JOB}/lvs.sh", f"/work/in/{top}.full.gds", f"/work/in/{top}.vg", top, f"{OUT}/lvs"], timeout=3600)],
        scripts=_scripts(),
        inputs={f"{top}.full.gds": gds, f"{top}.vg": netlist},
        artifacts=[("lvs/lvs.rpt", "report"), ("lvs/lvs_result.json", "json"), (f"lvs/{top}.spice", "spice")],
        limits=Limits(cpus=2, memory_mb=4096, timeout=3600),
    )


# ------------------------------------------------------------ numbers after a run


def _stamp(value) -> float:  # noqa: ANN001
    """A SiliconCompiler record time ("2026-10-26 08:16:59.055476", in the job's TZ, UTC) as a
    timestamp."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _asic_metrics(run: Run, out: Path, summary: dict) -> None:
    res = _read(out / "asic" / "result.json")
    if not res:
        return
    s = res.get("summary") or {}

    def val(name: str):  # noqa: ANN202
        return (s.get(name) or {}).get("value")

    fmax = val("fmax")
    picked = {
        "pdk": run.params.get("pdk", ""),
        "cells": val("cells"),
        "cellarea_um2": val("cellarea"),
        "totalarea_um2": val("totalarea"),
        "utilization_pct": round(val("utilization"), 1) if val("utilization") is not None else None,
        "setup_slack_ns": val("setupslack"),
        "hold_slack_ns": val("holdslack"),
        "setup_wns_ns": val("setupwns"),
        "hold_wns_ns": val("holdwns"),
        "fmax_mhz": round(fmax / 1e6, 1) if fmax else None,
        "power_mw": val("peakpower"),
        "irdrop_mv": val("irdrop"),
        "wirelength_um": val("wirelength"),
        "router_drcs": val("drcs"),
        "drvs": val("drvs"),
        "sc_version": res.get("sc_version", ""),
        "failed_nodes": res.get("failed_nodes", []),
    }
    summary.update({k: v for k, v in picked.items() if v not in (None, "", [])})
    if picked["cells"] is not None:
        summary["headline"] = f"{picked['cells']} cells" + (f" · {picked['fmax_mhz']:.0f} MHz" if picked["fmax_mhz"] else "")
    summary["_labels"] = ASIC_LABELS
    if not res.get("ok") and res.get("error"):
        summary["error_text"] = "SiliconCompiler: " + str(res["error"])[:400]
    # The flow's nodes as the run's steps: their states, times, numbers and logs.
    nodes = res.get("nodes") or []
    if nodes:
        db().execute("DELETE FROM run_steps WHERE run_id = ? AND node LIKE 'sc.%'", (run.id,))
        states = {"success": StepStatus.SUCCEEDED, "skipped": StepStatus.SKIPPED, "error": StepStatus.FAILED, "timeout": StepStatus.FAILED}
        logs = out / "asic" / "final" / "logs"
        for i, n in enumerate(nodes):
            nid = node_id(n["step"], str(n["index"]))
            kept = ("cells", "cellarea", "utilization", "setupslack", "holdslack", "wirelength", "drcs", "drvs", "tasktime")
            db().insert("run_steps", {
                "run_id": run.id, "idx": 100 + i, "node": nid, "title": n["step"],
                "status": states.get(n.get("status"), StepStatus.CANCELED).value,
                "started_at": _stamp(n.get("starttime")), "ended_at": _stamp(n.get("endtime")),
                "exit_code": n.get("toolexitcode"), "command": [n.get("tool") or "", n.get("task") or ""],
                "command_digest": "", "metrics": {k: v for k, v in (n.get("metrics") or {}).items() if k in kept},
            })
            dest = out / "steps" / nid / "stdout.log"
            log = logs / f"{n['step']}.{n['index']}.log"
            if log.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(log, dest)
            elif n.get("log_tail"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("\n".join(n["log_tail"]) + "\n", "utf-8")


_NUM_PAIR = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")


def drc_markers(lyrdb: Path, limit: int = 500) -> list[dict]:
    """Where each violation of a KLayout report is: its rule and bounding box (µm, top cell)."""
    try:
        root = ET.parse(lyrdb).getroot()
    except (OSError, ET.ParseError):
        return []
    out = []
    items = root.find("items")
    for item in items.findall("item") if items is not None else []:
        rule = (item.findtext("category") or "").strip().strip("'").replace("'.'", ".")
        xs, ys = [], []
        for v in item.iter("value"):
            for x, y in _NUM_PAIR.findall(v.text or ""):
                xs.append(float(x))
                ys.append(float(y))
        if xs:
            out.append({"rule": rule, "box": [min(xs), min(ys), max(xs), max(ys)]})
        if len(out) >= limit:
            break
    return out


def _drc_metrics(run: Run, out: Path, summary: dict) -> None:
    kl = _read(out / "drc" / "klayout" / "drc.json")
    markers = drc_markers(out / "drc" / "klayout" / "drc.lyrdb")
    if markers:
        (out / "drc" / "klayout" / "markers.json").write_text(json.dumps(markers), "utf-8")
        summary["markers"] = markers[:100]
    mg = _read(out / "drc" / "magic" / "magic_drc.json")
    if kl:
        summary["violations"] = int(kl.get("total", 0))
        summary["rules_checked"] = kl.get("rules_checked")
        summary["rules"] = kl.get("violated") or {}
    if mg:
        summary["magic_violations"] = int(mg.get("total", 0))
    if kl or mg:
        total = int(summary.get("violations", 0)) + int(summary.get("magic_violations", 0))
        broken = ", ".join(f"{r} ×{n}" for r, n in list((summary.get("rules") or {}).items())[:8])
        summary["headline"] = "clean" if total == 0 else f"{summary.get('violations', 0)} KLayout, {summary.get('magic_violations', 0)} Magic violations"
        if total:
            summary["error_text"] = f"DRC found violations: {broken or 'see the reports'}" + (f"; Magic: {summary['magic_violations']}" if summary.get("magic_violations") else "")
        summary["_labels"] = {"violations": "KLayout violations", "magic_violations": "Magic violations", "rules_checked": "Rules checked"}


def _lvs_metrics(run: Run, out: Path, summary: dict) -> None:
    r = _read(out / "lvs" / "lvs_result.json")
    if not r:
        return
    summary["lvs_pass"] = bool(r.get("pass"))
    summary["final_result"] = r.get("final_result", "")
    if r.get("nets"):
        summary["nets"] = r.get("nets")
    if r.get("devices"):
        summary["devices"] = " / ".join(str(d) for d in r["devices"])
    summary["headline"] = r.get("final_result", "") or ("match" if r.get("pass") else "no match")
    if not r.get("pass"):
        summary["error_text"] = f"LVS: {r.get('final_result') or 'the netlists do not match'}"
    summary["_labels"] = {"final_result": "Netgen", "nets": "Nets (layout / netlist)", "devices": "Devices (layout / netlist)"}


def metrics(run: Run, out: Path, summary: dict) -> None:
    fn = {"asic_sc": _asic_metrics, "signoff_drc": _drc_metrics, "signoff_lvs": _lvs_metrics}.get(run.flow_id)
    if fn is not None:
        fn(run, out, summary)


# ------------------------------------------------------------ the Signoff page


def _asic_run(ctx) -> Run | None:  # noqa: ANN001 — signoff._Ctx
    return next((r for r in ctx.runs if r.flow_id == "asic_sc" and r.status == RunStatus.SUCCEEDED), None)


def _layout_check(flow_id: str, what: str):  # noqa: ANN202
    def resolve(ctx, check) -> SignoffCheck:  # noqa: ANN001
        from chipova.services.signoff import _from_run  # noqa: PLC0415

        # The layout's own PDK (a Build ASIC run may have been asked for another one than chipova.toml's).
        asic = _asic_run(ctx)
        pdk_id = str((asic.params.get("pdk") if asic else "") or ctx.pdk)
        pdk = pdks.get(pdk_id)
        deck = (pdk.drc if what == "DRC" else pdk.lvs) if pdk else ""
        base = {"category": check.category, "title": check.title}
        if not deck:
            note = f" {pdk.status}" if pdk else ""
            return SignoffCheck(**base, status=SignoffStatus.BLOCKED, why=f"No {what} is set up for the PDK {pdk_id!r} in Chipova.{note}")
        if asic is None:
            return SignoffCheck(**base, status=SignoffStatus.BLOCKED, rule_deck=deck, why="Needs a layout: run Build ASIC on this snapshot first.")
        run = next((r for r in ctx.runs if r.flow_id == flow_id and r.source_run == asic.id), None)

        def passed(r: Run) -> tuple[bool, str]:
            s = r.summary or {}
            if what == "DRC":
                total = int(s.get("violations", 0)) + int(s.get("magic_violations", 0))
                return total == 0, s.get("headline", "")
            return bool(s.get("lvs_pass")), s.get("final_result", "")

        out = _from_run(check, run, passed, deck=deck)
        if out.status == SignoffStatus.NOT_RUN:
            out.why = f"Run checks: {what} of the layout of {asic.id}."
        elif out.status == SignoffStatus.FAIL and run is not None:
            out.summary = (run.summary or {}).get("error_text") or out.summary
        out.evidence = [*out.evidence, {"run": asic.id, "flow": "asic_sc", "status": "SUCCEEDED"}]
        return out

    return resolve


def _sta(ctx, check) -> SignoffCheck:  # noqa: ANN001
    asic = _asic_run(ctx)
    base = {"category": check.category, "title": check.title, "rule_deck": "OpenSTA in OpenROAD, after routing (typical corner)"}
    if asic is None:
        return SignoffCheck(**base, status=SignoffStatus.NOT_RUN, why="Build ASIC times the routed design: run it on this snapshot.")
    s = asic.summary or {}
    setup, hold = s.get("setup_slack_ns"), s.get("hold_slack_ns")
    if setup is None or hold is None:
        return SignoffCheck(**base, status=SignoffStatus.FAIL, run_id=asic.id, summary="the run reported no timing")
    ok = setup >= 0 and hold >= 0
    text = f"setup slack {setup:.3f} ns, hold slack {hold:.3f} ns" + (f", Fmax {s['fmax_mhz']} MHz" if s.get("fmax_mhz") else "")
    return SignoffCheck(**base, status=SignoffStatus.PASS if ok else SignoffStatus.FAIL, run_id=asic.id, summary=text,
                        evidence=[{"run": asic.id, "flow": "asic_sc", "status": asic.status.value}],
                        why="With OpenROAD's own parasitic estimate, one corner: not a multi-corner signoff STA with extracted parasitics.")


def _pex(ctx, check) -> SignoffCheck:  # noqa: ANN001
    asic = _asic_run(ctx)
    note = f" Build ASIC {asic.id} did write OpenROAD's SPEF (typical)." if asic else ""
    return SignoffCheck(category=check.category, title=check.title, status=SignoffStatus.NOT_CONFIGURED,
                        why="No signoff-grade parasitic extraction is set up in Chipova." + note)


def _power(ctx, check) -> SignoffCheck:  # noqa: ANN001
    asic = _asic_run(ctx)
    s = asic.summary if asic else {}
    est = ""
    if s.get("power_mw") is not None:
        est = f" OpenROAD's estimate from {asic.id}: peak {s['power_mw']:.4g} mW" + (f", IR drop {s['irdrop_mv']:.3g} mV" if s.get("irdrop_mv") is not None else "") + "."
    return SignoffCheck(category=check.category, title=check.title, status=SignoffStatus.NOT_CONFIGURED,
                        why="No power or IR-drop signoff at the PDK's corners is set up in Chipova." + est)


def _antenna(ctx, check) -> SignoffCheck:  # noqa: ANN001
    return SignoffCheck(category=check.category, title=check.title, status=SignoffStatus.NOT_CONFIGURED,
                        why="Build ASIC repairs antennas while routing (OpenROAD), but no antenna rule check is counted here.")


_registered = False


def register() -> None:
    """Adds the ASIC and signoff flows and their Signoff page rules (once)."""
    global _registered
    if _registered:
        return
    _registered = True
    from chipova.services import signoff  # noqa: PLC0415

    flows.register(Flow(FlowDefinition(
        id="asic_sc", version="1", title="Build ASIC (RTL → GDSII)", category="implement",
        description="SiliconCompiler drives Yosys, OpenROAD and KLayout through synthesis, floorplan, placement, clock tree, routing and GDS export on an open PDK, offline.",
        profiles=[OSIC], timeout=3600,
        params=[
            _p("top", "Top module", "module", "settings.top"),
            _p("pdk", "PDK", "choice", "settings.pdk", [p.id for p in pdks.PDKS.values() if p.flow]),
            _p("density", "Core utilisation % (0 = the PDK's default)", "float", 0.0, [0, 90]),
        ],
    ), _asic))
    flows.register(Flow(FlowDefinition(
        id="signoff_drc", version="1", title="DRC", category="signoff",
        description="KLayout's sky130A_mr deck and Magic check the full layout of a Build ASIC run.",
        profiles=[OSIC], timeout=3600, params=[],
    ), _drc, needs_source="asic_sc"))
    flows.register(Flow(FlowDefinition(
        id="signoff_lvs", version="1", title="LVS", category="signoff",
        description="Magic extracts the netlist of a Build ASIC run's layout and Netgen compares it with the gate-level netlist.",
        profiles=[OSIC], timeout=3600, params=[],
    ), _lvs, needs_source="asic_sc"))
    signoff._resolvers.update({
        "drc": _layout_check("signoff_drc", "DRC"),
        "lvs": _layout_check("signoff_lvs", "LVS"),
        "sta": _sta,
        "pex": _pex,
        "power": _power,
        "antenna": _antenna,
    })
