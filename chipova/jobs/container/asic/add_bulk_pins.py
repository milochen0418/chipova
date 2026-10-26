#!/usr/bin/env python3
"""Add the sky130 body pins (VPB, VNB) to every std-cell instance of a Verilog netlist.

SC 0.38 + lambdapdk 0.2.22 write netlists whose sky130_fd_sc_* instances connect only
VPWR/VGND (the lambdapdk LEF has no VPB/VNB pins), while the extracted layout ties the
cells' VPB/VNB to the supply nets through the tap cells. netgen then fails with
"_noconnect_" nets on VPB/VNB. Tie VPB to the instance's VPWR net and VNB to its VGND net.

usage: add_bulk_pins.py <in.v> <out.v>
"""
import re
import sys

INST = re.compile(r"\b(sky130_fd_sc_\w+)\s+(\\\S+\s|\S+)\s*\((.*?)\);", re.S)


def fix(m):
    body = m.group(3)
    if ".VPB(" in body or ".VNB(" in body:
        return m.group(0)
    g = re.search(r"\.VGND\(([^)]*)\)", body)
    p = re.search(r"\.VPWR\(([^)]*)\)", body)
    if not (g and p):
        return m.group(0)
    extra = f",\n    .VNB({g.group(1)}),\n    .VPB({p.group(1)})"
    return f"{m.group(1)} {m.group(2).rstrip()} ({body.rstrip()}{extra});"


def main(src, dst):
    text = open(src).read()
    out, n = INST.subn(fix, text)
    open(dst, "w").write(out)
    print(f"patched {n} instances -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
