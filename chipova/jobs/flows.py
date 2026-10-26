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
from chipova.jobs import pdks
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
    # The steps it needs: it runs when they succeeded (and only then), whatever else failed.
    needs: list[str] | None = None

    def job(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "argv": self.argv, "cwd": self.cwd, "env": self.env,
            "timeout": self.timeout, "allow_fail": self.continue_on_fail or self.optional,
            **({"needs": self.needs} if self.needs is not None else {}),
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
        # "settings.a|b": the first of those settings that is set.
        for name in p.default.split(".", 1)[1].split("|"):
            value = getattr(settings, name, None)
            if value not in (None, ""):
                return value
        return None
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
# nextpnr-ecp5's device options (LFE5U-12F … LFE5UM5G-85F) and the ECP5 packages.
ECP5_DEVICES = ["12k", "25k", "45k", "85k", "um-25k", "um-45k", "um-85k", "um5g-25k", "um5g-45k", "um5g-85k"]
ECP5_PACKAGES = ["CABGA256", "CABGA381", "CABGA554", "CABGA756", "CSFBGA285", "TQFP144"]
# Gowin parts nextpnr-gowin 0.7 and apicula place and pack here, with their family names.
GOWIN_DEVICES = {"GW1NR-LV9QN88PC6/I5": "GW1N-9C"}
FPGA_FLOWS = ("fpga_ice40", "fpga_ecp5", "fpga_gowin")


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


def _fpga_ecp5(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    reads = "\n".join(f"read_verilog -sv {f}" for f in _src(files))
    script = f"{reads}\nsynth_ecp5 -top {top} -json {OUT}/fpga/{top}.json\n"
    return JobSpec(
        steps=[
            Step("synth", "Yosys synth_ecp5", "yosys", ["yosys", "-s", f"{JOB}/fpga.ys"], cwd=f"{OUT}/fpga", timeout=1200),
            Step("pnr", "nextpnr place & route", "nextpnr",
                 ["nextpnr-ecp5", f"--{ctx.params['device']}", "--package", ctx.params["package"], "--json", f"{top}.json",
                  "--lpf", f"{SRC}/{ctx.params['pins']}", "--textcfg", f"{top}.config", "--report", "report.json",
                  "--freq", f"{ctx.params['freq_mhz']:.3f}", "--seed", "1"],
                 cwd=f"{OUT}/fpga", timeout=1800),
            Step("pack", "ecppack bitstream", "ecppack", ["ecppack", "--compress", f"{top}.config", f"{top}.bit"], cwd=f"{OUT}/fpga", timeout=300),
        ],
        scripts={"fpga.ys": script.encode()},
        artifacts=[("fpga/*.bit", "bitstream"), ("fpga/*.config", "fpga_config"), ("fpga/report.json", "report"), (f"fpga/{top}.json", "json")],
        limits=Limits(cpus=2, memory_mb=4096, timeout=3600),
    )


def _fpga_gowin(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    reads = "\n".join(f"read_verilog -sv {f}" for f in _src(files))
    script = f"{reads}\nsynth_gowin -top {top} -json {OUT}/fpga/{top}.json\n"
    device = ctx.params["device"]
    return JobSpec(
        steps=[
            Step("synth", "Yosys synth_gowin", "yosys", ["yosys", "-s", f"{JOB}/fpga.ys"], cwd=f"{OUT}/fpga", timeout=1200),
            Step("pnr", "nextpnr place & route", "nextpnr",
                 ["nextpnr-gowin", "--device", device, "--family", GOWIN_DEVICES[device], "--json", f"{top}.json",
                  "--cst", f"{SRC}/{ctx.params['pins']}", "--write", f"{top}.pnr.json", "--report", "report.json",
                  "--freq", f"{ctx.params['freq_mhz']:.3f}", "--seed", "1"],
                 cwd=f"{OUT}/fpga", timeout=1800),
            Step("pack", "gowin_pack bitstream", "gowin_pack", ["gowin_pack", "-d", GOWIN_DEVICES[device], "-o", f"{top}.fs", f"{top}.pnr.json"],
                 cwd=f"{OUT}/fpga", timeout=300),
        ],
        scripts={"fpga.ys": script.encode()},
        artifacts=[("fpga/*.fs", "bitstream"), ("fpga/report.json", "report"), (f"fpga/{top}.json", "json")],
        limits=Limits(cpus=2, memory_mb=4096, timeout=3600),
    )


# ------------------------------------------------------------ the package plan

PACKAGE_FILES = ("package/package.toml", "package/pins.csv")
PACKAGE_CHECK = Path(__file__).parent / "container" / "package" / "package_check.py"


def _package(ctx: Context) -> JobSpec:
    top = ctx.params["top"]
    files = _need(rtl_files(ctx), "RTL files (.v/.sv)")
    missing = [f for f in PACKAGE_FILES if f not in ctx.files]
    if missing:
        raise FlowError(f"the snapshot has no package plan: {', '.join(missing)} (the Heartbeat template has an example)")
    reads = "\n".join(f"read_verilog -sv {f}" for f in _src(files))
    script = f"{reads}\nhierarchy -top {top}\nproc\nwrite_json {OUT}/package/ports.json\n"
    return JobSpec(
        steps=[
            Step("ports", "Yosys: the design's ports", "yosys", ["yosys", "-q", "-s", f"{JOB}/package.ys"], cwd=f"{OUT}/package", timeout=300),
            Step("check", "Package plan against the ports", "package_check",
                 ["python3", f"{JOB}/package_check.py", f"{OUT}/package/ports.json", f"{SRC}/{PACKAGE_FILES[0]}", f"{SRC}/{PACKAGE_FILES[1]}", top, f"{OUT}/package"],
                 cwd=f"{OUT}/package", timeout=120),
        ],
        scripts={"package.ys": script.encode(), "package_check.py": PACKAGE_CHECK.read_bytes()},
        artifacts=[("package/report.json", "report"), ("package/bond.svg", "image"), ("package/ports.json", "json")],
        limits=Limits(cpus=1, memory_mb=1024, timeout=600),
    )


# ------------------------------------------------------------ SPICE (ngspice)


def _ngspice(ctx: Context) -> JobSpec:
    deck = ctx.params["deck"]
    return JobSpec(
        steps=[Step("ngspice", "ngspice simulation", "ngspice", ["ngspice", "-b", f"{SRC}/{deck}"], cwd=f"{OUT}/ams", timeout=900)],
        artifacts=[("ams/*.csv", "table"), ("ams/*.raw", "spice_raw")],
        limits=Limits(cpus=1, memory_mb=2048, timeout=1200),
    )


# ------------------------------------------------------------ Xschem and CACE (IIC-OSIC-TOOLS)

AMS_DIR = Path(__file__).parent / "container" / "ams"
CACE_CPUS = 3


def _ams_scripts() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(AMS_DIR.iterdir()) if p.suffix in (".py", ".tcl")}


def _pdk_folder(ctx: Context) -> str:
    pdk = pdks.get(ctx.settings.pdk)
    if pdk is None:
        raise FlowError(f"chipova.toml's [asic] pdk {ctx.settings.pdk!r} isn't a PDK Chipova knows ({', '.join(pdks.PDKS)})")
    return pdk.folder


def _xschemrc(ctx: Context, near: str, folder: str) -> str:
    """The project's xschemrc next to ``near`` (or in xschem/, or at the top), else the PDK's own."""
    here = near.rsplit("/", 1)[0] + "/xschemrc" if "/" in near else "xschemrc"
    for rc in (here, "xschem/xschemrc", "xschemrc"):
        if rc in ctx.files:
            return f"{SRC}/{rc}"
    return f"/foss/pdks/{folder}/libs.tech/xschem/xschemrc"


def _pictures(ctx: Context, rcfile: str) -> Step:
    """Every schematic and symbol of the snapshot drawn as SVG and PNG (pictures.tcl). Xvfb gives
    Xschem a display (complete texts, PNG); its own HOME, as CACE's parallel Xschem runs can leave a
    damaged ~/.xschem/recent_files that makes Xschem with a display wait on a dialog; ``timeout``
    stops xvfb-run with its Xvfb."""
    dirs = sorted({f.rsplit("/", 1)[0] if "/" in f else "." for f in ctx.files if f.endswith((".sch", ".sym"))})
    return Step("pictures", "Schematic pictures (Xschem)", "xschem",
                ["timeout", "-k", "5", "240", "xvfb-run", "-a", "xschem", "-r", "-q", "--tcl", "set dark_colorscheme 0",
                 "--rcfile", rcfile, "--script", f"{JOB}/pictures.tcl"],
                cwd=f"{OUT}/pictures", timeout=300, optional=True,
                env={"PICTURES_SRC": SRC, "PICTURES_DIRS": ":".join(dirs), "PICTURES_OUT": f"{OUT}/pictures", "HOME": "/work/tmp", "PWD": f"{OUT}/pictures"})


def _picture_name(path: str) -> str:
    """pictures.tcl's name for a schematic's picture: xschem/inverter_tb.sch -> xschem__inverter_tb."""
    folder, _, name = path.rpartition("/")
    return f"{(folder or '.').replace('/', '_')}__{name.rsplit('.', 1)[0]}"


def _xschem_sim(ctx: Context) -> JobSpec:
    tb = ctx.params["testbench"]
    folder = _pdk_folder(ctx)
    name = tb.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    rc = _xschemrc(ctx, tb, folder)
    ams = f"{OUT}/ams"
    # The PDK's own ngspice settings, as CACE uses them (SKY130: KLU, HSPICE compatibility; IHP:
    # the PSP transistor model through OSDI).
    init = "spinit" if folder.startswith("sky130") else ".spiceinit"
    return JobSpec(
        steps=[
            # PWD: IHP's xschemrc reads it, and a process started without a shell has none.
            Step("netlist", "Xschem netlist", "xschem",
                 ["xschem", "-n", "-s", "-r", "-x", "-q", "--rcfile", rc, "-o", ams, "-N", f"{name}.spice", f"{SRC}/{tb}"],
                 cwd=ams, timeout=120, env={"PWD": ams}),
            Step("check", "Netlist written, no symbol missing", "generic", ["python3", f"{JOB}/netlist_check.py", f"{ams}/{name}.spice"], cwd=ams, timeout=60),
            Step("spiceinit", "The PDK's ngspice settings", "generic", ["cp", f"/foss/pdks/{folder}/libs.tech/ngspice/{init}", f"{ams}/.spiceinit"],
                 cwd=ams, timeout=60, optional=True),
            Step("ngspice", "ngspice simulation", "ngspice", ["ngspice", "-b", f"{name}.spice"], cwd=ams, timeout=900, continue_on_fail=True),
            _pictures(ctx, rc),
        ],
        scripts=_ams_scripts(),
        env={"PDK_ROOT": "/foss/pdks", "PDK": folder},
        artifacts=[
            (f"pictures/{_picture_name(tb)}.svg", "schematic"), ("pictures/*.svg", "image"), ("pictures/*.png", "image"),
            ("ams/*.csv", "table"), ("ams/*.raw", "spice_raw"), (f"ams/{name}.spice", "spice"),
        ],
        limits=Limits(cpus=1, memory_mb=2048, timeout=1500),
    )


def _cace(ctx: Context) -> JobSpec:
    sheet = ctx.params["datasheet"]
    folder = _pdk_folder(ctx)
    work = f"{OUT}/cace"
    tb = ctx.settings.schematic_tb
    shown = [(f"pictures/{_picture_name(tb)}.svg", "schematic")] if tb in ctx.files else []
    return JobSpec(
        steps=[
            # CACE writes netlist/, runs/ and docs/ into the project: a copy it can write (cp would
            # keep the snapshot's read-only modes).
            Step("copy", "A copy of the project CACE can write in", "generic", ["cp", "-R", "--no-preserve=mode,ownership", SRC, work], timeout=120),
            # Exit 0 = every spec met, 2 = one failed (the run fails; the steps after still run).
            # -j: the container's CPUs (CACE would take the host's). One parameter at a time: in
            # parallel they netlist at once, and concurrent Xschem runs damage ~/.xschem/recent_files.
            Step("cace", "CACE: every spec across its corners", "cace",
                 ["cace", sheet, "--source", "schematic", "-j", str(CACE_CPUS), "--parallel-parameters", "1", "--no-progress-bar"],
                 cwd=work, timeout=3600, continue_on_fail=True, env={"PWD": work}),
            Step("results", "CACE's results as tables", "generic",
                 ["python3", f"{JOB}/cace_results.py", work, sheet, f"{OUT}/results", "--log", f"{OUT}/steps/cace/stdout.log"], timeout=120, optional=True),
            _pictures(ctx, _xschemrc(ctx, tb or sheet, folder)),
        ],
        scripts=_ams_scripts(),
        env={"PDK_ROOT": "/foss/pdks", "PDK": folder},
        artifacts=[
            *shown, ("pictures/*.svg", "image"), ("pictures/*.png", "image"),
            ("results/cace_results.json", "json"), ("results/*.csv", "data"),
            ("cace/runs/*/summary.md", "report"), ("cace/runs/*/*.log", "log"),
            ("cace/runs/*/parameters/*/*.png", "plot"), ("cace/runs/*/parameters/*/simulation_summary.csv", "data"),
            ("cace/netlist/schematic/*.spice", "spice"),
        ],
        limits=Limits(cpus=CACE_CPUS, memory_mb=2048, timeout=3600),
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
        _p("pcf", "Pin file (.pcf)", "file", "settings.fpga_pins|pcf", [".pcf"]),
        _p("freq_mhz", "Target clock (MHz)", "float", "settings.clock_mhz", [1, 500]),
    ],
), _fpga))

