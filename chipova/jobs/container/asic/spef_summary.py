#!/usr/bin/env python3
"""Summarise a SPEF file (IEEE 1481) with the standard library only.

usage: spef_summary.py <file.spef[.gz]> [<file2.spef> ...]  -> one JSON object per file on stdout
       (a JSON list when more than one file is given)

Per file: design, units, number of *D_NET nets, the sum of the nets' total capacitance (the
number on each *D_NET line: ground + coupling capacitance as seen by that net), the ground and
the coupling capacitance listed in the *CAP sections, the total resistance of the *RES sections,
and the five nets with the largest capacitance. Capacitances are in pF, resistances in ohm, no
matter which *C_UNIT / *R_UNIT the file uses.
A coupling capacitor is listed once per net that names it, so "coupling_cap_pf" counts every
listing; "coupling_cap_unique_pf" counts each (node, node) pair once.
"""
import gzip
import json
import sys

_C = {"FF": 1e-3, "PF": 1.0, "NF": 1e3, "UF": 1e6}
_R = {"OHM": 1.0, "KOHM": 1e3, "MOHM": 1e6}


def _open(path):
    return gzip.open(path, "rt", errors="replace") if path.endswith(".gz") else open(path, errors="replace")


def summarise(path):
    design = ""
    cscale, rscale = 1.0, 1.0
    names = {}
    nets = []  # (name, total_cap_pf)
    ground = coupling = res = 0.0
    n_cap = n_cc = n_res = 0
    pairs = {}
    section = ""
    in_map = False
    cur = None
    with _open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            tok = line.split()
            key = tok[0]
            if key == "*DESIGN":
                design = line.split(None, 1)[1].strip().strip('"') if len(tok) > 1 else ""
            elif key == "*C_UNIT" and len(tok) >= 3:
                cscale = float(tok[1]) * _C.get(tok[2].upper(), 1.0)
            elif key == "*R_UNIT" and len(tok) >= 3:
                rscale = float(tok[1]) * _R.get(tok[2].upper(), 1.0)
            elif key == "*NAME_MAP":
                in_map = True
            elif in_map and key.startswith("*") and key[1:].isdigit() and len(tok) >= 2:
                names[key] = tok[1]
            elif key in ("*PORTS", "*D_NET", "*R_NET", "*POWER_NETS", "*GROUND_NETS"):
                in_map = False
                if key == "*D_NET":
                    cur = names.get(tok[1], tok[1])
                    nets.append((cur, float(tok[2]) * cscale if len(tok) > 2 else 0.0))
                section = ""
            elif key in ("*CONN", "*CAP", "*RES", "*INDUC"):
                section = key
            elif key == "*END":
                section, cur = "", None
            elif section == "*CAP" and key.isdigit():
                val = float(tok[-1]) * cscale
                if len(tok) == 3:
                    ground += val
                    n_cap += 1
                elif len(tok) >= 4:
                    coupling += val
                    n_cc += 1
                    pairs[tuple(sorted((tok[1], tok[2])))] = val
            elif section == "*RES" and key.isdigit() and len(tok) >= 4:
                res += float(tok[3]) * rscale
                n_res += 1
    top = sorted(nets, key=lambda kv: -kv[1])[:5]
    return {
        "file": path,
        "design": design,
        "nets": len(nets),
        "total_cap_pf": round(sum(c for _, c in nets), 6),
        "ground_cap_pf": round(ground, 6),
        "coupling_cap_pf": round(coupling, 6),
        "coupling_cap_unique_pf": round(sum(pairs.values()), 6),
        "total_res_ohm": round(res, 3),
        "cap_entries": n_cap,
        "coupling_entries": n_cc,
        "res_entries": n_res,
        "largest_nets": [{"net": n, "cap_pf": round(c, 6)} for n, c in top],
    }


def main(paths):
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    out = []
    for p in paths:
        try:
            out.append(summarise(p))
        except (OSError, ValueError) as e:
            print(json.dumps({"file": p, "error": str(e)}))
            return 2
    print(json.dumps(out[0] if len(out) == 1 else out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
