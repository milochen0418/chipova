"""The flows a run can be: the only things Chipova ever runs (blueprint 7.2: an allow-list).

A flow turns a snapshot, the project's settings (its ``chipova.toml`` in that snapshot) and a few
checked parameters into fixed steps: argv lists for the tools, no shell and no free text. Names
that end up in a command (a module, a file) are checked first: modules are Verilog identifiers,
files must be files of the snapshot. Unknown parameters are refused, so neither a person nor an
AI can slip a command in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from chipova.domain.models import FlowDefinition, FlowParam, ProjectSettings, Revision, Run
from chipova.jobs.docker_runner import Limits

SRC = "/work/src"
OUT = "/work/out"
JOB = "/work/job"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")
RTL_EXT = (".v", ".sv")
BASE = "eda-base-1"
OSIC = "iic-osic-2026.10"


class FlowError(ValueError):
    """The run can't be made as asked; the message says why, for a person or an AI to read."""


@dataclass
class Step:
    id: str
    title: str
    tool: str  # which parser reads its log (chipova.jobs.parsers)
    argv: list[str]
    cwd: str = OUT
    timeout: int = 600
    env: dict[str, str] = field(default_factory=dict)
    # Run the steps after it even when it fails (each step's problems are still reported).
    continue_on_fail: bool = False
    # Its failure doesn't fail the run (pictures, extras).
    optional: bool = False
    # Shown as a step of the run but not run by itself: a node of a tool's own flow (Build ASIC's
    # SiliconCompiler nodes), moved along by the tool's markers and its report.
    virtual: bool = False

    def job(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "argv": self.argv, "cwd": self.cwd, "env": self.env,
            "timeout": self.timeout, "allow_fail": self.continue_on_fail or self.optional,
        }


@dataclass
class Context:
    revision: Revision
    settings: ProjectSettings
    files: list[str]  # the snapshot's paths
    params: dict[str, Any]
    profile_id: str
    source_run: Run | None = None
    source_files: dict[str, Path] = field(default_factory=dict)  # the source run's artifacts by name


@dataclass
class JobSpec:
    steps: list[Step]
    scripts: dict[str, bytes] = field(default_factory=dict)  # under /work/job
    inputs: dict[str, Path] = field(default_factory=dict)  # under /work/in
    artifacts: list[tuple[str, str]] = field(default_factory=list)  # (glob under /work/out, kind)
    limits: Limits = field(default_factory=Limits)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Flow:
    definition: FlowDefinition
    build: Callable[[Context], JobSpec]
    needs_source: str = ""  # a flow this one checks the outputs of ("" = none)

    @property
    def id(self) -> str:
        return self.definition.id


# ------------------------------------------------------------ parameters


def check_params(flow: Flow, given: dict[str, Any], settings: ProjectSettings, files: list[str]) -> dict[str, Any]:
    """The flow's parameters: the given ones checked, the rest from the settings or defaults."""
    given = dict(given or {})
    known = {p.name: p for p in flow.definition.params}
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise FlowError(f"{flow.id} has no parameter {', '.join(unknown)} (it takes: {', '.join(known) or 'none'})")
    out: dict[str, Any] = {}
    for name, p in known.items():
        value = given.get(name)
        if value in (None, ""):
            value = _default(p, settings)
        out[name] = _check(flow.id, p, value, files)
    return out


def _default(p: FlowParam, settings: ProjectSettings) -> Any:
    if isinstance(p.default, str) and p.default.startswith("settings."):
        return getattr(settings, p.default.split(".", 1)[1], None)
    return p.default