register(Flow(FlowDefinition(
    id="fpga_ecp5", version="1", title="Build FPGA (ECP5)", category="implement",
    description="Yosys synth_ecp5, nextpnr place & route against the pin file (.lpf), ecppack: a Lattice ECP5 bitstream (ULX3S, OrangeCrab…) with its timing.",
    profiles=[BASE], timeout=3600,
    params=[
        _p("top", "Top module", "module", "settings.top"),
        _p("device", "Device", "choice", "settings.fpga_device", ECP5_DEVICES),
        _p("package", "Package", "choice", "settings.fpga_package", ECP5_PACKAGES),
        _p("pins", "Pin file (.lpf)", "file", "settings.fpga_pins", [".lpf"]),
        _p("freq_mhz", "Target clock (MHz)", "float", "settings.clock_mhz", [1, 500]),
    ],
), _fpga_ecp5))

register(Flow(FlowDefinition(
    id="fpga_gowin", version="1", title="Build FPGA (Gowin)", category="implement",
    description="Yosys synth_gowin, nextpnr-gowin against the pin file (.cst), apicula's gowin_pack: a Gowin GW1N bitstream (Tang Nano 9K) with its timing.",
    profiles=[BASE], timeout=3600,
    params=[
        _p("top", "Top module", "module", "settings.top"),
        _p("device", "Device", "choice", "settings.fpga_device", list(GOWIN_DEVICES)),
        _p("pins", "Pin file (.cst)", "file", "settings.fpga_pins", [".cst"]),
        _p("freq_mhz", "Target clock (MHz)", "float", "settings.clock_mhz", [1, 500]),
    ],
), _fpga_gowin))

