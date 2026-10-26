#!/usr/bin/env python3
"""Summarise a KLayout LVS run: lvsdb_summary.py <run.lvsdb> <klayout_lvs.log> [limit] -> JSON.

pass = the LVS log says "Congratulations! Netlists match." (the IHP/GF180 decks print it only when
the compare and, in strict mode, the top-level port check succeed). The cross-reference in the
.lvsdb gives the details: every circuit pair (top cell + each std cell) with its status, and for
circuits that did not match, the nets / devices / cell instances / pins without a partner.
Prints one JSON line; exit 0 = match, 1 = no match, 2 = the run did not finish (no verdict, no db).
Needs KLayout's Python module (klayout.db), which the image has.
"""
import json
import os
import sys

import klayout.db as db


def flat_devices(circuit, memo):
    if circuit is None:
        return 0
    key = circuit.name
    if key not in memo:
        n = sum(1 for _ in circuit.each_device())
        for sc in circuit.each_subcircuit():
            n += flat_devices(sc.circuit_ref(), memo)
        memo[key] = n
    return memo[key]


def name(obj):
    if obj is None:
        return None
    for attr in ("expanded_name", "name"):
        if hasattr(obj, attr):
            try:
                v = getattr(obj, attr)
                return v() if callable(v) else v
            except Exception:  # noqa: BLE001
                pass
    return str(obj)


def main(lvsdb, log, limit=20):
    text = open(log, errors="replace").read() if os.path.exists(log) else ""
    if "Congratulations! Netlists match." in text:
        verdict = "Netlists match"
    elif "Netlists don't match" in text:
        verdict = "Netlists don't match"
    else:
        print(json.dumps({"pass": False, "final_result": "no verdict in the LVS log", "error": True}))
        return 2
    out = {"final_result": verdict, "pass": verdict == "Netlists match"}
    if not os.path.exists(lvsdb):
        out["error"] = "no .lvsdb"
        print(json.dumps(out))
        return 2
    lvs = db.LayoutVsSchematic()
    lvs.read(lvsdb)
    xref = lvs.xref()
    lay, sch = lvs.netlist(), lvs.reference
    circuits, problems, warnings = {}, [], []
    for cp in xref.each_circuit_pair():
        a, b = cp.first(), cp.second()
        st = str(cp.status())
        label = a.name if a else (b.name if b else "?")
        circuits[st] = circuits.get(st, 0) + 1
        if st in ("Match", "Skipped"):
            # a matched circuit can still carry net pairs KLayout flags (e.g. supply nets whose
            # pin counts differ because of unconnected body pins): list them, they do not fail
            for p in xref.each_net_pair(cp):
                if str(p.status()) not in ("Match", "MatchWithWarning"):
                    warnings.append([label, name(p.first()), name(p.second()), str(p.status())])
            continue
        bad = {"circuit": label, "status": st, "layout": a.name if a else None,
               "schematic": b.name if b else None}
        for kind, it in (("nets", xref.each_net_pair), ("devices", xref.each_device_pair),
                         ("instances", xref.each_subcircuit_pair), ("pins", xref.each_pin_pair)):
            rows = []
            for p in it(cp):
                if str(p.status()) != "Match":
                    rows.append([name(p.first()), name(p.second()), str(p.status())])
            if rows:
                bad[kind] = rows[:limit]
                bad[kind + "_count"] = len(rows)
        problems.append(bad)
    top_l = lay.top_circuit() if lay is not None else None
    top_s = None
    if sch is not None and top_l is not None:
        top_s = sch.circuit_by_name(top_l.name) or sch.circuit_by_name(top_l.name.upper())
    out["top"] = top_l.name if top_l else None
    if top_l and top_s:
        count = lambda it: sum(1 for _ in it)  # noqa: E731
        out["nets"] = [count(top_l.each_net()), count(top_s.each_net())]
        out["instances"] = [count(top_l.each_subcircuit()), count(top_s.each_subcircuit())]
        out["devices"] = [flat_devices(top_l, {}), flat_devices(top_s, {})]
    out["circuits"] = circuits
    out["mismatches"] = problems
    if warnings:
        out["net_warnings"] = warnings[:limit]
    print(json.dumps(out))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  (a crash here must not read as "no match")
        print(json.dumps({"pass": False, "error": f"{type(e).__name__}: {e}"}))
        sys.exit(2)