def _check(flow_id: str, p: FlowParam, value: Any, files: list[str]) -> Any:
    where = f"{flow_id}: {p.name}"
    if p.kind == "module":
        if not isinstance(value, str) or not IDENT.match(value):
            raise FlowError(f"{where} must be a Verilog module name, not {value!r}")
        return value
    if p.kind == "bool":
        if isinstance(value, str):
            value = value.lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if p.kind == "float":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise FlowError(f"{where} must be a number") from None
        lo, hi = (p.choices[0], p.choices[1]) if len(p.choices) == 2 else ("-inf", "inf")
        if not float(lo) <= v <= float(hi):
            raise FlowError(f"{where} must be between {lo} and {hi}")
        return v
    if p.kind == "choice":
        if value not in p.choices:
            raise FlowError(f"{where} must be one of {', '.join(p.choices)}")
        return value
    if p.kind == "file":
        exts = tuple(p.choices)
        if not isinstance(value, str) or value not in files or (exts and not value.endswith(exts)):
            raise FlowError(f"{where} must be a {'/'.join(exts) or ''} file of the snapshot, not {value!r}")
        return value
    if p.kind == "word":
        if not isinstance(value, str) or not re.match(r"^[a-z0-9]{1,16}$", value):
            raise FlowError(f"{where} must be a short lowercase word")
        return value
    raise FlowError(f"{where}: unknown kind {p.kind}")


# ------------------------------------------------------------ which files


def rtl_files(ctx: Context) -> list[str]:
    """The RTL sources: the settings' list, else every .v/.sv outside tb/ that isn't a
    testbench."""
    listed = [f for f in ctx.settings.rtl if f in ctx.files]
    missing = [f for f in ctx.settings.rtl if f not in ctx.files]
    if missing:
        raise FlowError(f"chipova.toml lists RTL files the snapshot doesn't have: {', '.join(missing)}")
    if listed:
        return listed
    sim = set(ctx.settings.sim)
    return [f for f in ctx.files if f.endswith(RTL_EXT) and not f.startswith("tb/") and f not in sim and not Path(f).name.startswith("tb_")]


def sim_files(ctx: Context) -> list[str]:
    listed = [f for f in ctx.settings.sim if f in ctx.files]
    missing = [f for f in ctx.settings.sim if f not in ctx.files]
    if missing:
        raise FlowError(f"chipova.toml lists testbench files the snapshot doesn't have: {', '.join(missing)}")
    if listed:
        return listed
    return [f for f in ctx.files if f.endswith(RTL_EXT) and (f.startswith("tb/") or Path(f).name.startswith("tb_"))]


def _src(paths_: list[str]) -> list[str]:
    return [f"{SRC}/{p}" for p in paths_]


def _need(files: list[str], what: str) -> list[str]:
    if not files:
        raise FlowError(f"the snapshot has no {what}")
    return files


# ------------------------------------------------------------ lint


