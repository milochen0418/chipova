#!/usr/bin/env python3
"""Turn a gate-level Verilog netlist (OpenROAD write_verilog, as SiliconCompiler writes it) into a
SPICE/CDL netlist for LVS: one .SUBCKT per Verilog module, an X line per cell instance with its
nets in the port order of the cell's .SUBCKT in the library CDL/SPICE, and the library .SUBCKTs
of the cells it uses copied in front (so the file stands alone).

usage: vg2spice.py <in.v> <cells.cdl|.spice> [<more cells.cdl> ...] -o <out.cdl>
                   [--top NAME] [--tie PIN=NET ...] [--skip-cells REGEX]
  --tie PIN=NET   connect cell pin PIN to net NET in every instance that leaves it out (e.g. a
                  netlist without supply pins: --tie VDD=VDD --tie VSS=VSS); NET = @OTHER means
                  "the net on the instance's pin OTHER" (GF180 body pins: --tie VNW=@VDD
                  --tie VPW=@VSS, like add_bulk_pins.py does for SKY130's VPB/VNB)
  --skip-cells    leave out instances whose cell name matches (e.g. 'fill|decap' for an LVS
                  that ignores them); default: keep every instance
Prints one JSON line: {"top":..., "instances": n, "cells": n, "nets": n, "unconnected_pins": n,
"tied_pins": n}; exit 0 = written, 2 = failure (unknown cell, parse error).
Only Python's standard library.

What it understands: module headers (ANSI or not), input/output/inout/wire declarations with
[msb:lsb] ranges, escaped identifiers (\\name ), bit-selects, named port connections
.PIN(net) / .PIN() (an unconnected pin gets its own net), assign a = b; (nets merged).
Refused with exit 2 (OpenROAD does not write them for SC's flows): positional connections,
concatenations {a,b} and constants 1'b0 on cell pins (use tie cells), assign joining two ports.
"""
import json
import re
import sys

TOKEN = re.compile(r"\\\S+|[A-Za-z_][A-Za-z0-9_$]*|\d+'[bBhHdDoO][0-9a-fA-FxXzZ_]+|\d+|\S")


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def ident(tok):
    """Escaped Verilog identifier -> plain name usable in SPICE."""
    if tok.startswith("\\"):
        tok = tok[1:]
    return re.sub(r"[=(),;{}]", "_", tok)


def read_subckts(paths):
    """{cell: (ports, text)} from .SUBCKT ... .ENDS blocks (continuation lines '+' joined)."""
    cells = {}
    for path in paths:
        lines = open(path, errors="replace").read().splitlines()
        joined = []
        for ln in lines:
            if ln.startswith("+") and joined:
                joined[-1] += " " + ln[1:]
            else:
                joined.append(ln)
        cur, body = None, []
        for ln in joined:
            low = ln.strip().lower()
            if low.startswith(".subckt"):
                f = ln.split()
                ports = [p for p in f[2:] if "=" not in p]
                cur, body = (f[1], ports), [ln]
            elif cur is not None:
                body.append(ln)
                if low.startswith(".ends"):
                    cells.setdefault(cur[0], (cur[1], "\n".join(body)))
                    cur = None
    return cells


class Module:
    def __init__(self, name):
        self.name, self.ports, self.dirs, self.ranges = name, [], {}, {}
        self.insts, self.assigns = [], []


def parse(text):
    toks = TOKEN.findall(strip_comments(text))
    mods, i = [], 0

    def expect(t):
        nonlocal i
        if toks[i] != t:
            raise ValueError(f"expected {t!r} at token {i}: {' '.join(toks[max(0, i - 5):i + 5])}")
        i += 1

    def rng():
        nonlocal i
        if toks[i] == "[":
            msb, lsb = int(toks[i + 1]), int(toks[i + 3])
            expect("[")
            i += 3
            expect("]")
            return msb, lsb
        return None

    def net_ref():
        nonlocal i
        t = toks[i]
        i += 1
        if "'" in t:
            return ("const", t)
        name = ident(t)
        if i < len(toks) and toks[i] == "[":
            idx = toks[i + 1]
            i += 2
            if toks[i] == ":":
                raise ValueError(f"part-select {name}[{idx}:...] in a port connection")
            expect("]")
            return ("net", f"{name}[{idx}]")
        return ("net", name)

    while i < len(toks):
        if toks[i] != "module":
            i += 1
            continue
        i += 1
        m = Module(ident(toks[i]))
        i += 1
        if toks[i] == "#":
            raise ValueError("parameterised module in a gate-level netlist")
        expect("(")
        while toks[i] != ")":                         # header: names, or ANSI declarations
            if toks[i] in ("input", "output", "inout"):
                d = toks[i]
                i += 1
                if toks[i] in ("wire", "reg"):
                    i += 1
                r = rng()
                name = ident(toks[i])
                i += 1
                m.ports.append(name)
                m.dirs[name], m.ranges[name] = d, r
            elif toks[i] == ",":
                i += 1
            else:
                m.ports.append(ident(toks[i]))
                i += 1
        expect(")")
        expect(";")
        while toks[i] != "endmodule":
            t = toks[i]
            if t in ("input", "output", "inout", "wire", "supply0", "supply1", "tri"):
                i += 1
                if toks[i] in ("wire", "reg"):
                    i += 1
                r = rng()
                while True:
                    name = ident(toks[i])
                    i += 1
                    if t in ("input", "output", "inout"):
                        m.dirs[name], m.ranges[name] = t, r
                    if toks[i] == ",":
                        i += 1
                        continue
                    expect(";")
                    break
            elif t == "assign":
                i += 1
                a = net_ref()
                expect("=")
                b = net_ref()
                expect(";")
                m.assigns.append((a, b))
            else:                                     # cell instance
                cell = ident(t)
                i += 1
                if toks[i] == "#":
                    raise ValueError(f"parameterised instance of {cell}")
                inst = ident(toks[i])
                i += 1
                expect("(")
                conns = {}
                while toks[i] != ")":
                    if toks[i] == ",":
                        i += 1
                        continue
                    if toks[i] != ".":
                        raise ValueError(f"positional connection in {cell} {inst}")
                    i += 1
                    pin = ident(toks[i])
                    i += 1
                    expect("(")
                    if toks[i] == ")":
                        conns[pin] = None
                    elif toks[i] == "{":
                        raise ValueError(f"concatenation on {inst}.{pin}")
                    else:
                        conns[pin] = net_ref()
                    expect(")")
                expect(")")
                expect(";")
                m.insts.append((cell, inst, conns))
        i += 1
        mods.append(m)
    return mods


