"""The layout renderer's own process (started by :mod:`chipova.jobs.layout`; it imports only
KLayout). It reads requests from stdin and writes answers to stdout, each a 4-byte length and
a JSON body, a PNG following the body when there is one."""

import collections
import json
import struct
import sys
from pathlib import Path

import klayout.db as kdb
import klayout.lay as klay

BACKGROUND = "#020617"
views = collections.OrderedDict()


def view(path, lyp):
    key = path + "|" + lyp
    if key in views:
        views.move_to_end(key)
        return views[key]
    lv = klay.LayoutView()
    lv.set_config("background-color", BACKGROUND)
    lv.set_config("grid-visible", "false")
    lv.load_layout(path, True)
    if lyp and Path(lyp).is_file():
        lv.load_layer_props(lyp)
    lv.max_hier()
    lv.zoom_fit()
    views[key] = lv
    while len(views) > 3:
        _, old = views.popitem(last=False)
        old._destroy()
    return lv


def answer(req):
    lv = view(req["path"], req.get("lyp", ""))
    if req["op"] == "info":
        cv = lv.active_cellview()
        ly = cv.layout()
        box = cv.cell.dbbox()
        layers = []
        for p in lv.each_layer():
            if p.source_layer < 0:
                continue
            layers.append({"key": f"{p.source_layer}/{p.source_datatype}", "name": p.source_name or p.name or "", "color": f"#{p.fill_color & 0xFFFFFF:06x}"})
        cells = sorted({ly.cell(i).name for i in range(ly.cells())})
        return {"ok": True, "top": cv.cell.name, "dbu": ly.dbu, "bbox": [box.left, box.bottom, box.right, box.top],
                "layers": layers, "cells": cells[:500], "cell_count": len(cells)}, b""
    hidden = set(req.get("hidden") or [])
    for p in lv.each_layer():
        if p.source_layer >= 0:
            p.visible = f"{p.source_layer}/{p.source_datatype}" not in hidden
    x0, y0, x1, y1 = req["box"]
    box = kdb.DBox(x0, y0, x1, y1)
    lv.zoom_box(box)
    png = lv.get_pixels_with_options(int(req["w"]), int(req["h"]), 0, 1, 0.0, box).to_png_data()
    return {"ok": True, "png": len(png)}, png


def main():
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    while True:
        head = inp.read(4)
        if len(head) < 4:
            return
        (n,) = struct.unpack(">I", head)
        req = json.loads(inp.read(n))
        try:
            body, extra = answer(req)
        except Exception as e:  # noqa: BLE001 — told to the page
            body, extra = {"ok": False, "error": f"{type(e).__name__}: {e}"}, b""
        data = json.dumps(body).encode()
        out.write(struct.pack(">I", len(data)) + data + extra)
        out.flush()


if __name__ == "__main__":
    main()
