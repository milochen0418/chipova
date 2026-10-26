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
        raise FlowError(f"no {what} is set up for {src.params.get('pdk')!r} in Chipova (SKY130, IHP SG13G2 and GF180 have one)")
    top = str(src.params.get("top", ""))
    gds = ctx.source_files.get(f"asic/final/{top}.full.gds")
    if gds is None or not gds.is_file():
        raise FlowError("that Build ASIC run kept no full GDS")
    return top, pdk, gds


def _drc(ctx: Context) -> JobSpec:
    top, pdk, gds = _layout_of(ctx, "DRC")
    layout = f"/work/in/{top}.full.gds"
    kl, mg, dens = f"{OUT}/drc/klayout", f"{OUT}/drc/magic", f"{OUT}/drc/density"
    if pdk.id == "ihp130":
        # IHP's main rule set is what LibreLane signs off with; it holds the minimum rules IHP's
        # tape-out precheck checks. Density holds for a whole chip after fill (inside the seal
        # ring), so a block's numbers are shown, not counted.
        steps = [
            Step("klayout", "KLayout DRC (IHP main rules)", "klayout_drc", ["bash", f"{JOB}/drc_ihp_klayout.sh", layout, top, kl, "4", "main"],
                 timeout=3600, continue_on_fail=True),
            Step("magic", "Magic DRC (ihp-sg13g2)", "magic_drc", ["bash", f"{JOB}/drc_ihp_magic.sh", layout, top, mg], timeout=3600, continue_on_fail=True),
            Step("density", "Metal density (for the chip, after fill)", "klayout_drc", ["bash", f"{JOB}/density_ihp.sh", layout, top, dens, "4"],
                 timeout=1800, optional=True),
        ]
    elif pdk.id == "gf180":
        # Variant C: the 9 kÅ top metal of the gf180_demo target Build ASIC uses. Magic's GF180
        # tech knows the 11 kÅ one only, so it isn't run here.
        steps = [
            Step("klayout", "KLayout DRC (gf180mcu, variant C)", "klayout_drc", ["bash", f"{JOB}/drc_gf180_klayout.sh", layout, top, kl, "4"],
                 env={"VARIANT": "gf180mcuC"}, timeout=3600, continue_on_fail=True),
            Step("density", "Metal density (for the chip, after fill)", "klayout_drc", ["bash", f"{JOB}/density_gf180.sh", layout, top, dens, "4"],
                 env={"VARIANT": "gf180mcuC"}, timeout=1800, optional=True),
        ]
    else:
        steps = [
            Step("klayout", "KLayout DRC (sky130A_mr)", "klayout_drc", ["bash", f"{JOB}/drc_klayout.sh", layout, top, kl, "4"],
                 env={"STDCELL_GDS": "none"}, timeout=3600, continue_on_fail=True),
            Step("magic", "Magic DRC", "magic_drc", ["bash", f"{JOB}/drc_magic.sh", layout, top, mg],
                 env={"STDCELL_GDS": "none"}, timeout=3600),
        ]
    return JobSpec(
        steps=steps,
        scripts=_scripts(),
        inputs={f"{top}.full.gds": gds},
        artifacts=[
            ("drc/klayout/drc.lyrdb", "report"), ("drc/klayout/drc.json", "json"), ("drc/klayout/markers.json", "json"),
            ("drc/magic/magic_drc.rpt", "report"), ("drc/magic/magic_drc.json", "json"),
            ("drc/density/density.json", "json"), ("drc/density/*.lyrdb", "report"),
        ],
        limits=Limits(cpus=4, memory_mb=4096, timeout=3600),
    )


