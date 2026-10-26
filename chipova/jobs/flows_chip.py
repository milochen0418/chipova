"""Full chip: JKU's IHP SG13G2 analog/mixed-signal chip template, built and checked as a whole.

The template's tree is in the IIC-OSIC image (``TEMPLATE``, release 2026.09 with its generated
files removed); a run copies it, puts the snapshot's edited sources over it (container/chip/
chip_overlay.py: RTL, LibreLane setups, schematics, testbenches), deletes every generated file and
runs the template's own make targets: the bondpad and logos, the counter (LibreLane) and the
inverter (KLayout and Magic checks, PEX, views), the chip (LibreLane's chip flow: padframe, power
grid, placement and routing, seal ring, gate-level LVS), Magic DRC of the chip, the simulations.
Each step runs when the steps it needs succeeded (runner.py ``needs``).

What it can't show is said by the Full chip check, which never reads PASS from it: the template's
top-level LVS isn't finished upstream, and the logo-and-fill step and the DRC of the filled chip
need more memory than a run gets (they were killed at 3 GB).
"""

from __future__ import annotations

import json
from pathlib import Path

from chipova.domain.models import Run, SignoffCheck, SignoffStatus
from chipova.jobs import flows, pdks
from chipova.jobs.docker_runner import Limits
from chipova.jobs.flows import JOB, OSIC, OUT, SRC, Context, Flow, FlowDefinition, JobSpec, Step

TEMPLATE = "/opt/chipova/ams-template"
TREE = "/work/tmp/tpl"  # not under /work/out: only what chip_collect.py picks is kept
CHIP_DIR = Path(__file__).parent / "container" / "chip"
# A project made from the chip template has these (templates/ams_chip_ihp).
MARKERS = ("rtl/chip_top.sv", "flow/librelane/config.yaml")
# What the image's own shell set-up gives its tools (the template's Makefiles call sak-*.sh).
ENV = {
    "PATH": "/foss/tools/bin:/foss/tools/sak:/foss/tools/klayout:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONPATH": "/usr/local/lib/python3.12/dist-packages:/usr/lib/python3/dist-packages:/foss/tools/yosys/share/yosys/python3:/foss/tools/klayout/pymod",
    "LD_LIBRARY_PATH": "/foss/tools/klayout:/foss/tools/ngspice/lib:/foss/tools/iverilog/lib",
    "KLAYOUT_HOME": "/headless/.klayout",
    "KLAYOUT_PATH": "/headless/.klayout:/foss/pdks/ihp-sg13g2/libs.tech/klayout:/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech",
    "PDK_ROOT": "/foss/pdks", "PDK": "ihp-sg13g2", "PDKPATH": "/foss/pdks/ihp-sg13g2", "STD_CELL_LIBRARY": "sg13g2_stdcell",
    "SPICE_USERINIT_DIR": "/foss/pdks/ihp-sg13g2/libs.tech/ngspice", "SAK": "/foss/tools/sak",
    "PYTHONPYCACHEPREFIX": "/work/tmp/pycache", "USER": "designer",
    # IHP's xschemrc reads $PWD; a process started without a shell has none (the shells make
    # starts then set the right one).
    "PWD": TREE,
}
COUNTER, INVERTER = f"{TREE}/macros/counter", f"{TREE}/macros/inverter"
# What the check can't have from a run here, whatever the run says.
NOT_HERE = (
    "the top-level LVS (the chip's layout against its schematic) isn't finished in the template upstream",
    "the logo and metal fill, and the DRC of the filled chip, need more memory than a run gets here",
)


def _make(*args: str, cwd: str = TREE) -> list[str]:
    return ["make", "-C", cwd, *args]


