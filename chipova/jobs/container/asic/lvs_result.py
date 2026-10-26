#!/usr/bin/env python3
"""Summarise a netgen LVS run: lvs_result.py <lvs.rpt> [<lvs.json>] -> JSON on stdout.

pass = the "Final result:" line says exactly "Circuits match uniquely." and no cell has
property errors. Other final results: "Circuits match uniquely with port errors.",
"Netlists do not match.", "Top level cell failed pin matching.", "Subcell(s) failed matching."
"""
import json
import os
import sys


def main(rpt, js=None):
    text = open(rpt, errors="replace").read()
    final = ""
    for line in text.splitlines():
        if line.startswith("Final result:"):
            final = line[len("Final result:"):].strip()
    prop_err = "had property errors" in text
    out = {"final_result": final,
           "pass": final == "Circuits match uniquely." and not prop_err,
           "property_errors": prop_err}
    if js and os.path.exists(js):
        cells = json.load(open(js))
        top = cells[-1] if cells else {}
        out["top"] = top.get("name")
        out["nets"] = top.get("nets")
        out["devices"] = [sum(n for _, n in side) for side in top.get("devices", [[], []])]
        out["badnets"] = sum(len(c.get("badnets", [])) for c in cells)
        out["badelements"] = sum(len(c.get("badelements", [])) for c in cells)
    print(json.dumps(out))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
