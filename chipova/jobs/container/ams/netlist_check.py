"""Xschem exits 0 even when it could not netlist: the netlist must exist, hold something, and name
no symbol xschem could not find.

    netlist_check.py <netlist.spice>

Exit 0 = the netlist is there, 1 = it isn't or a symbol is missing. Python's standard library only.
"""

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    if not path.is_file() or path.stat().st_size == 0:
        print(f"xschem wrote no netlist: {path.name}")
        return 1
    missing = [line.strip() for line in path.read_text(errors="replace").splitlines() if "IS MISSING" in line]
    if missing:
        print("the netlist names symbols xschem could not find:")
        print("\n".join(missing[:20]))
        return 1
    print(f"netlist: {path.name}, {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
