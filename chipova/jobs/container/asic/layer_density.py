#!/usr/bin/env python3
"""Per-layer density of a layout: merged layer area / layout extent area (the "global" density
the PDK density decks check), for decks that do not print the numbers (GF180).

usage: layer_density.py <layout.gds[.gz]> <top> (--pdk gf180 | NAME=L/D[+L/D...] ...)
  --pdk gf180   COMP, Poly2, Metal1-5 and MetalTop of a 5-metal GF180MCU stack, each with its
                dummy (fill) datatype 4 (e.g. Metal2 = 36/0 + 36/4)
Prints one JSON line {"area_um2": extent area, "bbox_um": [...], "layers": {NAME: {"area_um2",
"density_pct"}}}; exit 0, or 2 on failure. Needs KLayout's Python module (klayout.db).
"""
import json
import sys

import klayout.db as db

PRESETS = {
    "gf180": {"COMP": "22/0+22/4", "Poly2": "30/0+30/4", "Metal1": "34/0+34/4",
              "Metal2": "36/0+36/4", "Metal3": "42/0+42/4", "Metal4": "46/0+46/4",
              "Metal5": "81/0+81/4", "MetalTop": "53/0+53/4"},
}


def main(argv):
    gds, top, specs = argv[0], argv[1], {}
    rest = argv[2:]
    while rest:
        a = rest.pop(0)
        if a == "--pdk":
            specs.update(PRESETS[rest.pop(0)])
        else:
            name, _, layers = a.partition("=")
            specs[name] = layers
    ly = db.Layout()
    ly.read(gds)
    cell = ly.cell(top)
    if cell is None:
        raise ValueError(f"no cell {top}")
    box = cell.bbox()
    total = box.width() * box.height() * ly.dbu * ly.dbu
    out = {"area_um2": round(total, 3), "bbox_um": [round(v, 3) for v in (
        box.left * ly.dbu, box.bottom * ly.dbu, box.right * ly.dbu, box.top * ly.dbu)], "layers": {}}
    for name, layers in specs.items():
        reg = db.Region()
        for spec in layers.split("+"):
            ln, dt = (int(x) for x in spec.split("/"))
            li = ly.find_layer(ln, dt)
            if li is not None:
                reg += db.Region(cell.begin_shapes_rec(li))
        reg.merge()
        area = reg.area() * ly.dbu * ly.dbu
        out["layers"][name] = {"area_um2": round(area, 2),
                               "density_pct": round(100.0 * area / total, 2) if total else None}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit(2)
