#!/usr/bin/env python3
"""Check that a GDS holds the real standard-cell layouts, not LEF abstracts.

usage: gds_cell_check.py [--pdk ihp|gf180|sky130] <design.gds[.gz]> <top> <lib.gds> [<lib.gds> ...]

Every cell under <top> that also exists in a library GDS is compared with the library cell,
layer by layer (XOR of the cell's own and child shapes; labels count as dots, so a missing
label shows up too). A cell is "identical"
when no layer differs. The *_with_device_layers counts say how many of those cells have shapes
on the layers transistors are made of (--pdk ihp (default): Activ, GatPoly, Cont, nSD, pSD,
NWell, ThickGateOx; gf180: COMP, Poly2, Contact, Nplus, Pplus, Nwell, Dualgate; sky130: diff,
poly, licon1, nwell, nsdm, psdm): an abstract (LEF) cell has none.

Prints one JSON line: {"cells": N, "identical": n, "differs": {cell: [layers]},
"not_in_library": [...], "lib_cells_with_device_layers": n, "design_cells_with_device_layers": n}
exit 0 = every library cell used by the design is identical to the library's,
1 = some differ (e.g. abstracts: pins + boundary only), 2 = failure.
Needs KLayout's Python module (klayout.db), which the image has.
"""
import json
import sys

import klayout.db as db

# Layers that only transistors / wells use, per PDK. Used only for the "device layers" counts;
# the XOR covers every layer.
DEVICE_LAYERS_BY_PDK = {
    "ihp": {(1, 0), (5, 0), (6, 0), (7, 0), (14, 0), (31, 0), (44, 0)},
    "gf180": {(22, 0), (30, 0), (33, 0), (32, 0), (31, 0), (21, 0), (55, 0)},
    "sky130": {(65, 20), (66, 20), (66, 44), (64, 20), (93, 44), (94, 20)},
}
DEVICE_LAYERS = DEVICE_LAYERS_BY_PDK["ihp"]


def region(layout, cell, li):
    return db.Region(cell.begin_shapes_rec(li))


def main(design, top, libs):
    dl = db.Layout()
    dl.read(design)
    topc = dl.cell(top)
    if topc is None:
        raise SystemExit(f"top cell {top} not in {design}")
    used = {dl.cell(ci).name for ci in topc.called_cells()}
    lib = db.Layout()
    for path in libs:
        lib.read(path)
    lib_names = {c.name for c in lib.each_cell()}
    identical, differs, not_in_lib = 0, {}, []
    dev_lib = dev_design = 0
    for name in sorted(used):
        if name not in lib_names:
            not_in_lib.append(name)
            continue
        dc, lc = dl.cell(name), lib.cell(name)
        bad = []
        keys = {(i.layer, i.datatype) for i in lib.layer_infos()} | \
               {(i.layer, i.datatype) for i in dl.layer_infos()}
        has_dev_l = has_dev_d = False
        for (ln, dt) in sorted(keys):
            li_l = lib.find_layer(ln, dt)
            li_d = dl.find_layer(ln, dt)
            rl = region(lib, lc, li_l) if li_l is not None else db.Region()
            rd = region(dl, dc, li_d) if li_d is not None else db.Region()
            # dbu may differ between the files: scale the library region to the design's dbu
            if li_l is not None and abs(lib.dbu - dl.dbu) > 1e-12:
                rl = rl.transformed(db.ICplxTrans(lib.dbu / dl.dbu))
            if (ln, dt) in DEVICE_LAYERS:
                has_dev_l = has_dev_l or not rl.is_empty()
                has_dev_d = has_dev_d or not rd.is_empty()
            if not (rl ^ rd).is_empty():
                bad.append(f"{ln}/{dt}")
        dev_lib += has_dev_l
        dev_design += has_dev_d
        if bad:
            differs[name] = bad
        else:
            identical += 1
    out = {"design": design, "top": top, "cells": len(used), "identical": identical,
           "differs": differs, "not_in_library": not_in_lib,
           "lib_cells_with_device_layers": dev_lib,
           "design_cells_with_device_layers": dev_design}
    print(json.dumps(out))
    return 0 if not differs and identical > 0 else 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv[:1] == ["--pdk"]:
        DEVICE_LAYERS = DEVICE_LAYERS_BY_PDK[argv[1]]
        argv = argv[2:]
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(main(argv[0], argv[1], argv[2:]))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)}))
        sys.exit(2)