def _fullchip(ctx: Context) -> JobSpec:
    missing = [m for m in MARKERS if m not in ctx.files]
    if missing:
        raise flows.FlowError(f"Full chip builds projects made from the IHP chip template; this snapshot has no {', '.join(missing)}")

    def step(sid: str, title: str, argv: list[str], needs: list[str], timeout: int, tool: str = "make") -> Step:
        return Step(sid, title, tool, argv, cwd=TREE, timeout=timeout, needs=needs)

    return JobSpec(
        steps=[
            Step("stage", "The template (from the image)", "generic", ["cp", "-a", f"{TEMPLATE}/.", TREE], cwd="/work/tmp", timeout=300),
            Step("overlay", "This snapshot's sources over it", "generic", ["python3", f"{JOB}/chip_overlay.py", SRC, TREE], cwd=TREE, timeout=120, needs=["stage"]),
            step("clean", "Delete every generated file (make clean-all)", _make("clean-all"), ["overlay"], 300),
            step("bondpad", "Bondpad: build, KLayout and Magic DRC", _make("build-bondpad"), ["clean"], 900),
            step("logos", "Logos: build, KLayout and Magic DRC", _make("build-logos"), ["clean"], 900),
            step("counter", "Counter: LibreLane (DRC, LVS, antenna)", _make("build-top", cwd=COUNTER), ["clean"], 3600),
            step("counter_pex", "Counter: Magic PEX", _make("magic-pex", cwd=COUNTER), ["counter"], 900),
            # Icarus, cocotb (RTL and gate level), and an Xschem run of the PEX netlist.
            step("counter_sim", "Counter: Icarus, cocotb, Xschem", _make("sim-all", cwd=COUNTER), ["counter_pex"], 900),
            step("inverter_klayout", "Inverter: KLayout DRC, LVS, PEX", _make("klayout-verify-all", cwd=INVERTER), ["clean"], 900),
            step("inverter_magic", "Inverter: Magic DRC, Netgen LVS, PEX", _make("magic-verify-all", cwd=INVERTER), ["inverter_klayout"], 900),
            step("inverter", "Inverter: LEF and views", _make("build-top", cwd=INVERTER), ["inverter_magic"], 600),
            step("inverter_sim", "Inverter: CACE corners, Monte Carlo, mismatch", _make("sim-all", cwd=INVERTER), ["inverter"], 1800),
            step("chip", "Chip: LibreLane (padframe, seal ring, P&R, gate-level LVS)", _make("librelane-nodrc"), ["bondpad", "logos", "counter", "inverter"], 3600),
            step("chip_copy", "Chip: reports, GDS, netlists, picture", _make("copy-reports", "copy-gds", "copy-netlist", "copy-render"), ["chip"], 300),
            step("chip_drc", "Chip: Magic DRC (without fill)", _make("magic-drc", "CELL=chip_top"), ["chip_copy"], 1800),
            step("chip_sim", "Chip: cocotb, RTL and gate level", _make("sim-rtl-cocotb", "sim-gl-cocotb"), ["chip_copy"], 900),
            Step("collect", "What the run shows", "generic", ["python3", f"{JOB}/chip_collect.py", TREE, f"{OUT}/chip"], cwd=TREE, timeout=300, needs=["stage"]),
            Step("lyp", "Layer colours", "generic", ["cp", pdks.PDKS["ihp130"].lyp, f"{OUT}/chip/ihp130.lyp"], timeout=60, optional=True, needs=["collect"]),
        ],
        scripts={p.name: p.read_bytes() for p in sorted(CHIP_DIR.glob("*.py"))},
        env=ENV,
        artifacts=[
            ("chip/chip.json", "json"), ("chip/chip_top.png", "image"), ("chip/chip_top.gds.gz", "gds"), ("chip/*.lyp", "lyp"),
            ("chip/librelane_metrics.json", "json"), ("chip/chip_top.magic.drc.rpt", "report"), ("chip/reports/*.rpt", "report"),
        ],
        limits=Limits(cpus=4, memory_mb=4096, pids=4096, timeout=5400, pin_cpus=True),
    )


# ------------------------------------------------------------ the run's numbers

PARTS = (("bondpad", "bondpad"), ("logos", "logos"), ("counter", "counter"), ("counter_pex", "counter PEX"), ("counter_sim", "counter simulations"),
         ("inverter_klayout", "inverter KLayout checks"), ("inverter_magic", "inverter Magic checks"), ("inverter", "inverter views"),
         ("inverter_sim", "inverter CACE"), ("chip", "chip assembly"), ("chip_drc", "chip DRC"), ("chip_sim", "chip simulations"))


