#!/usr/bin/env python3
"""Summarise per-corner power (report_power) and static IR drop (PDNSim) runs as JSON (stdlib only).

usage: power_result.py <outdir> <pdk> <corner>=<rc>:<spef>:<pdn_tech_lef> [...]
reads <outdir>/power_<c>.log (power_ir.tcl's output, with PDNSim's "IR report" blocks),
power_<c>.json (report_power -format json), power_<c>.activity.rpt, ir_<c>_<net>.csv and
<outdir>/pdk_files.json.
env IR_LIMIT_PCT (default 5): the check fails when, in a corner, the worst drop on the power net
    plus the worst rise on the ground net exceeds this % of that corner's supply voltage;
    POWER_LIMIT_MW (optional): the check also fails when a corner's total power exceeds it;
    ELAPSED_S: run time.
prints one JSON line; exit 0 = within limits and every supply net fully connected,
1 = over a limit or a supply net (or cell) not connected to its pins, 2 = a tool failed.
"""
import csv
import json
import os
import re
import sys


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _sig(x, n=6):
    """x with n significant digits (None stays None)."""
    return None if x is None else float(f"{x:.{n}g}")


def ir_blocks(text):
    """PDNSim's '########## IR report' and '########## EM analysis' blocks, by net."""
    ir, em = {}, {}
    for block in re.findall(r"#{10} IR report #+\n(.*?)\n#{20,}", text, re.S):
        d = dict((k.strip(), v.strip()) for k, v in (l.split(":", 1) for l in block.splitlines() if ":" in l))
        net = d.get("Net")
        if net:
            ir[net] = {
                "supply_v": _f(d.get("Supply voltage", "").split()[0] if d.get("Supply voltage") else None),
                "worst_voltage_v": _f((d.get("Worstcase voltage") or " ").split()[0]),
                "average_voltage_v": _f((d.get("Average voltage") or " ").split()[0]),
                "average_drop_v": _f((d.get("Average IR drop") or " ").split()[0]),
                "worst_drop_v": _f((d.get("Worstcase IR drop") or " ").split()[0]),
                "pdnsim_total_power_w": _f((d.get("Total power") or " ").split()[0]),
            }
    for block in re.findall(r"#{10} EM analysis #+\n(.*?)\n#{20,}", text, re.S):
        d = dict((k.strip(), v.strip()) for k, v in (l.split(":", 1) for l in block.splitlines() if ":" in l))
        net = d.get("Net")
        if net:
            em[net] = {"max_current_a": _f((d.get("Maximum current") or " ").split()[0]),
                       "average_current_a": _f((d.get("Average current") or " ").split()[0]),
                       "resistors": int(_f(d.get("Number of resistors")) or 0)}
    return ir, em


def worst_instance(path, ground):
    """The instance terminal with the lowest (power net) / highest (ground net) voltage."""
    try:
        rows = list(csv.DictReader(open(path)))
    except OSError:
        return None
    rows = [r for r in rows if _f(r.get("Voltage")) is not None]
    if not rows:
        return None
    r = (max if ground else min)(rows, key=lambda r: float(r["Voltage"]))
    return {"instance": r.get("Instance"), "terminal": r.get("Terminal"), "layer": r.get("Layer"),
            "x_um": _f(r.get("X location")), "y_um": _f(r.get("Y location")), "voltage_v": _f(r["Voltage"]),
            "terminals": len(rows)}


def activity(path):
    out = {}
    try:
        for line in open(path, errors="replace"):
            t = line.split()
            if len(t) == 2 and t[1].isdigit():
                out[t[0]] = int(t[1])
    except OSError:
        pass
    return out


