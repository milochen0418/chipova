#!/usr/bin/env python3
"""Summarise multi-corner OpenSTA runs (sta.tcl, one per corner) as JSON (standard library only).

usage: sta_result.py <outdir> <pdk> <name>=<lib_corner>:<rc_corner>:<spef> [...]
reads <outdir>/sta_<name>.log, sta_<name>.setup.json, sta_<name>.hold.json, sta_<name>.check_setup.rpt
and <outdir>/pdk_files.json; env ELAPSED_S (run time), STA_FAIL_ON_DRV=1 (max slew and max capacitance
violations fail the check too; by default they are only reported; max fanout is always only reported).
prints one JSON line; exit 0 = every corner meets setup and hold, 1 = a corner fails (or the
timing is not a post-layout timing: no clock, nets without parasitics, cells without timing),
2 = a tool failed.

Slacks are in ns. WNS and TNS follow the usual convention: 0 when nothing violates; the real worst
slack is "worst_slack_ns".
"""
import gzip
import json
import os
import re
import sys

PHYSICAL_ONLY = re.compile(r"(fill|tap|decap|diode|antenna|endcap|filler)", re.I)


def _f(x):
    """A finite float, or None (OpenSTA prints INF-like values when nothing is constrained)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if abs(v) < 1e6 else None


def power_ports(def_path):
    """Names of the DEF's pins with USE POWER / USE GROUND (the netlist's VDD/VSS ports)."""
    names, inside, cur = set(), False, None
    if not def_path or not os.path.isfile(def_path):
        return names
    op = gzip.open if def_path.endswith(".gz") else open
    with op(def_path, "rt", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("PINS"):
                inside = True
            elif s.startswith("END PINS"):
                break
            elif inside:
                if s.startswith("- "):
                    cur = s.split()[1]
                if cur and re.search(r"\+ USE (POWER|GROUND)", s):
                    names.add(cur)
    return names


def parse_log(path):
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return None
    out = {"done": "CHIPOVA_DONE:" in text, "black_boxes": sorted(set(re.findall(r"module (\S+) not found", text)))}
    for key in ("WS_max", "WS_min", "TNS_max", "TNS_min", "VIOLATORS_max", "VIOLATORS_min"):
        m = re.findall(rf"CHIPOVA_{key}: (\S+)", text)
        out[key] = _f(m[-1]) if m else None
    out["drv"] = {}
    for what in ("max_slew", "max_capacitance", "max_fanout"):
        m = re.findall(rf"CHIPOVA_DRV_{what}: (\S+)", text)
        out["drv"][what] = int(m[-1]) if m and m[-1].isdigit() else None
    m = re.findall(r"CHIPOVA_CLOCKS: (\d+)", text)
    out["clock_count"] = int(m[-1]) if m else 0
    m = re.findall(r"CHIPOVA_TIME_UNIT: (\S+)", text)
    out["time_unit"] = m[-1] if m else ""
    out["clocks"] = []
    for name, period, minp in re.findall(r"CHIPOVA_CLOCK: (\S+) (\S+) (\S+)", text):
        p, mp = _f(period), _f(minp)
        out["clocks"].append({"name": name, "period_ns": p, "min_period_ns": mp,
                              "fmax_mhz": round(1000.0 / mp, 2) if mp else None})
    m = re.findall(r"CHIPOVA_DANGLING_PORTS: ?(.*)", text)
    out["dangling_ports"] = m[-1].split() if m else []
    out["unannotated"] = [(s, n, int(k)) for s, n, k in re.findall(r"CHIPOVA_UNANNOTATED: (\S+) (\S+) (-?\d+)", text)]
    out["errors"] = [l for l in text.splitlines() if l.startswith("Error") or l.startswith("[ERROR")][:5]
    return out


def parse_check_setup(path, ignore):
    """check_setup -verbose: 'Warning: There are N <what>.' followed by indented names.
    -> {what: [names]} without the names in ignore (power/ground ports); a warning whose names
    are all ignored is dropped, a warning that lists no names is kept (with an empty list)."""
    out, listed, cur = {}, {}, None
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"Warning: There (?:is|are) \d+ (.*?)\.?$", line)
        if m or line.startswith("Warning"):
            cur = m.group(1) if m else line.split(":", 1)[-1].strip()
            out.setdefault(cur, [])
            listed.setdefault(cur, False)
        elif cur and line.startswith(" ") and line.strip():
            listed[cur] = True
            if line.strip() not in ignore:
                out[cur].append(line.strip())
    return {k: v for k, v in out.items() if v or not listed[k]}


def worst_path(path):
    try:
        checks = json.load(open(path)).get("checks", [])
    except (OSError, ValueError):
        return None
    checks = [c for c in checks if c.get("slack") is not None]
    if not checks:
        return None
    c = min(checks, key=lambda c: c["slack"])
    ns = lambda v: round(v * 1e9, 4) if isinstance(v, (int, float)) else None  # noqa: E731
    return {"group": c.get("path_group"), "from": c.get("startpoint"), "to": c.get("endpoint"),
            "clock": c.get("target_clock"), "arrival_ns": ns(c.get("data_arrival_time")),
            "required_ns": ns(c.get("required_time")), "slack_ns": ns(c.get("slack")),
            "stages": len(c.get("source_path") or [])}


def main(outdir, pdk, *specs):
    try:
        files = json.load(open(os.path.join(outdir, "pdk_files.json")))
    except (OSError, ValueError):
        files = {}
    fail_on_drv = os.environ.get("STA_FAIL_ON_DRV") == "1"
    res = {"check": "sta", "pdk": pdk, "tool": "OpenSTA (sta)", "parasitics": "OpenRCX SPEF per RC corner (pex.sh)",
           "clocks": "propagated", "corners": {}}
    if os.environ.get("ELAPSED_S"):
        res["time_s"] = float(os.environ["ELAPSED_S"])
    tool_failed = False
    any_fail = False
    pg = power_ports(os.environ.get("DEF"))
    res["power_ground_ports"] = sorted(pg)
    for spec in specs:
        name, rest = spec.split("=", 1)
        lib_corner, rc, spef = rest.split(":", 2)
        log = parse_log(os.path.join(outdir, f"sta_{name}.log"))
        meta = (files.get("corners") or {}).get(lib_corner, {})
        entry = {"liberty": meta.get("liberty"), "vdd_v": meta.get("vdd_v"), "rc": rc, "spef": spef}
        if log is None or not log["done"]:
            entry["error"] = (log or {}).get("errors") or "sta did not finish"
            tool_failed = True
            res["corners"][name] = entry
            continue
        problems = []
        for kind, mm in (("setup", "max"), ("hold", "min")):
            ws = log[f"WS_{mm}"]
            entry[kind] = {
                "worst_slack_ns": ws,
                "wns_ns": min(0.0, ws) if ws is not None else None,
                "tns_ns": log[f"TNS_{mm}"],
                "violating_endpoints": int(log[f"VIOLATORS_{mm}"] or 0),
                "worst_path": worst_path(os.path.join(outdir, f"sta_{name}.{kind}.json")),
            }
            if ws is None:
                problems.append(f"no {kind} path is constrained: nothing was timed")
            elif ws < 0:
                problems.append(f"{kind} violated: worst slack {ws} ns on {entry[kind]['violating_endpoints']} endpoints")
        entry["clocks"] = log["clocks"]
        entry["drv_violations"] = log["drv"]
        if log["clock_count"] == 0:
            problems.append("no clock is defined: nothing is timed")
        ignore = set(log["dangling_ports"]) | pg
        real_unannotated = [n for s, n, k in log["unannotated"]
                            if not (n in ignore or (k <= 1 and "/" in n) or k == 0)]
        entry["unannotated_drivers"] = real_unannotated
        if real_unannotated:
            problems.append(f"{len(real_unannotated)} driven nets have no extracted parasitics")
        entry["black_boxes"] = log["black_boxes"]
        no_timing = [b for b in log["black_boxes"] if not PHYSICAL_ONLY.search(b)]
        if no_timing:
            problems.append("cells without a timing model: " + ", ".join(no_timing[:10]))
        entry["constraint_warnings"] = parse_check_setup(os.path.join(outdir, f"sta_{name}.check_setup.rpt"), ignore)
        drv = (log["drv"].get("max_slew") or 0) + (log["drv"].get("max_capacitance") or 0)
        if fail_on_drv and drv:
            problems.append(f"{drv} max slew / max capacitance violations")
        entry["problems"] = problems
        entry["pass"] = not problems
        any_fail = any_fail or bool(problems)
        res["corners"][name] = entry
    timed = {k: v for k, v in res["corners"].items() if "setup" in v}
    if timed:
        s = min(timed.items(), key=lambda kv: kv[1]["setup"]["worst_slack_ns"] if kv[1]["setup"]["worst_slack_ns"] is not None else 1e9)
        h = min(timed.items(), key=lambda kv: kv[1]["hold"]["worst_slack_ns"] if kv[1]["hold"]["worst_slack_ns"] is not None else 1e9)
        res["worst"] = {"setup_slack_ns": s[1]["setup"]["worst_slack_ns"], "setup_corner": s[0],
                        "hold_slack_ns": h[1]["hold"]["worst_slack_ns"], "hold_corner": h[0]}
    res["pass"] = not tool_failed and not any_fail
    print(json.dumps(res))
    return 2 if tool_failed else (1 if any_fail else 0)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
