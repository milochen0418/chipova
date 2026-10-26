"""Puts a snapshot's files over the chip template's tree, for the Full chip flow.

    chip_overlay.py <snapshot dir> <template tree>

Only the template's sources a person edits are taken (ALLOWED, by folder); a file the template
doesn't have in such a folder is added. Anything else in the snapshot (chipova.toml, the README,
files elsewhere) is left out, and listed. Marks the run's start (.chipova-started) for
chip_collect.py. Prints a JSON summary. Exit 0, or 2 when a path would leave the tree. Python's
standard library only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ALLOWED = (
    "rtl/", "flow/librelane/", "macros/counter/rtl/", "macros/counter/flow/", "macros/counter/testbenches/",
    "macros/inverter/schematic/", "schematic/", "testbenches/cocotb/",
)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, tree = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    # The run's start: chip_collect.py takes only results written after it.
    (tree / ".chipova-started").write_text("")
    changed, same, left_out = [], 0, []
    for folder, _, names in os.walk(src):
        for name in names:
            path = Path(folder, name)
            rel = path.relative_to(src).as_posix()
            if not rel.startswith(ALLOWED) or path.is_symlink():
                left_out.append(rel)
                continue
            dst = (tree / rel).resolve()
            if tree not in dst.parents:
                print(json.dumps({"error": f"{rel} would leave the template's tree"}))
                return 2
            data = path.read_bytes()
            if dst.is_file() and dst.read_bytes() == data:
                same += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            changed.append(rel)
    template = (tree / ".chipova-template").read_text().strip() if (tree / ".chipova-template").is_file() else ""
    print(json.dumps({"template": template, "changed": sorted(changed), "unchanged": same, "left_out": sorted(left_out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