def main(outdir, pdk, *specs):
    try:
        files = json.load(open(os.path.join(outdir, "pdk_files.json")))
    except (OSError, ValueError):
        files = {}
    limit_pct = float(os.environ.get("IR_LIMIT_PCT") or 5.0)
    power_limit = _f(os.environ.get("POWER_LIMIT_MW"))
    res = {"check": "power_ir", "pdk": pdk,
           "tool": "OpenSTA report_power (in OpenROAD) + PDNSim analyze_power_grid",
           "ir_model": "static IR drop (each cell draws its average current, from report_power) through the PDN "
                       "as routed in the DEF; ideal voltage sources at the supply nets' top-level pins (DEF PINS), "
                       "or on PDNSim's own bump pattern when a net has no pin; package and pads not modelled",
           "limits": {"ir_drop_pct_of_vdd": limit_pct, "power_mw": power_limit}, "corners": {}}
    if os.environ.get("ELAPSED_S"):
        res["time_s"] = float(os.environ["ELAPSED_S"])
    tool_failed = any_fail = False
    for spec in specs:
        corner, rest = spec.split("=", 1)
        rc, spef, pdn_tlef = rest.split(":", 2)
        meta = (files.get("corners") or {}).get(corner, {})
        entry = {"liberty": meta.get("liberty"), "vdd_v": meta.get("vdd_v"), "rc": rc, "spef": spef,
                 "pdn_tech_lef": pdn_tlef}
        try:
            text = open(os.path.join(outdir, f"power_{corner}.log"), errors="replace").read()
        except OSError:
            text = ""
        m = re.findall(r"CHIPOVA_ACTIVITY: (.*)", text)
        entry["activity"] = m[-1] if m else None
        cuts = dict(re.findall(r"CHIPOVA_CUT_RES: (\S+) (\S+)", text))
        if cuts:  # set from the PDK's values: the tech LEF has none for these cut layers
            entry["cut_res_ohm"] = {k: _f(v) for k, v in cuts.items()}
        entry["activity_annotation"] = activity(os.path.join(outdir, f"power_{corner}.activity.rpt"))
        problems = []
        try:
            pj = json.load(open(os.path.join(outdir, f"power_{corner}.json")))
            tot = pj.get("Total", {})
            entry["power_mw"] = {k: _sig(float(tot[k]) * 1e3) for k in ("total", "internal", "switching", "leakage") if k in tot}
            entry["power_groups_mw"] = {g: _sig(float(v.get("total", 0)) * 1e3) for g, v in pj.items() if g != "Total"}
        except (OSError, ValueError, KeyError):
            entry["error"] = "report_power gave no result"
            tool_failed = True
        m = re.findall(r"CHIPOVA_SUPPLY_NETS: power \{(.*?)\} ground \{(.*?)\}", text)
        power_nets, ground_nets = (m[-1][0].split(), m[-1][1].split()) if m else ([], [])
        entry["supply_nets"] = {"power": power_nets, "ground": ground_nets}
        # The log part of each supply net: from "CHIPOVA_IR_NET: <net>" to the next such line.
        parts = {}
        for m in re.finditer(r"CHIPOVA_IR_NET: (\S+) pins (\d+)\n(.*?)(?=CHIPOVA_IR_NET: |\Z)", text, re.S):
            parts[m.group(1)] = (int(m.group(2)), m.group(3))
        psm_msgs = [l for l in text.splitlines() if re.match(r"\[(WARNING|ERROR) PSM-", l)]
        if not power_nets or not ground_nets:
            problems.append("the DEF has no power or no ground net")
        entry["ir"] = {}
        total_drop = 0.0
        complete = bool(power_nets and ground_nets)
        vdd = _f(meta.get("vdd_v"))
        for net in power_nets + ground_nets:
            ground = net in ground_nets
            npins, part = parts.get(net, (0, ""))
            ir, em = ir_blocks(part)
            d = ir.get(net)
            err = re.findall(r"CHIPOVA_IR_ERROR: \S+ (.*)", part)
            if d is None and "PSM-0069" in part:
                # PDNSim's connectivity check failed: the design's PDN is broken (not a tool failure).
                loose = re.findall(r"PSM-0038\] Unconnected shape on net \S+ at (.*)", part)
                cells = re.findall(r"PSM-0039\] (.*)", part)
                entry["ir"][net] = {"error": "PSM-0069 check connectivity failed", "source_pins": npins,
                                    "connected": False, "unconnected_shapes": len(loose),
                                    "unconnected_examples": loose[:10], "other_messages": cells[:10]}
                problems.append(f"{net}: PDN not connected to its pins ({len(loose)} unconnected shapes)")
                complete = False
                continue
            if d is None:
                entry["ir"][net] = {"error": err[-1] if err else "PDNSim gave no IR report", "source_pins": npins}
                tool_failed = True
                complete = False
                continue
            bumps = re.findall(r"PSM-0073\] (.*)", part)
            drop = d["worst_drop_v"] or 0.0
            total_drop += drop
            e = {"source_pins": npins,
                 "voltage_sources": ("the net's top-level pins (DEF PINS)" if npins and not bumps
                                     else "PDNSim's own bump pattern: " + (bumps[-1] if bumps else "?")),
                 "supply_v": d["supply_v"],
                 "worst_drop_mv": _sig(drop * 1e3), "average_drop_mv": _sig((d["average_drop_v"] or 0) * 1e3),
                 "worst_drop_pct_of_vdd": _sig(100.0 * drop / vdd) if vdd else None,
                 "connected": bool(re.search(r"PSM-0040\] All shapes on net \S+ are connected", part)),
                 "worst_terminal": worst_instance(os.path.join(outdir, f"ir_{corner}_{net}.csv"), ground)}
            if net in em:
                e["em"] = em[net]
            entry["ir"][net] = e
            if not e["connected"]:
                problems.append(f"{net}: not every PDN shape / cell is connected to the net's pins")
            if not npins:
                entry.setdefault("warnings", []).append(
                    f"{net} has no top-level pin: PDNSim assumed a bump pattern on the top layer")
        if psm_msgs:
            entry["pdnsim_messages"] = psm_msgs[:20]
        # Worst drop on the power net(s) + worst rise on the ground net(s), only when all were analysed.
        entry["ir_drop_total_mv"] = _sig(total_drop * 1e3) if complete else None
        entry["ir_drop_total_pct_of_vdd"] = _sig(100.0 * total_drop / vdd) if vdd and complete else None
        if vdd and 100.0 * total_drop / vdd > limit_pct:
            problems.append(f"IR drop {100.0 * total_drop / vdd:.3f}% of VDD > {limit_pct}%")
        if power_limit is not None and entry.get("power_mw", {}).get("total", 0) > power_limit:
            problems.append(f"total power {entry['power_mw']['total']:.4g} mW > {power_limit} mW")
        entry["problems"] = problems
        entry["pass"] = not problems and "error" not in entry
        any_fail = any_fail or bool(problems)
        res["corners"][corner] = entry
    ok = {k: v for k, v in res["corners"].items() if v.get("ir_drop_total_pct_of_vdd") is not None}
    if ok:
        w = max(ok.items(), key=lambda kv: kv[1]["ir_drop_total_pct_of_vdd"])
        p = max(ok.items(), key=lambda kv: (kv[1].get("power_mw") or {}).get("total", 0))
        res["worst"] = {"ir_drop_total_mv": w[1]["ir_drop_total_mv"], "ir_drop_total_pct_of_vdd": w[1]["ir_drop_total_pct_of_vdd"],
                        "ir_corner": w[0], "power_mw": (p[1].get("power_mw") or {}).get("total"), "power_corner": p[0]}
    res["pass"] = not tool_failed and not any_fail
    print(json.dumps(res))
    return 2 if tool_failed else (1 if any_fail else 0)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
