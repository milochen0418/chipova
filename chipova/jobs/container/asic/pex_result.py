#!/usr/bin/env python3
"""Summarise an OpenRCX extraction (one SPEF per RC corner) as JSON (standard library only).

usage: pex_result.py <outdir> <top> <pdk> <rc_corner> [<rc_corner> ...]
reads <outdir>/pex_<rc>.log and <outdir>/<top>.<rc>.spef for each RC corner, <outdir>/pdk_files.json;
env BUILD_SPEF: the Build ASIC run's own SPEF, summarised next to ours for comparison (optional);
env ELAPSED_S: run time.
prints one JSON line; exit 0 = every RC corner extracted and every routed signal net is in its
SPEF, 1 = nets missing from a SPEF or signal nets left unrouted (opens), 2 = a tool failed.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spef_summary import summarise  # noqa: E402


def _log_numbers(path):
    out = {}
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return None
    m = re.findall(r"CHIPOVA_SIGNAL_NETS_ROUTED: (\d+)", text)
    if m:
        out["routed_signal_nets"] = int(m[-1])
    m = re.findall(r"CHIPOVA_SIGNAL_NETS_UNROUTED: (\d+)(.*)", text)
    if m:
        out["unrouted_signal_nets"] = int(m[-1][0])
        names = m[-1][1].split()
        if names:
            out["unrouted_examples"] = names
    m = re.findall(r"RCX-0045\] Extract (\d+) nets, (\d+) rsegs, (\d+) caps, (\d+) ccs", text)
    if m:
        n, r, c, cc = map(int, m[-1])
        out["openrcx"] = {"nets": n, "rsegs": r, "caps": c, "ccs": cc}
    m = re.findall(r"RCX-0440\] Coupling threshhold is ([\d.]+) fF", text)
    if m:
        out["coupling_threshold_ff"] = float(m[-1])
    out["written"] = "CHIPOVA_SPEF_WRITTEN" in text
    out["errors"] = [l for l in text.splitlines() if l.startswith("[ERROR")][:5]
    return out


def main(outdir, top, pdk, *rcs):
    try:
        files = json.load(open(os.path.join(outdir, "pdk_files.json")))
    except (OSError, ValueError):
        files = {}
    res = {"check": "pex", "pdk": pdk, "tool": "OpenROAD OpenRCX (extract_parasitics)", "format": "SPEF (IEEE 1481-1999)",
           "corners": {}}
    if os.environ.get("ELAPSED_S"):
        res["time_s"] = float(os.environ["ELAPSED_S"])
    failed = problems = False
    for rc in rcs:
        spef = os.path.join(outdir, f"{top}.{rc}.spef")
        log = _log_numbers(os.path.join(outdir, f"pex_{rc}.log"))
        entry = {"spef": spef}
        entry.update((files.get("rc_corners") or {}).get(rc, {}))
        if log is None or not log.get("written") or not os.path.isfile(spef):
            entry["error"] = (log or {}).get("errors") or "no SPEF written"
            failed = True
            res["corners"][rc] = entry
            continue
        s = summarise(spef)
        entry.update({k: log[k] for k in ("routed_signal_nets", "unrouted_signal_nets", "unrouted_examples",
                                           "openrcx", "coupling_threshold_ff") if k in log})
        entry.update({k: s[k] for k in ("nets", "total_cap_pf", "ground_cap_pf", "coupling_cap_pf",
                                         "coupling_cap_unique_pf", "total_res_ohm", "largest_nets")})
        entry["used_by"] = [c for c, v in (files.get("corners") or {}).items() if v.get("rc") == rc]
        found = []
        if s["nets"] < log.get("routed_signal_nets", 0):
            found.append(f"{log['routed_signal_nets'] - s['nets']} routed signal nets are not in the SPEF")
        if log.get("unrouted_signal_nets", 0):
            found.append(f"{log['unrouted_signal_nets']} signal nets have no routing (opens)")
        entry["problems"] = found
        problems = problems or bool(found)
        res["corners"][rc] = entry
    ref = os.environ.get("BUILD_SPEF")
    if ref and os.path.isfile(ref):
        s = summarise(ref)
        res["build_spef"] = {k: s[k] for k in ("file", "nets", "total_cap_pf", "ground_cap_pf", "coupling_cap_pf",
                                               "total_res_ohm")}
    res["pass"] = not failed and not problems
    print(json.dumps(res))
    return 2 if failed else (1 if problems else 0)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