def expand_ports(m):
    out = []
    for p in m.ports:
        r = m.ranges.get(p)
        if r is None:
            out.append(p)
        else:
            step = -1 if r[0] >= r[1] else 1
            out += [f"{p}[{k}]" for k in range(r[0], r[1] + step, step)]
    return out


def main(argv):
    args, libs, out, top, ties, skip = list(argv), [], None, None, {}, None
    vin = args.pop(0)
    while args:
        a = args.pop(0)
        if a == "-o":
            out = args.pop(0)
        elif a == "--top":
            top = args.pop(0)
        elif a == "--tie":
            pin, _, net = args.pop(0).partition("=")
            ties[pin] = net
        elif a == "--skip-cells":
            skip = re.compile(args.pop(0))
        else:
            libs.append(a)
    if not out or not libs:
        print(__doc__, file=sys.stderr)
        return 2
    cells = read_subckts(libs)
    mods = parse(open(vin).read())
    if not mods:
        raise ValueError("no module in the netlist")
    names = {m.name for m in mods}
    top = top or mods[-1].name
    used, lines, stats = [], [], {"instances": 0, "unconnected_pins": 0, "tied_pins": 0}
    nets_seen = set()
    for m in mods:
        parent = {}

        def find(x):
            while parent.get(x, x) != x:
                x = parent[x]
            return x

        port_set = set(expand_ports(m))
        consts = {}
        for a, b in m.assigns:                         # merge assigned nets, keep port names
            if b[0] == "const":
                consts[a[1]] = b[1]
                continue
            ra, rb = find(a[1]), find(b[1])
            if ra != rb:
                if ra in port_set and rb in port_set:
                    # two ports on one net: a SPICE .SUBCKT cannot short its own pins
                    raise ValueError(f"assign {a[1]} = {b[1]} joins two ports of {m.name}")
                if rb in port_set:
                    ra, rb = rb, ra
                parent[rb] = ra
        ports = expand_ports(m)
        lines.append(f".SUBCKT {m.name} {' '.join(ports)}")
        for cell, inst, conns in m.insts:
            if skip is not None and skip.search(cell):
                continue
            if cell in names:
                order = expand_ports(next(x for x in mods if x.name == cell))
            elif cell in cells:
                order = cells[cell][0]
                if cell not in used:
                    used.append(cell)
            else:
                raise ValueError(f"cell {cell} (instance {inst}) is in no library netlist given")
            nets = []
            for pin in order:
                ref = conns.get(pin)
                if ref is None and pin not in conns and pin in ties:
                    net = ties[pin]
                    if net.startswith("@"):
                        other = conns.get(net[1:])
                        if other is None or other[0] != "net":
                            raise ValueError(f"{inst}: --tie {pin}={net}, but {net[1:]} is not connected")
                        net = find(other[1])
                    nets.append(net)
                    stats["tied_pins"] += 1
                    continue
                if ref is None:
                    nets.append(f"_nc_{inst}_{pin}")
                    stats["unconnected_pins"] += 1
                    continue
                kind, val = ref
                if kind == "const":
                    raise ValueError(f"constant {val} on {inst}.{pin}: use tie cells")
                if val in consts:
                    raise ValueError(f"net {val} is assigned a constant ({consts[val]})")
                nets.append(find(val))
            nets_seen.update(nets)
            unknown = set(conns) - set(order)
            if unknown:
                raise ValueError(f"{inst} ({cell}) connects pins the cell has not: {sorted(unknown)}")
            stats["instances"] += 1
            lines.append(f"X{inst} {' '.join(nets)} {cell}")
        lines.append(f".ENDS {m.name}")
        lines.append("")
    with open(out, "w") as f:
        f.write(f"* {top}: from {vin} by vg2spice.py; cells from {', '.join(libs)}\n\n")
        for c in used:
            f.write(cells[c][1] + "\n\n")
        f.write("\n".join(lines) + "\n")
    res = {"top": top, "out": out, "cells": len(used), "nets": len(nets_seen), **stats}
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit(2)