def _lvs(ctx: Context) -> JobSpec:
    top, pdk, gds = _layout_of(ctx, "LVS")
    netlist = ctx.source_files.get(f"asic/final/{top}.vg")
    if netlist is None or not netlist.is_file():
        raise FlowError("that Build ASIC run kept no gate-level netlist")
    # IHP: its own KLayout deck (each cell once, then the top); GF180: Magic + Netgen, as
    # LibreLane (KLayout's GF180 deck flags the supply nets of matching circuits).
    script, title, tool = {
        "ihp130": ("lvs_ihp_klayout.sh", "KLayout LVS (IHP sg13g2.lvs)", "klayout_lvs"),
        "gf180": ("lvs_gf180_magic.sh", "Magic extraction + Netgen LVS (gf180mcuD)", "netgen"),
    }.get(pdk.id, ("lvs.sh", "Magic extraction + Netgen LVS", "netgen"))
    return JobSpec(
        steps=[Step("lvs", title, tool, ["bash", f"{JOB}/{script}", f"/work/in/{top}.full.gds", f"/work/in/{top}.vg", top, f"{OUT}/lvs"], timeout=3600)],
        scripts=_scripts(),
        inputs={f"{top}.full.gds": gds, f"{top}.vg": netlist},
        artifacts=[
            ("lvs/lvs.rpt", "report"), ("lvs/lvs.log", "log"), ("lvs/lvs_result.json", "json"), (f"lvs/{top}.spice", "spice"),
            (f"lvs/{top}.schematic.spice", "spice"), (f"lvs/{top}.cdl", "netlist"), ("lvs/run/*.lvsdb", "report"), ("lvs/run/*.cir", "spice"),
        ],
        limits=Limits(cpus=2, memory_mb=4096, timeout=3600),
    )


# The checks of the routed design OpenROAD/OpenSTA run (container/asic: pex.sh, sta.sh,
# power_ir.sh, antenna.sh, with the corners of pdk_env.sh), in this order: STA and power use the
# parasitics PEX extracted.
OPENROAD_PDKS = ("skywater130", "ihp130", "gf180")
OPENROAD_CHECKS = (
    ("pex", "Parasitic extraction (OpenRCX)"),
    ("sta", "Static timing, every corner (OpenSTA)"),
    ("power_ir", "Power and IR drop (PDNSim)"),
    ("antenna", "Antenna rules (OpenROAD)"),
)
SIGNOFF_OUT = f"{OUT}/signoff"


