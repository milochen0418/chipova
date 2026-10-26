"""What a Full chip run of the IHP chip template shows, from the tree its make targets built.

    chip_collect.py <template tree> <outdir>

Reads what this run wrote (never a file older than the run's start: the template ships results of
its own): LibreLane's final metrics of the chip (padframe, timing at every corner, gate-level
LVS, antenna, IR drop, power), the chip's Magic DRC count, the cocotb results. Copies the chip's
GDS (no fill), its picture, LibreLane's reports and the DRC report into <outdir>, and writes
<outdir>/chip.json. Exit 0. Python's standard library only.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

METRICS = {
    "design__die__bbox": "die_bbox_um", "design__io": "io_count", "design__instance__count__padcells": "pad_cells",
    "design__instance__count__macros": "macros", "design__instance__count__stdcell": "std_cells",
    "timing__setup__ws": "setup_slack_ns", "timing__hold__ws": "hold_slack_ns",
    "timing__setup_vio__count": "setup_violations", "timing__hold_vio__count": "hold_violations",
    "design__max_slew_violation__count": "max_slew_violations", "design__max_cap_violation__count": "max_cap_violations",
    "timing__drv__floating__nets": "floating_nets", "design__lvs_error__count": "lvs_errors",
    "antenna__violating__nets": "antenna_violating_nets", "route__drc_errors": "route_drc_errors",
    "ir__drop__worst": "ir_drop_worst_v", "power__total": "power_w", "design__lint_error__count": "lint_errors",
}


def fresh(path: Path, since: float) -> bool:
    return path.is_file() and path.stat().st_mtime >= since


def cocotb(xml_path: Path, since: float) -> dict | None:
    if not fresh(xml_path, since):
        return None
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return {"error": "results.xml can't be read"}
    cases = root.findall(".//testcase")
    failed = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None]
    return {"tests": len(cases), "failed": failed}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    tree, out = Path(argv[1]), Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    started = (tree / ".chipova-started").stat().st_mtime if (tree / ".chipova-started").is_file() else 0.0
    result: dict = {"template": (tree / ".chipova-template").read_text().strip() if (tree / ".chipova-template").is_file() else ""}
    runs = sorted((tree / "flow" / "librelane" / "runs").glob("RUN_*"))
    metrics = runs[-1] / "final" / "metrics.json" if runs else None
    if metrics is not None and fresh(metrics, started):
        m = json.loads(metrics.read_text())
        result["chip"] = {name: m.get(key) for key, name in METRICS.items() if key in m}
        shutil.copy(metrics, out / "librelane_metrics.json")
    rpt = tree / "verification" / "drc" / "chip_top.magic.drc" / "chip_top.magic.drc.rpt"
    if fresh(rpt, started):
        text = rpt.read_text(errors="replace")
        counts = [int(n) for n in re.findall(r"COUNT:\s*(\d+)", text)]
        result["chip_magic_drc"] = {"violations": sum(counts) if counts else None}
        shutil.copy(rpt, out / "chip_top.magic.drc.rpt")
    result["cocotb"] = {
        name: r for name, r in (
            ("chip", cocotb(tree / "testbenches" / "cocotb" / "sim_build" / "results.xml", started)),
            ("counter", cocotb(tree / "macros" / "counter" / "testbenches" / "cocotb" / "sim_build" / "results.xml", started)),
        ) if r is not None
    }
    for src, name in ((tree / "layout" / "chip_top.gds.gz", "chip_top.gds.gz"), (tree / "render" / "img" / "chip_top_librelane.png", "chip_top.png")):
        if fresh(src, started):
            shutil.copy(src, out / name)
    reports = tree / "verification" / "reports"
    if reports.is_dir():
        (out / "reports").mkdir(exist_ok=True)
        for f in sorted(reports.glob("*.rpt")):
            if fresh(f, started):
                shutil.copy(f, out / "reports" / f.name)
    (out / "chip.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