def _lint(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    if ctx.params["include_testbench"]:
        files = files + sim_files(ctx)
        top = ctx.settings.testbench or top
    warn = ["-Wall"] if ctx.params["strict"] else []
    return JobSpec(
        steps=[
            Step("verilator", "Verilator lint", "verilator",
                 ["verilator", "--lint-only", *warn, "-Wno-fatal", "--timing", "--top-module", top, *_src(files)],
                 cwd=f"{OUT}/lint", timeout=300, continue_on_fail=True),
            Step("iverilog", "Icarus Verilog elaboration", "iverilog",
                 ["iverilog", "-g2012", "-Wall", "-t", "null", "-s", top, *_src(files)],
                 cwd=f"{OUT}/lint", timeout=300),
        ],
        limits=Limits(cpus=2, memory_mb=2048, timeout=600),
    )


# ------------------------------------------------------------ simulation


def _sim(ctx: Context) -> JobSpec:
    tb = ctx.params["testbench"]
    if not tb:
        raise FlowError("set the testbench's top module in Settings (chipova.toml [sim] testbench)")
    files = _need(rtl_files(ctx), "RTL files") + _need(sim_files(ctx), "testbench files (tb/*.v)")
    if ctx.params["simulator"] == "verilator":
        steps = [
            Step("build", "Verilator build", "verilator",
                 ["verilator", "--binary", "--timing", "--trace", "-Wno-fatal", "-Wno-lint", "-Wno-style",
                  "-j", "2", "--top-module", tb, "-Mdir", "obj", *_src(files)],
                 cwd=f"{OUT}/sim", timeout=900),
            Step("run", "Simulation", "vvp", [f"{OUT}/sim/obj/V{tb}"], cwd=f"{OUT}/sim", timeout=600),
        ]
    else:
        steps = [
            Step("compile", "Icarus Verilog compile", "iverilog",
                 ["iverilog", "-g2012", "-Wall", "-o", "sim.vvp", "-s", tb, *_src(files)],
                 cwd=f"{OUT}/sim", timeout=300),
            Step("run", "Simulation", "vvp", ["vvp", "-n", "sim.vvp"], cwd=f"{OUT}/sim", timeout=600),
        ]
    return JobSpec(
        steps=steps,
        artifacts=[("sim/*.vcd", "vcd"), ("sim/*.fst", "fst")],
        limits=Limits(cpus=2, memory_mb=3072, timeout=1200),
    )


# ------------------------------------------------------------ synthesis


def _synth(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    reads = "\n".join(f"read_verilog -sv {f}" for f in _src(files))
    flatten = " -flatten" if ctx.params["flatten"] else ""
    synth = (
        f"{reads}\n"
        f"hierarchy -check -top {top}\n"
        f"synth -top {top}{flatten}\n"
        "opt_clean -purge\n"
        f"tee -q -o {OUT}/synth/stat.json stat -json\n"
        "stat\n"
        f"write_verilog -noattr {OUT}/synth/netlist.v\n"
        f"write_json {OUT}/synth/netlist.json\n"
    )
    view = (
        f"{reads}\n"
        f"hierarchy -top {top}\n"
        "proc\nopt -purge\n"
        f"show -format dot -prefix {OUT}/synth/rtl -notitle -stretch {top}\n"
    )
    return JobSpec(
        steps=[
            Step("yosys", "Yosys synthesis", "yosys", ["yosys", "-s", f"{JOB}/synth.ys"], cwd=f"{OUT}/synth", timeout=1200),
            Step("rtl_view", "RTL schematic", "yosys", ["yosys", "-q", "-s", f"{JOB}/rtl_view.ys"], cwd=f"{OUT}/synth", timeout=300, optional=True),
            Step("svg", "Schematic picture", "graphviz", ["dot", "-Tsvg", "rtl.dot", "-o", "rtl.svg"], cwd=f"{OUT}/synth", timeout=120, optional=True),
        ],
        scripts={"synth.ys": synth.encode(), "rtl_view.ys": view.encode()},
        artifacts=[("synth/netlist.v", "netlist"), ("synth/netlist.json", "json"), ("synth/stat.json", "report"), ("synth/rtl.svg", "image")],
        limits=Limits(cpus=2, memory_mb=4096, timeout=1800),
    )


# ------------------------------------------------------------ FPGA (iCE40)

ICE40_DEVICES = ["lp384", "lp1k", "lp4k", "lp8k", "hx1k", "hx4k", "hx8k", "up3k", "up5k", "u1k", "u2k", "u4k"]


def _fpga(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    pcf = ctx.params["pcf"]
    reads = "\n".join(f"read_verilog -sv {f}" for f in _src(files))
    script = f"{reads}\nsynth_ice40 -top {top} -json {OUT}/fpga/{top}.json\n"
    return JobSpec(
        steps=[
            Step("synth", "Yosys synth_ice40", "yosys", ["yosys", "-s", f"{JOB}/fpga.ys"], cwd=f"{OUT}/fpga", timeout=1200),
            Step("pnr", "nextpnr place & route", "nextpnr",
                 ["nextpnr-ice40", f"--{ctx.params['device']}", "--package", ctx.params["package"], "--json", f"{top}.json",
                  "--pcf", f"{SRC}/{pcf}", "--asc", f"{top}.asc", "--report", "report.json",
                  "--freq", f"{ctx.params['freq_mhz']:.3f}", "--seed", "1"],
                 cwd=f"{OUT}/fpga", timeout=1800),
            Step("pack", "icepack bitstream", "icepack", ["icepack", f"{top}.asc", f"{top}.bin"], cwd=f"{OUT}/fpga", timeout=300),
        ],
        scripts={"fpga.ys": script.encode()},
        artifacts=[("fpga/*.bin", "bitstream"), ("fpga/*.asc", "fpga_asc"), ("fpga/report.json", "report"), (f"fpga/{top}.json", "json")],
        limits=Limits(cpus=2, memory_mb=4096, timeout=3600),
    )


# ------------------------------------------------------------ SPICE (ngspice)


def _ngspice(ctx: Context) -> JobSpec:
    deck = ctx.params["deck"]
    return JobSpec(
        steps=[Step("ngspice", "ngspice simulation", "ngspice", ["ngspice", "-b", f"{SRC}/{deck}"], cwd=f"{OUT}/ams", timeout=900)],
        artifacts=[("ams/*.csv", "table"), ("ams/*.raw", "spice_raw")],
        limits=Limits(cpus=1, memory_mb=2048, timeout=1200),
    )


# ------------------------------------------------------------ the registry


def _p(name: str, title: str, kind: str, default: Any = None, choices: list | None = None, help: str = "") -> FlowParam:  # noqa: A002
    return FlowParam(name=name, title=title, kind=kind, default=default, choices=[str(c) for c in (choices or [])], help=help)


FLOWS: dict[str, Flow] = {}


def register(flow: Flow) -> Flow:
    FLOWS[flow.id] = flow
    return flow


register(Flow(FlowDefinition(
    id="rtl_lint", version="1", title="Lint", category="verify",
    description="Checks the RTL with Verilator (lint, all warnings) and Icarus Verilog (elaboration).",
    profiles=[BASE, OSIC], timeout=600,
    params=[
        _p("top", "Top module", "module", "settings.top"),
        _p("include_testbench", "Also the testbench", "bool", False),
        _p("strict", "All warnings (-Wall)", "bool", True),
    ],
), _lint))

register(Flow(FlowDefinition(
    id="rtl_sim", version="1", title="Simulate", category="verify",
    description="Runs the testbench (Icarus Verilog, or Verilator) and keeps its waveform. A line starting with FAIL or ERROR fails the run.",
    profiles=[BASE, OSIC], timeout=1200,
    params=[
        _p("testbench", "Testbench top", "module", "settings.testbench"),
        _p("simulator", "Simulator", "choice", "icarus", ["icarus", "verilator"]),
    ],
), _sim))

register(Flow(FlowDefinition(
    id="synth_yosys", version="1", title="Synthesize", category="implement",
    description="Maps the RTL to generic gates with Yosys: cell counts, a gate-level netlist and an RTL schematic.",
    profiles=[BASE, OSIC], timeout=1800,
    params=[
        _p("top", "Top module", "module", "settings.top"),
        _p("flatten", "Flatten the hierarchy", "bool", True),
    ],
), _synth))

register(Flow(FlowDefinition(
    id="fpga_ice40", version="1", title="Build FPGA (iCE40)", category="implement",
    description="Yosys synth_ice40, nextpnr place & route against the pin file, icepack: a bitstream with its timing.",
    profiles=[BASE, OSIC], timeout=3600,
    params=[
        _p("top", "Top module", "module", "settings.top"),
        _p("device", "Device", "choice", "settings.fpga_device", ICE40_DEVICES),
        _p("package", "Package", "word", "settings.fpga_package"),
        _p("pcf", "Pin file (.pcf)", "file", "settings.pcf", [".pcf"]),
        _p("freq_mhz", "Target clock (MHz)", "float", 12.0, [1, 500]),
    ],
), _fpga))

register(Flow(FlowDefinition(
    id="ams_ngspice", version="1", title="SPICE simulation", category="ams",
    description="Runs a SPICE deck in ngspice (batch): its measurements, and the vectors it writes with wrdata as tables.",
    profiles=[BASE, OSIC], timeout=1200,
    params=[_p("deck", "SPICE deck", "file", "settings.spice", [".spice", ".sp", ".cir"])],
), _ngspice))


def get(flow_id: str) -> Flow | None:
    return FLOWS.get(flow_id)


def definitions() -> list[FlowDefinition]:
    return [f.definition for f in FLOWS.values()]
