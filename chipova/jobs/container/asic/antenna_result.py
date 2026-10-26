#!/usr/bin/env python3
"""Summarise an OpenROAD check_antennas run as JSON (standard library only).

usage: antenna_result.py <antenna.rpt> <antenna.log> <cell.lef> <design.def[.gz]> [pdk]
prints one JSON line; exit 0 = no violation, 1 = violations, 2 = the check did not run properly.

antenna.rpt is check_antennas' -report_file: blocks of
    Net: <net>
      Pin:   <inst/pin> (<cell>)
        Layer: <layer>
          Partial area ratio:    48.04
          Required ratio:    4.00 (Side area) (VIOLATED)
Only lines marked (VIOLATED) are kept. The log gives the tool's own totals (ANT-0002 nets,
ANT-0001 pins) and the routed-net count printed by antenna.tcl. The cell LEF and the DEF are
read to list input pins of the cells used that have no ANTENNAGATEAREA (such pins can't be
checked, so they would make a clean result meaningless).
"""
import gzip
import json
import os
import re
import sys

_RATIO = re.compile(r"^(Partial|Cumulative) area ratio:\s*([-\d.eE+]+)")
_REQ = re.compile(r"^Required ratio:\s*([-\d.eE+]+)\s*\(([^)]*)\)\s*(\(VIOLATED\))?")


def parse_report(path):
    nets = []
    net = pin = cell = layer = None
    last_ratio = None
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return None
    for raw in lines:
        s = raw.strip()
        if s.startswith("Net:"):
            net = {"net": s[4:].strip(), "violations": []}
            nets.append(net)
        elif s.startswith("Pin:"):
            m = re.match(r"Pin:\s*(\S+)\s*(?:\((\S+)\))?", s)
            pin, cell = (m.group(1), m.group(2)) if m else (s[4:].strip(), None)
        elif s.startswith("Layer:"):
            layer = s[6:].strip()
        else:
            m = _RATIO.match(s)
            if m:
                last_ratio = (m.group(1).lower(), float(m.group(2)))
                continue
            m = _REQ.match(s)
            if m and m.group(3) and net is not None:
                net["violations"].append({
                    "pin": pin, "cell": cell, "layer": layer, "rule": m.group(2),
                    "ratio": last_ratio[1] if last_ratio else None,
                    "ratio_kind": last_ratio[0] if last_ratio else None,
                    "required": float(m.group(1)),
                })
    return [n for n in nets if n["violations"]]


def parse_log(path):
    out = {}
    pats = {
        "net_violations": r"ANT-0002\] Found (\d+) net violations",
        "pin_violations": r"ANT-0001\] Found (\d+) pin violations",
        "routed_signal_nets": r"CHIPOVA_SIGNAL_NETS_ROUTED: (\d+)",
        "unrouted_signal_nets": r"CHIPOVA_SIGNAL_NETS_UNROUTED: (\d+)",
        "check_antennas_returned": r"CHIPOVA_ANTENNA_NETS: (-?\d+)",
    }
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return out, ""
    for k, p in pats.items():
        m = re.findall(p, text)
        if m:
            out[k] = int(m[-1])
    errors = [l for l in text.splitlines() if l.startswith("[ERROR")]
    return out, "\n".join(errors[:5])


def used_cells(def_path):
    op = gzip.open if def_path.endswith(".gz") else open
    cells, inside = set(), False
    with op(def_path, "rt", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("COMPONENTS"):
                inside = True
            elif s.startswith("END COMPONENTS"):
                break
            elif inside and s.startswith("-"):
                parts = s.split()
                if len(parts) >= 3:
                    cells.add(parts[2])
    return cells


def pins_without_gate_area(lef_path, cells):
    """Input pins (signal/clock) of the given cells with no ANTENNAGATEAREA in the LEF."""
    missing = []
    macro = pin = None
    direction = use = None
    has_gate = False
    with open(lef_path, errors="replace") as f:
        for line in f:
            t = line.split()
            if not t:
                continue
            if t[0] == "MACRO":
                macro = t[1]
            elif t[0] == "PIN" and macro in cells:
                pin, direction, use, has_gate = t[1], None, "SIGNAL", False
            elif pin and t[0] == "DIRECTION":
                direction = t[1]
            elif pin and t[0] == "USE":
                use = t[1].rstrip(";")
            elif pin and t[0] == "ANTENNAGATEAREA":
                has_gate = True
            elif pin and t[0] == "END" and len(t) > 1 and t[1] == pin:
                if direction == "INPUT" and use in ("SIGNAL", "CLOCK") and not has_gate:
                    missing.append(f"{macro}/{pin}")
                pin = None
            elif t[0] == "END" and len(t) > 1 and t[1] == macro:
                macro = None
    return missing


def main(rpt, log, lef, def_path, pdk=""):
    tool, errors = parse_log(log)
    nets = parse_report(rpt)
    out = {"check": "antenna", "pdk": pdk, "tool": "OpenROAD check_antennas"}
    out.update(tool)
    if os.environ.get("ELAPSED_S"):
        out["time_s"] = float(os.environ["ELAPSED_S"])
    try:
        files = json.load(open(os.environ["PDK_FILES"]))
        out["pdk_files"] = {"tech_lef": files["tech_lef"], "cell_lef": files["cell_lef"]}
    except (KeyError, OSError, ValueError):
        pass
    if nets is None and tool.get("net_violations") == 0:
        nets = []  # no report file: nothing to report
    if nets is None or "net_violations" not in tool:
        out["error"] = errors or "check_antennas did not finish (no ANT-0002 line in the log)"
        print(json.dumps(out))
        return 2
    try:
        cells = used_cells(def_path)
        out["cells_used"] = len(cells)
        out["input_pins_without_antenna_data"] = pins_without_gate_area(lef, cells)
        if out["input_pins_without_antenna_data"]:
            out["warnings"] = ["input pins without ANTENNAGATEAREA in the cell LEF can't be checked: "
                               + ", ".join(out["input_pins_without_antenna_data"][:10])]
    except OSError as e:
        out["lef_def_error"] = str(e)
    out["violating_nets"] = [
        {"net": n["net"], "violations": n["violations"][:20], "count": len(n["violations"])} for n in nets[:200]
    ]
    out["pass"] = tool.get("net_violations", 1) == 0 and tool.get("pin_violations", 1) == 0
    if tool.get("routed_signal_nets", 0) == 0:
        out["pass"] = False
        out["error"] = "no routed signal nets in the DEF: nothing was checked"
        print(json.dumps(out))
        return 2
    print(json.dumps(out))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:6]))
