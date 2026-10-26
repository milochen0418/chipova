"""The Full chip run puts only the template's editable sources of a snapshot over the template."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1] / "chipova" / "jobs" / "container" / "chip" / "chip_overlay.py"


def overlay(src: Path, tree: Path) -> tuple[int, dict]:
    out = subprocess.run([sys.executable, str(OVERLAY), str(src), str(tree)], capture_output=True, text=True, check=False)
    return out.returncode, json.loads(out.stdout or "{}")


def test_only_the_editable_sources_go_over_the_template(tmp_path: Path):
    tree, src = tmp_path / "tree", tmp_path / "src"
    (tree / "rtl").mkdir(parents=True)
    (tree / "rtl" / "chip_core.sv").write_text("module chip_core; endmodule\n")
    (tree / "Makefile").write_text("all:\n")
    (tree / ".chipova-template").write_text("2026.09 cf12265\n")
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "chip_core.sv").write_text("module chip_core; // changed\nendmodule\n")
    (src / "Makefile").write_text("all:\n\techo not from the snapshot\n")
    (src / "chipova.toml").write_text("")
    (src / "schematic" / "xschem").mkdir(parents=True)
    (src / "schematic" / "xschem" / "new.sch").write_text("v {xschem version=3.4.8}\n")
    rc, r = overlay(src, tree)
    assert rc == 0 and r["changed"] == ["rtl/chip_core.sv", "schematic/xschem/new.sch"] and r["template"] == "2026.09 cf12265", r
    assert set(r["left_out"]) == {"Makefile", "chipova.toml"}
    assert "changed" in (tree / "rtl" / "chip_core.sv").read_text() and (tree / "Makefile").read_text() == "all:\n"
    assert (tree / ".chipova-started").is_file()
    # The same snapshot again changes nothing.
    rc, r = overlay(src, tree)
    assert rc == 0 and r["changed"] == [] and r["unchanged"] == 2
