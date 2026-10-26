#!/usr/bin/env python3
"""Replace LEF-abstract standard cells in a GDS with their real layouts.

Why: SiliconCompiler 0.38.10's KLayout export (macro_resolution_mode=0) only pulls a cell's
layout from the library GDS when the LEF macro has a FOREIGN statement. lambdapdk 0.2.22's
sky130hd merged LEF has none, so write.gds/0/outputs/<top>.gds.gz contains abstract cells
(pins, labels, boundary only). DRC/LVS on that file is meaningless. This script overwrites
every cell that also exists in the given library GDS file(s) with the library version and
prunes the unused library cells.

usage: python3 gds_merge_cells.py <in.gds[.gz]> <out.gds> <top> <lib.gds> [<lib.gds> ...]
"""
import sys
import klayout.db as db


def main(src, dst, top, libs):
    ly = db.Layout()
    ly.read(src)
    if ly.cell(top) is None:
        raise SystemExit(f"top cell {top} not in {src}")
    before = {c.name for c in ly.each_cell()}
    opt = db.LoadLayoutOptions()
    opt.cell_conflict_resolution = db.LoadLayoutOptions.CellConflictResolution.OverwriteCell
    for lib in libs:
        ly.read(lib, opt)
    # drop library cells the design does not use (they arrived as extra top cells)
    for c in list(ly.top_cells()):
        if c.name != top:
            ly.prune_cell(c.cell_index(), -1)
    replaced = sorted(n for n in before if ly.cell(n) is not None and not n.startswith("VIA_")
                      and n != top)
    ly.write(dst)
    print(f"replaced {len(replaced)} cells; top cells now: {[c.name for c in ly.top_cells()]}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
