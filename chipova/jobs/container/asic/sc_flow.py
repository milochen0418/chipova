#!/usr/bin/env python3
"""Chipova driver: run a SiliconCompiler (0.38, new API) RTL->GDS flow and dump a JSON report.

While the flow runs, a watcher prints a marker line as each flow node starts and finishes
(``@@chipova node-start <step>/<index>``, ``@@chipova node-end <step>/<index>``), from the node
folders SiliconCompiler makes, so Chipova can show the flowgraph live.

Runs inside the job container (offline, uid 1000, HOME=/work/home, cwd = a writable dir).
Needs the SC data cache baked into the image (see Dockerfile; default /opt/sc-cache).

Example:
  python3 /work/job/sc_flow.py --top heartbeat --src /work/src/heartbeat.v \
      --sdc /work/src/heartbeat.sdc --param N=8 --pdk sky130 --threads 6 \
      --out result.json --collect final

Exit code: 0 = flow finished and every node succeeded, 1 = flow failed, 2 = bad arguments.
The JSON report is written in both cases (as far as the run got).
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time
import traceback

TARGETS = {
    "sky130": "skywater130_demo", "skywater130": "skywater130_demo",
    "ihp130": "ihp130_demo", "sg13g2": "ihp130_demo",
    "gf180": "gf180_demo",
    "freepdk45": "freepdk45_demo",
    "asap7": "asap7_demo",
}


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", required=True, help="top module name (also the SC design name)")
    ap.add_argument("--src", action="append", required=True,
                    help="Verilog/SystemVerilog source (repeatable)")
    ap.add_argument("--sdc", action="append", default=[], help="SDC file (repeatable)")
    ap.add_argument("--inc", action="append", default=[], help="include dir (repeatable)")
    ap.add_argument("--define", action="append", default=[], help="NAME or NAME=VALUE")
    ap.add_argument("--param", action="append", default=[], help="top parameter NAME=VALUE")
    ap.add_argument("--pdk", default="sky130", choices=sorted(TARGETS))
    ap.add_argument("--jobname", default="job0")
    ap.add_argument("--builddir", default="build")
    ap.add_argument("--cachedir", default=os.environ.get("CHIPOVA_SC_CACHE", "/opt/sc-cache"))
    ap.add_argument("--threads", type=int, default=0,
                    help="max threads per tool (0 = SC default = all visible CPUs; set this "
                         "to the container --cpus value)")
    ap.add_argument("--density", type=float, default=None, help="target core utilisation %%")
    ap.add_argument("--coremargin", type=float, default=None, help="core margin (um)")
    ap.add_argument("--timeout", type=float, default=None, help="per-node timeout (s)")
    ap.add_argument("--no-vercheck", action="store_true",
                    help="skip SC tool version checks. DO NOT USE with SC 0.38.10: the yosys "
                         "script reads the version recorded by the check and, without it, "
                         "emits 'abc -fast', which yosys 0.70 rejects (synthesis fails)")
    ap.add_argument("--png-res", type=int, default=0,
                    help="resolution of the KLayout layout PNG (default 4096)")
    ap.add_argument("--no-full-gds", action="store_true",
                    help="do not write <top>.full.gds (SC GDS with the real std-cell layouts "
                         "merged in; needed for sky130 DRC/LVS, see gds_merge_cells.py)")
    ap.add_argument("--full-png", type=int, default=0, metavar="PX",
                    help="also render <top>.full.png (PX x PX) from the full GDS with KLayout")
    ap.add_argument("--out", default="sc_result.json", help="JSON report path")
    ap.add_argument("--collect", default=None,
                    help="copy the final artifacts + logs into this dir (small, for upload)")
    ap.add_argument("--verbose", action="store_true", help="stream tool logs to stdout")
    return ap.parse_args(argv)


def build_project(args):
    from siliconcompiler import ASIC, Design
    from siliconcompiler import targets

    design = Design(args.top)
    with design.active_fileset("rtl"):
        design.set_topmodule(args.top)
        for f in args.src:
            design.add_file(os.path.abspath(f))
        for d in args.inc:
            design.add_idir(os.path.abspath(d))
        for d in args.define:
            design.add_define(d)
        for p in args.param:
            name, _, value = p.partition("=")
            design.set_param(name, value)
    filesets = ["rtl"]
    if args.sdc:
        with design.active_fileset("sdc"):
            for f in args.sdc:
                design.add_file(os.path.abspath(f), filetype="sdc")
        filesets.append("sdc")

    project = ASIC(design)
    project.add_fileset(filesets)
    getattr(targets, TARGETS[args.pdk])(project)

    opt = project.option
    opt.set_cachedir(args.cachedir)       # baked, read-only data cache -> no downloads
    opt.set_jobname(args.jobname)
    opt.set_builddir(args.builddir)
    opt.set_nodisplay(True)               # headless
    opt.set_nodashboard(True)
    opt.set_quiet(not args.verbose)       # tool output only in the per-node logs
    if args.no_vercheck:
        opt.set_novercheck(True)
    if args.timeout:
        opt.set_timeout(args.timeout)
    if args.threads > 0:
        opt.scheduler.set_maxthreads(args.threads)
    if args.density is not None:
        project.constraint.area.set_density(args.density)
    if args.coremargin is not None:
        project.constraint.area.set_coremargin(args.coremargin)
    if args.png_res > 0:
        from siliconcompiler.tools.klayout.export import ExportTask
        tasks = ExportTask.find_task(project)
        for t in (tasks if isinstance(tasks, set) else [tasks]):
            t.set_klayout_resolution(args.png_res, args.png_res)
    return project


def node_dir(proj, step, index):
    from siliconcompiler.utils.paths import workdir
    return workdir(proj, step, index)


def collect_report(proj, args, ok, error, wall):
    """Build the JSON-able report from a (history) project."""
    import siliconcompiler
    flow = proj.get_flow()
    order = [n for level in flow.get_execution_order() for n in level]
    metric_names = list(proj.getkeys("metric"))
    units = {m: proj.get("metric", m, field="unit") for m in metric_names}

    nodes = []
    for step, index in order:
        rec = {k: proj.get("record", k, step=step, index=index)
               for k in ("status", "starttime", "endtime", "toolversion", "toolpath",
                         "toolexitcode")}
        metrics = {}
        for m in metric_names:
            v = proj.get("metric", m, step=step, index=index)
            if v is not None:
                metrics[m] = v
        d = node_dir(proj, step, index)
        gnode = flow.get_graph_node(step, index)
        nodes.append({
            "step": step, "index": index,
            "tool": gnode.get_tool(), "task": gnode.get_task(),
            "status": rec["status"] or "not-run",
            "tasktime_s": metrics.get("tasktime"), "exetime_s": metrics.get("exetime"),
            "starttime": rec["starttime"], "endtime": rec["endtime"],
            "toolversion": rec["toolversion"], "toolexitcode": rec["toolexitcode"],
            "dir": d if os.path.isdir(d) else None,
            "tool_log": _exists(os.path.join(d, f"{step}.log")),
            "sc_log": _exists(os.path.join(d, f"sc_{step}_{index}.log")),
            "errors_file": _exists(os.path.join(d, f"{step}.errors")),
            "warnings_file": _exists(os.path.join(d, f"{step}.warnings")),
            "metrics": metrics,
        })
        if rec["status"] in ("error", "timeout"):
            nodes[-1]["log_tail"] = (_tail(nodes[-1]["sc_log"]) + _tail(nodes[-1]["tool_log"]))

    # final value of every metric = value from the last node (in execution order) that
    # reported it -- the same rule SC's summary table follows for the "final" column.
    summary = {}
    for n in nodes:
        if n["status"] != "success":
            continue
        for m, v in n["metrics"].items():
            summary[m] = {"value": v, "unit": units.get(m), "from": f"{n['step']}/{n['index']}"}

    jobdir = os.path.dirname(os.path.dirname(node_dir(proj, *order[0])))
    top = args.top

    def res(ext, step, filename=None):
        try:
            return proj.find_result(ext, step=step, filename=filename)
        except Exception:
            return None

    views = "write.views"
    artifacts = {
        "gds": res("gds", "write.gds"),
        "layout_png": res("png", "write.gds"),
        "def": res("def", views),
        # final gate-level netlists; for sky130 both carry fill/tap cells and VDD/VSS pins
        # (VPWR/VGND only -- see add_bulk_pins.py for LVS)
        "netlist": res("vg", views),
        "lvs_netlist": res(None, views, f"{top}.lvs.vg"),
        "synth_netlist": res("vg", "synthesis"),
        "sdc": res("sdc", views),
        "lef": res("lef", views),
        "odb": res("odb", views),
        "spef": sorted(glob.glob(os.path.join(node_dir(proj, views, "0"), "outputs", "*.spef"))),
        "sdf": sorted(glob.glob(os.path.join(node_dir(proj, views, "0"), "outputs", "*.sdf"))),
        "liberty": sorted(glob.glob(os.path.join(node_dir(proj, views, "0"), "outputs", "*.lib"))),
        "report_images": sorted(glob.glob(os.path.join(node_dir(proj, views, "0"), "reports",
                                                       "images", "**", "*.png"), recursive=True)),
        "manifest": _exists(os.path.join(jobdir, f"{top}.pkg.json")),
        "job_log": _exists(os.path.join(jobdir, "job.log")),
    }
    exit_outputs = {}
    for step, index in flow.get_exit_nodes():
        out = os.path.join(node_dir(proj, step, index), "outputs")
        exit_outputs[f"{step}/{index}"] = sorted(glob.glob(os.path.join(out, "*")))

    return {
        "ok": ok, "error": error, "wall_time_s": round(wall, 3),
        "failed_nodes": [f"{n['step']}/{n['index']}" for n in nodes
                         if n["status"] in ("error", "timeout")],
        "sc_version": siliconcompiler.__version__,
        "design": top, "pdk": proj.get("asic", "pdk"), "mainlib": proj.get("asic", "mainlib"),
        "flow": proj.option.get_flow(), "jobdir": jobdir,
        "nodes": nodes, "metric_units": units, "summary": summary,
        "artifacts": artifacts, "exit_node_outputs": exit_outputs,
    }


def _exists(p):
    return p if p and os.path.exists(p) else None


def _tail(path, n=30):
    if not path:
        return []
    with open(path, errors="replace") as f:
        return [line.rstrip("\n") for line in f.readlines()[-n:]]


def library_gds_files(proj):
    """GDS files of the std-cell/macro libraries the flow used (resolved in the SC cache)."""
    files = []
    for lib in proj.get("asic", "asiclib"):
        libobj = proj.get("library", lib, field="schema")
        for fs in libobj.get("asic", "aprfileset"):
            if libobj.valid("fileset", fs, "file", "gds"):
                files.extend(f for f in libobj.find_files("fileset", fs, "file", "gds") if f)
    return files


def write_full_gds(proj, report, args):
    """SC's KLayout export keeps LEF abstracts for cells whose LEF macro has no FOREIGN
    statement (lambdapdk 0.2.22 sky130hd). Overwrite them with the library layouts."""
    import klayout.db as db
    src = report["artifacts"]["gds"]
    libs = library_gds_files(proj)
    if not src or not libs:
        return None
    ly = db.Layout()
    ly.read(src)
    opt = db.LoadLayoutOptions()
    opt.cell_conflict_resolution = db.LoadLayoutOptions.CellConflictResolution.OverwriteCell
    for lib in libs:
        ly.read(lib, opt)
    for c in list(ly.top_cells()):
        if c.name != args.top:
            ly.prune_cell(c.cell_index(), -1)
    dst = os.path.join(os.path.dirname(src), f"{args.top}.full.gds")
    ly.write(dst)
    report["artifacts"]["gds_full"] = dst
    report["artifacts"]["gds_full_from"] = libs
    if args.full_png:
        import subprocess
        png = os.path.join(os.path.dirname(src), f"{args.top}.full.png")
        lyp = os.path.join(os.path.dirname(src), f"{args.top}.lyp")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gds_png.py")
        cmd = ["klayout", "-zz", "-r", script, "-rd", f"gds={dst}", "-rd", f"png={png}",
               "-rd", f"size={args.full_png}"]
        if os.path.exists(lyp):
            cmd += ["-rd", f"lyp={lyp}"]
        if subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.exists(png):
            report["artifacts"]["layout_png_full"] = png
    return dst


def collect_files(report, dest):
    os.makedirs(dest, exist_ok=True)
    a = report["artifacts"]
    picks = [a.get(k) for k in ("gds", "gds_full", "layout_png", "layout_png_full", "def",
                                "netlist", "lvs_netlist", "sdc", "lef", "job_log")]
    picks += a.get("spef", [])
    for p in picks:
        if p and os.path.exists(p):
            shutil.copy2(p, dest)
    logs = os.path.join(dest, "logs")
    os.makedirs(logs, exist_ok=True)
    for n in report["nodes"]:
        if n["tool_log"]:
            shutil.copy2(n["tool_log"], os.path.join(logs, f"{n['step']}.{n['index']}.log"))


def watch_nodes(args, stop):
    """Prints when each flow node starts (its folder appears) and ends (its outputs appear)."""
    jobdir = os.path.join(os.path.abspath(args.builddir), args.top, args.jobname)
    started, ended = set(), set()
    while not stop.wait(1.0):
        for d in sorted(glob.glob(os.path.join(jobdir, "*", "*"))):
            step, index = d.split(os.sep)[-2:]
            if not index.isdigit() or not os.path.isdir(d):
                continue
            key = f"{step}/{index}"
            if key not in started:
                started.add(key)
                print(f"@@chipova node-start {key}", flush=True)
            out = os.path.join(d, "outputs")
            if key not in ended and os.path.isdir(out) and os.listdir(out):
                ended.add(key)
                print(f"@@chipova node-end {key}", flush=True)


def main(argv=None):
    import threading

    args = parse_args(argv if argv is not None else sys.argv[1:])
    t0 = time.time()
    project = build_project(args)
    ok, error, result = False, None, None
    stop = threading.Event()
    watcher = threading.Thread(target=watch_nodes, args=(args, stop), daemon=True)
    watcher.start()
    try:
        result = project.run()          # returns the completed job's history project
        ok = True
    except Exception as e:              # node failure, missing tool, bad RTL, ...
        error = str(e)
        try:
            result = project.history(args.jobname)   # recorded once nodes started running
        except Exception:
            result = None
    wall = time.time() - t0
    stop.set()
    watcher.join(3)

    try:
        report = collect_report(result if result is not None else project, args, ok, error, wall)
        if ok and any(n["status"] not in ("success", "skipped", "not-run")
                      for n in report["nodes"]):
            report["ok"] = ok = False
    except Exception as e:
        report = {"ok": False, "error": f"{error} / report failed: {e}",
                  "traceback": traceback.format_exc(), "wall_time_s": round(wall, 3)}
        ok = False

    if ok and not args.no_full_gds:
        try:
            write_full_gds(result, report, args)
        except Exception as e:
            report["full_gds_error"] = str(e)

    if args.collect and ok:
        collect_files(report, args.collect)
        report["collected_dir"] = os.path.abspath(args.collect)

    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, default=str)
    s = report.get("summary", {})
    brief = {k: s[k]["value"] for k in ("cells", "cellarea", "totalarea", "setupwns", "setuptns",
                                       "holdwns", "holdtns", "fmax", "drcs", "drvs",
                                       "wirelength", "peakpower", "totaltime") if k in s}
    print(json.dumps({"ok": ok, "error": report.get("error"), "summary": brief}, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