def _signoff_openroad(ctx: Context) -> JobSpec:
    src = ctx.source_run
    if src is None:
        raise FlowError("the timing, parasitics, antenna and power checks look at a succeeded Build ASIC run: give its id")
    pdk_id = str(src.params.get("pdk", ""))
    if pdk_id not in OPENROAD_PDKS:
        raise FlowError(f"no corners are set up for {pdk_id!r} in Chipova's timing and power checks (SKY130, IHP SG13G2 and GF180 have them)")
    top = str(src.params.get("top", ""))
    inputs = {}
    for ext in ("def.gz", "vg", "sdc", "typical.spef"):
        path = ctx.source_files.get(f"asic/final/{top}.{ext}")
        if path is not None and path.is_file():
            inputs[f"{top}.{ext}"] = path
        elif ext != "typical.spef":
            raise FlowError(f"that Build ASIC run kept no {top}.{ext}")
    parasitics = {"SPEF_DIR": f"{SIGNOFF_OUT}/pex"}
    return JobSpec(
        steps=[
            Step(key, title, "openroad", ["bash", f"{JOB}/{key}.sh", "/work/in", f"{SIGNOFF_OUT}/{key}", pdk_id, top],
                 env={**parasitics, "STA_FAIL_ON_DRV": "1"} if key == "sta" else (parasitics if key == "power_ir" else {}),
                 timeout=1800, continue_on_fail=True)
            for key, title in OPENROAD_CHECKS
        ],
        scripts=_scripts(),
        inputs=inputs,
        artifacts=[
            ("signoff/*/*.json", "json"), ("signoff/pex/*.spef", "spef"), ("signoff/sta/*.rpt", "report"),
            ("signoff/power_ir/*.rpt", "report"), ("signoff/power_ir/*.csv", "data"), ("signoff/antenna/*.rpt", "report"),
        ],
        limits=Limits(cpus=2, memory_mb=2048, timeout=3600),
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


_NUM_PAIR = re.compile(r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?),(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_TRANS = re.compile(r"^\s*([rm])(\d+)\s+\*([\d.eE+-]+)\s+(-?[\d.eE+-]+),(-?[\d.eE+-]+)\s*$")


def _apply(trans: str, x: float, y: float) -> tuple[float, float]:
    """A KLayout DCplxTrans ("r90 *1 dx,dy", "m45 *1 dx,dy") applied to a point."""
    m = _TRANS.match(trans or "")
    if not m:
        return x, y
    kind, angle, mag, dx, dy = m.group(1), int(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
    if kind == "m":  # mirrored at the line through 0,0 at <angle> degrees
        x, y = {0: (x, -y), 45: (y, x), 90: (-x, y), 135: (-y, -x)}[angle]
    else:
        x, y = {0: (x, y), 90: (-y, x), 180: (-x, -y), 270: (y, -x)}[angle]
    return x * mag + dx, y * mag + dy


def drc_markers(lyrdb: Path, limit: int = 500) -> list[dict]:
    """Where each violation of a KLayout report is: its rule and bounding box (µm, top cell).
    A deck run in deep (hierarchical) mode reports a violation inside a sub-cell (a standard
    cell, a router's via cell) once, in that cell's own coordinates: it is moved to the top cell
    through the example placement the report keeps for the cell."""
    try:
        root = ET.parse(lyrdb).getroot()
    except (OSError, ET.ParseError):
        return []
    top = (root.findtext("top-cell") or "").strip()
    place = {}
    cells = root.find("cells")
    for c in cells.findall("cell") if cells is not None else []:
        refs = c.find("references")
        ref = refs.find("ref") if refs is not None else None
        if ref is not None:
            place[(c.findtext("name") or "").strip()] = ((ref.findtext("parent") or "").strip(), (ref.findtext("trans") or "").strip())
    out = []
    items = root.find("items")
    for item in items.findall("item") if items is not None else []:
        rule = (item.findtext("category") or "").strip().strip("'").replace("'.'", ".")
        cell = (item.findtext("cell") or "").strip()
        pts = [(float(x), float(y)) for v in item.iter("value") for x, y in _NUM_PAIR.findall(v.text or "")]
        if not pts:
            continue
        c, seen = cell, set()
        while c and c != top and c in place and c not in seen:
            seen.add(c)
            parent, trans = place[c]
            pts = [_apply(trans, x, y) for x, y in pts]
            c = parent
        marker = {"rule": rule, "box": [round(v, 4) for v in (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))]}
        if cell and cell != top:
            marker["cell"] = cell
        out.append(marker)
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
    dens = _read(out / "drc" / "density" / "density.json")
    if dens:  # shown, not counted: density holds for the whole chip after fill
        summary["density_rules_missed"] = len(dens.get("violated") or {})
        summary["density"] = {"violated": dens.get("violated") or {}, "layers": dens.get("layers") or {}}
    if kl or mg:
        total = int(summary.get("violations", 0)) + int(summary.get("magic_violations", 0))
        broken = ", ".join(f"{r} ×{n}" for r, n in list((summary.get("rules") or {}).items())[:8])
        summary["headline"] = "clean" if total == 0 else f"{summary.get('violations', 0)} KLayout, {summary.get('magic_violations', 0)} Magic violations"
        if total:
            summary["error_text"] = f"DRC found violations: {broken or 'see the reports'}" + (f"; Magic: {summary['magic_violations']}" if summary.get("magic_violations") else "")
        summary["_labels"] = {"violations": "KLayout violations", "magic_violations": "Magic violations", "rules_checked": "Rules checked",
                              "density_rules_missed": "Density rules missed (for the chip after fill; not counted)"}


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
    summary["_labels"] = {"final_result": "Verdict", "nets": "Nets (layout / netlist)", "devices": "Devices (layout / netlist)"}


def _openroad_result(key: str, j: dict) -> dict:
    """The part of one check's JSON the Signoff page and the run's numbers use."""
    if key == "antenna":
        return {"pass": j.get("pass"), "net_violations": j.get("net_violations"), "pin_violations": j.get("pin_violations"),
                "nets": j.get("routed_signal_nets"), "violating_nets": (j.get("violating_nets") or [])[:20]}
    if key == "pex":
        return {"pass": j.get("pass"), "corners": {c: {"nets": v.get("nets"), "total_cap_pf": v.get("total_cap_pf"), "total_res_ohm": v.get("total_res_ohm"),
                                                       "rules": v.get("openrcx_rules"), "problems": v.get("problems")}
                                                   for c, v in (j.get("corners") or {}).items()}}
    if key == "sta":
        return {"pass": j.get("pass"), "worst": j.get("worst") or {},
                "corners": {c: {"setup_ws_ns": (v.get("setup") or {}).get("worst_slack_ns"), "setup_tns_ns": (v.get("setup") or {}).get("tns_ns"),
                                "hold_ws_ns": (v.get("hold") or {}).get("worst_slack_ns"), "hold_tns_ns": (v.get("hold") or {}).get("tns_ns"),
                                "drv_violations": v.get("drv_violations"), "problems": v.get("problems")}
                            for c, v in (j.get("corners") or {}).items()}}
    return {"pass": j.get("pass"), "worst": j.get("worst") or {},
            "corners": {c: {"power_mw": (v.get("power_mw") or {}).get("total"), "ir_drop_total_mv": v.get("ir_drop_total_mv"),
                            "ir_drop_total_pct_of_vdd": v.get("ir_drop_total_pct_of_vdd"), "activity": v.get("activity"),
                            "problems": v.get("problems"), "warnings": v.get("warnings")}
                        for c, v in (j.get("corners") or {}).items()}}


def _openroad_metrics(run: Run, out: Path, summary: dict) -> None:
    checks = {key: _openroad_result(key, j) for key, _ in OPENROAD_CHECKS if (j := _read(out / "signoff" / key / f"{key}.json"))}
    if not checks:
        return
    summary["checks"] = checks
    for key, c in checks.items():  # each step's own verdict, on its node of the flow
        summary.setdefault("_steps", {})[key] = {"pass": c.get("pass")}
    sta, pw, an, px = checks.get("sta", {}), checks.get("power_ir", {}), checks.get("antenna", {}), checks.get("pex", {})
    worst = sta.get("worst") or {}
    flat = {
        "setup_slack_ns": worst.get("setup_slack_ns"), "setup_corner": worst.get("setup_corner"),
        "hold_slack_ns": worst.get("hold_slack_ns"), "hold_corner": worst.get("hold_corner"),
        "ir_drop_pct": (pw.get("worst") or {}).get("ir_drop_total_pct_of_vdd"), "ir_corner": (pw.get("worst") or {}).get("ir_corner"),
        "power_mw": (pw.get("worst") or {}).get("power_mw"), "antenna_violations": an.get("net_violations"),
        "pex_corners": len(px.get("corners") or {}),
    }
    summary.update({k: v for k, v in flat.items() if v is not None})
    names = {"pex": "PEX", "sta": "STA", "power_ir": "power/IR", "antenna": "antenna"}
    summary["headline"] = " · ".join(f"{names[k]} {'✓' if c.get('pass') else '✗'}" for k, c in checks.items())
    failed = [names[k] for k, c in checks.items() if not c.get("pass")]
    if failed:
        summary["error_text"] = "Failed: " + ", ".join(failed)
    summary["_labels"] = {
        "setup_slack_ns": "Worst setup slack (ns)", "setup_corner": "… in the corner", "hold_slack_ns": "Worst hold slack (ns)", "hold_corner": "… in the corner",
        "ir_drop_pct": "Worst IR drop (% of VDD)", "ir_corner": "… in the corner", "power_mw": "Most power (mW, vectorless)",
        "antenna_violations": "Antenna violations", "pex_corners": "RC corners extracted",
    }


def metrics(run: Run, out: Path, summary: dict) -> None:
    fn = {"asic_sc": _asic_metrics, "signoff_drc": _drc_metrics, "signoff_lvs": _lvs_metrics, "signoff_openroad": _openroad_metrics}.get(run.flow_id)
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
        run = ctx.latest(flow_id, source_run=asic.id)

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


def _openroad_check(key: str, what: str):  # noqa: ANN202
    """A Signoff check from one part of a signoff_openroad run of the snapshot's layout: PASS or
    FAIL as that check itself said, whatever the other three said."""
    def resolve(ctx, check) -> SignoffCheck:  # noqa: ANN001
        base = {"category": check.category, "title": check.title}
        asic = _asic_run(ctx)
        if asic is None:
            return SignoffCheck(**base, status=SignoffStatus.BLOCKED, why="Needs a layout: run Build ASIC on this snapshot first.")
        pdk_id = str(asic.params.get("pdk", ""))
        if pdk_id not in OPENROAD_PDKS:
            return SignoffCheck(**base, status=SignoffStatus.BLOCKED, why=f"No corners are set up for {pdk_id!r} in Chipova's {what}.")
        run = ctx.latest("signoff_openroad", source_run=asic.id)
        evidence = [{"run": asic.id, "flow": "asic_sc", "status": "SUCCEEDED"}]
        if run is None:
            return SignoffCheck(**base, status=SignoffStatus.NOT_RUN, evidence=evidence, why=f"Run checks: {what} of the layout of {asic.id}.")
        evidence.insert(0, {"run": run.id, "flow": run.flow_id, "status": run.status.value})
        if not run.status.finished:
            return SignoffCheck(**base, status=SignoffStatus.RUNNING, run_id=run.id, evidence=evidence, summary="running" if run.status == RunStatus.RUNNING else "waiting")
        result = ((run.summary or {}).get("checks") or {}).get(key)
        if not result:
            return SignoffCheck(**base, status=SignoffStatus.FAIL, run_id=run.id, evidence=evidence, summary=run.error or "the check left no result")
        return SignoffCheck(**base, status=SignoffStatus.PASS if result.get("pass") else SignoffStatus.FAIL, run_id=run.id, evidence=evidence,
                            rule_deck=_openroad_deck(key, result), summary=_openroad_summary(key, result))

    return resolve


def _openroad_deck(key: str, r: dict) -> str:
    if key == "pex":
        rules = {Path(v.get("rules") or "").name for v in (r.get("corners") or {}).values()}
        return "OpenRCX " + ", ".join(sorted(rules))
    return {"sta": "OpenSTA, every liberty corner with its extracted parasitics", "power_ir": "OpenROAD report_power + PDNSim (static IR)",
            "antenna": "OpenROAD check_antennas, the PDK's LEF antenna rules"}.get(key, "")


def _openroad_summary(key: str, r: dict) -> str:
    corners = r.get("corners") or {}
    if key == "antenna":
        return f"{r.get('net_violations')} nets and {r.get('pin_violations')} pins over the limits, of {r.get('nets')} nets"
    if key == "pex":
        return "; ".join(f"{c}: {v.get('nets')} nets, {1000 * (v.get('total_cap_pf') or 0):.1f} fF" for c, v in corners.items())
    if key == "sta":
        w = r.get("worst") or {}
        text = f"worst setup slack {w.get('setup_slack_ns')} ns ({w.get('setup_corner')}), worst hold slack {w.get('hold_slack_ns')} ns ({w.get('hold_corner')}), {len(corners)} corners"
        problems = [p for v in corners.values() for p in (v.get("problems") or [])]
        return text + ("; " + "; ".join(problems[:3]) if problems else "")
    w = r.get("worst") or {}
    pct = w.get("ir_drop_total_pct_of_vdd")
    return (f"worst IR drop {w.get('ir_drop_total_mv')} mV = {pct:.3g} % of VDD ({w.get('ir_corner')}); "
            f"most power {w.get('power_mw'):.4g} mW ({w.get('power_corner')}, vectorless activity)") if pct is not None and w.get("power_mw") is not None else "no result"


_registered = False


def register() -> None:
    """Adds the ASIC and signoff flows and their Signoff page rules (once)."""
    global _registered
    if _registered:
        return
    _registered = True
    from chipova.jobs import flows_chip  # noqa: PLC0415
    from chipova.services import signoff  # noqa: PLC0415

    flows_chip.register()
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
        description="The PDK's own open DRC decks check the full layout of a Build ASIC run: KLayout (SKY130 sky130A_mr, IHP's main rules, GF180's open_pdks deck) and Magic (SKY130, IHP).",
        profiles=[OSIC], timeout=3600, params=[],
    ), _drc, needs_source="asic_sc"))
    flows.register(Flow(FlowDefinition(
        id="signoff_lvs", version="1", title="LVS", category="signoff",
        description="The layout of a Build ASIC run against its gate-level netlist: Magic + Netgen (SKY130, GF180), IHP's own KLayout deck (IHP SG13G2).",
        profiles=[OSIC], timeout=3600, params=[],
    ), _lvs, needs_source="asic_sc"))
    flows.register(Flow(FlowDefinition(
        id="signoff_openroad", version="1", title="Timing, parasitics, antenna, power/IR", category="signoff",
        description="On a Build ASIC run's routed design: OpenRCX parasitics per RC corner, OpenSTA at every corner with them, power and static IR drop (PDNSim), antenna rules.",
        profiles=[OSIC], timeout=3600, params=[],
    ), _signoff_openroad, needs_source="asic_sc"))
    signoff._resolvers.update({
        "drc": _layout_check("signoff_drc", "DRC"),
        "lvs": _layout_check("signoff_lvs", "LVS"),
        "sta": _openroad_check("sta", "timing"),
        "pex": _openroad_check("pex", "parasitic extraction"),
        "power": _openroad_check("power_ir", "power and IR drop"),
        "antenna": _openroad_check("antenna", "antenna check"),
    })