def metrics(run: Run, out: Path, summary: dict, steps: dict[str, str]) -> None:
    """``steps``: each step's status. The parts that failed, and what the chip's own reports say."""
    try:
        r = json.loads((out / "chip" / "chip.json").read_text())
    except (OSError, ValueError):
        r = {}
    chip = r.get("chip") or {}
    summary.update({k: v for k, v in chip.items() if k in ("io_count", "pad_cells", "macros", "setup_slack_ns", "hold_slack_ns", "lvs_errors", "antenna_violating_nets")})
    if chip.get("power_w") is not None:
        summary["power_mw"] = round(chip["power_w"] * 1000, 3)
    drc = (r.get("chip_magic_drc") or {}).get("violations")
    if drc is not None:
        summary["chip_drc_violations"] = drc
    failed = [title for sid, title in PARTS if steps.get(sid) == "FAILED"]
    skipped = [title for sid, title in PARTS if steps.get(sid) == "SKIPPED"]
    summary["failed_parts"] = failed
    summary["template"] = r.get("template", "")
    if failed:
        summary["headline"] = "failed: " + ", ".join(failed)
        summary["error_text"] = "Full chip: " + ", ".join(failed) + " failed" + (f" ({', '.join(skipped)} not run)" if skipped else "")
    else:
        summary["headline"] = f"{summary.get('pad_cells', '?')} pad cells, {summary.get('macros', '?')} macros, chip DRC {drc if drc is not None else '?'} (no fill)"
    summary["_labels"] = {
        "io_count": "Pads (IO)", "pad_cells": "Padframe cells", "macros": "Macros", "setup_slack_ns": "Worst setup slack (ns)",
        "hold_slack_ns": "Worst hold slack (ns)", "lvs_errors": "Gate-level LVS errors", "antenna_violating_nets": "Antenna violations",
        "chip_drc_violations": "Magic DRC of the chip (no fill)", "power_mw": "Power (mW, LibreLane)", "template": "Template",
    }


# ------------------------------------------------------------ the Full chip check

def resolve(ctx, check) -> SignoffCheck:  # noqa: ANN001 — signoff._Ctx, Check
    base = {"category": check.category, "title": check.title, "rule_deck": "JKU's IHP SG13G2 chip template, its own make targets"}
    if not all(m in ctx.files for m in MARKERS):
        return SignoffCheck(**base, status=SignoffStatus.NOT_CONFIGURED,
                            why="Full chip runs on projects made from the IHP analog/mixed-signal chip template (padframe, seal ring, macros).")
    run = ctx.latest("fullchip_ihp")
    if run is None:
        return SignoffCheck(**base, status=SignoffStatus.NOT_RUN, why="Run checks: Full chip builds and checks the whole chip.")
    evidence = [{"run": run.id, "flow": run.flow_id, "status": run.status.value}]
    if not run.status.finished:
        return SignoffCheck(**base, status=SignoffStatus.RUNNING, run_id=run.id, evidence=evidence, summary="running")
    s = run.summary or {}
    if s.get("failed_parts") or run.status.value != "SUCCEEDED":
        return SignoffCheck(**base, status=SignoffStatus.FAIL, run_id=run.id, evidence=evidence, summary=s.get("error_text") or run.error or run.status.value)
    # Everything that runs here passed; what can't run here keeps it from PASS.
    return SignoffCheck(**base, status=SignoffStatus.BLOCKED, run_id=run.id, evidence=evidence, summary=s.get("headline", ""),
                        why="What ran here passed, but " + "; ".join(NOT_HERE) + ".")


_registered = False


def register() -> None:
    global _registered
    if _registered:
        return
    _registered = True
    from chipova.services import signoff  # noqa: PLC0415

    flows.register(Flow(FlowDefinition(
        id="fullchip_ihp", version="1", title="Full chip (IHP)", category="signoff",
        description="JKU's IHP SG13G2 chip template with this snapshot's sources: bondpad, logos, the counter and inverter macros with their checks, the chip with LibreLane (padframe, seal ring, P&R, gate-level LVS), Magic DRC of the chip, cocotb.",
        profiles=[OSIC], timeout=5400, params=[],
    ), _fullchip))
    signoff._resolvers["fullchip"] = resolve