register(Flow(FlowDefinition(
    id="ams_ngspice", version="1", title="SPICE simulation", category="ams",
    description="Runs a SPICE deck in ngspice (batch): its measurements, and the vectors it writes with wrdata as tables.",
    profiles=[BASE, OSIC], timeout=1200,
    params=[_p("deck", "SPICE deck", "file", "settings.spice", [".spice", ".sp", ".cir"])],
), _ngspice))

register(Flow(FlowDefinition(
    id="ams_xschem", version="1", title="Xschem simulation", category="ams",
    description="Xschem netlists a testbench schematic with the PDK's devices, ngspice simulates it with the PDK's settings: its measurements and the tables it writes, and pictures of the schematics.",
    profiles=[OSIC], timeout=1500,
    params=[_p("testbench", "Testbench schematic", "file", "settings.schematic_tb", [".sch"])],
), _xschem_sim))

register(Flow(FlowDefinition(
    id="ams_cace", version="1", title="Corners (CACE)", category="ams",
    description="CACE simulates every parameter of a datasheet across its process corners, supplies and temperatures, and checks each result against its limits: PASS only when every spec holds everywhere.",
    profiles=[OSIC], timeout=3600,
    params=[_p("datasheet", "CACE datasheet", "file", "settings.cace", [".yaml", ".yml"])],
), _cace))


register(Flow(FlowDefinition(
    id="package_check", version="1", title="Check the package plan", category="lab",
    description="Checks package/pins.csv against the design's top-level ports (Yosys): every port bit on exactly one pin, pins within the package and used once, power and ground pins; draws the bond diagram.",
    profiles=[BASE, OSIC], timeout=600,
    params=[_p("top", "Top module", "module", "settings.top")],
), _package))


def get(flow_id: str) -> Flow | None:
    return FLOWS.get(flow_id)


def definitions() -> list[FlowDefinition]:
    return [f.definition for f in FLOWS.values()]
