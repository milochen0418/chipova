"""Checks a project's package plan against its design, and draws the bond diagram.

    package_check.py <ports.json> <package.toml> <pins.csv> <top> <outdir>

``ports.json`` is Yosys' ``write_json`` of the design (its top module's ports, with directions
and widths). ``package.toml`` names the package ([package] type, pins, body_mm, pitch_mm, osat,
notes); ``pins.csv`` maps its pins: ``pin,signal,kind,pad`` (kind: input, output, inout, power,
ground, nc). Checked: every bit of every top-level port is on exactly one pin (a bus bit as
``name[i]``), every signal on a pin is a port or a supply, pin numbers are within the package and
used once, and there is at least one power and one ground pin. Writes report.json and bond.svg;
prints a one-line JSON summary; exit 0 = the plan is consistent, 1 = it isn't, 2 = bad input.
Python's standard library only.
"""

from __future__ import annotations

import csv
import html
import json
import math
import sys
import tomllib
from pathlib import Path

KINDS = {"input", "output", "inout", "power", "ground", "nc"}
COLORS = {"input": "#2dd4bf", "output": "#fbbf24", "inout": "#a78bfa", "power": "#f87171", "ground": "#60a5fa", "nc": "#475569"}


def ports_of(ports_json: dict, top: str) -> dict[str, str]:
    """The top module's port bits ({"clk": "input", "led[0]": "output", …})."""
    module = (ports_json.get("modules") or {}).get(top)
    if module is None:
        raise ValueError(f"the design has no module {top!r}")
    out = {}
    for name, p in (module.get("ports") or {}).items():
        bits = p.get("bits") or []
        if len(bits) == 1:
            out[name] = p.get("direction", "")
        else:
            offset = int(p.get("offset", 0) or 0)
            for i in range(len(bits)):
                out[f"{name}[{i + offset}]"] = p.get("direction", "")
    return out


def read_pins(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(line for line in fh if not line.lstrip().startswith("#")):
            rows.append({k.strip(): (v or "").strip() for k, v in row.items() if k})
    return rows


def check(ports: dict[str, str], package: dict, pins: list[dict]) -> dict:
    count = int(package.get("pins", 0) or 0)
    problems: list[str] = []
    seen_pins: dict[int, str] = {}
    on_pins: dict[str, list[int]] = {}
    for row in pins:
        try:
            number = int(row.get("pin", ""))
        except ValueError:
            problems.append(f"pin {row.get('pin')!r} is not a number")
            continue
        kind = row.get("kind", "").lower()
        signal = row.get("signal", "")
        if kind not in KINDS:
            problems.append(f"pin {number}: kind {kind!r} is not one of {', '.join(sorted(KINDS))}")
        if count and not 1 <= number <= count:
            problems.append(f"pin {number} is outside the package's {count} pins")
        if number in seen_pins:
            problems.append(f"pin {number} is used twice ({seen_pins[number]}, {signal})")
        seen_pins[number] = signal
        if kind in ("input", "output", "inout"):
            if signal not in ports:
                problems.append(f"pin {number}: {signal!r} is not a port of the design")
            else:
                on_pins.setdefault(signal, []).append(number)
                if ports[signal] != kind:
                    problems.append(f"pin {number}: {signal} is an {ports[signal]} of the design, the plan says {kind}")
    for port in sorted(ports):
        where = on_pins.get(port, [])
        if not where:
            problems.append(f"port {port} is on no pin")
        elif len(where) > 1:
            problems.append(f"port {port} is on pins {', '.join(map(str, where))}")
    kinds = [r.get("kind", "").lower() for r in pins]
    if "power" not in kinds:
        problems.append("no power pin")
    if "ground" not in kinds:
        problems.append("no ground pin")
    return {
        "ok": not problems, "problems": problems, "package": package.get("type", ""), "pins": count,
        "ports": len(ports), "mapped": sum(1 for p in ports if on_pins.get(p)),
        "power_pins": kinds.count("power"), "ground_pins": kinds.count("ground"),
    }


def bond_svg(package: dict, pins: list[dict], top: str) -> str:
    """A QFN-style picture: the package's pins round its edges (pin 1 at the top of the left side,
    counter-clockwise), the die's pads, and a bond wire for each pin that has a signal."""
    count = max(4, int(package.get("pins", 0) or len(pins) or 4))
    side = math.ceil(count / 4)
    size, body, die = 640, 440, 180
    c = size / 2
    pitch = body / (side + 1)

    def pin_xy(n: int) -> tuple[float, float, str]:
        i = n - 1
        s, k = divmod(i, side)
        t = (k + 1) * pitch - body / 2
        if s == 0:
            return c - body / 2 - 18, c + t, "left"
        if s == 1:
            return c + t, c + body / 2 + 18, "bottom"
        if s == 2:
            return c + body / 2 + 18, c - t, "right"
        return c - t, c - body / 2 - 18, "top"

    def pad_xy(n: int) -> tuple[float, float]:
        x, y, edge = pin_xy(n)
        scale = die / body
        return c + (x - c) * scale * 0.82, c + (y - c) * scale * 0.82

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" font-family="ui-monospace, monospace" font-size="11">',
        f'<rect width="{size}" height="{size}" fill="#020617"/>',
        f'<rect x="{c - body / 2}" y="{c - body / 2}" width="{body}" height="{body}" rx="10" fill="#0f172a" stroke="#334155"/>',
        f'<rect x="{c - die / 2}" y="{c - die / 2}" width="{die}" height="{die}" fill="#134e4a" stroke="#2dd4bf"/>',
        f'<text x="{c}" y="{c + 4}" fill="#99f6e4" text-anchor="middle">{html.escape(top)}</text>',
        f'<text x="{c}" y="22" fill="#e2e8f0" text-anchor="middle" font-size="13">{html.escape(str(package.get("type", "")))} · {count} pins</text>',
    ]
    by_pin = {}
    for row in pins:
        try:
            by_pin[int(row.get("pin", ""))] = row
        except ValueError:
            pass
    for n in range(1, count + 1):
        x, y, edge = pin_xy(n)
        row = by_pin.get(n, {})
        kind = (row.get("kind") or "nc").lower()
        color = COLORS.get(kind, "#475569")
        if row.get("signal") and kind != "nc":
            px, py = pad_xy(n)
            parts.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="1.2" opacity="0.8"/>')
            parts.append(f'<rect x="{px - 3:.1f}" y="{py - 3:.1f}" width="6" height="6" fill="{color}"/>')
        w, h = (14, 8) if edge in ("left", "right") else (8, 14)
        parts.append(f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w}" height="{h}" fill="{color}"/>')
        label = html.escape(row.get("signal") or "")
        num = f'<tspan fill="#64748b">{n}</tspan>'
        if edge == "left":
            parts.append(f'<text x="{x - 12:.1f}" y="{y + 4:.1f}" text-anchor="end" fill="#e2e8f0">{label} {num}</text>')
        elif edge == "right":
            parts.append(f'<text x="{x + 12:.1f}" y="{y + 4:.1f}" fill="#e2e8f0">{num} {label}</text>')
        elif edge == "bottom":
            parts.append(f'<text x="{x:.1f}" y="{y + 20:.1f}" text-anchor="end" fill="#e2e8f0" transform="rotate(-60 {x:.1f} {y + 20:.1f})">{label} {num}</text>')
        else:
            parts.append(f'<text x="{x:.1f}" y="{y - 12:.1f}" fill="#e2e8f0" transform="rotate(-60 {x:.1f} {y - 12:.1f})">{num} {label}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print(__doc__)
        return 2
    ports_json, package_toml, pins_csv, top, outdir = argv[1:]
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        ports = ports_of(json.loads(Path(ports_json).read_text()), top)
        package = tomllib.loads(Path(package_toml).read_text()).get("package", {})
        pins = read_pins(Path(pins_csv))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    report = check(ports, package, pins)
    report["pin_table"] = pins
    (out / "report.json").write_text(json.dumps(report, indent=1))
    (out / "bond.svg").write_text(bond_svg(package, pins, top))
    print(json.dumps({k: v for k, v in report.items() if k != "pin_table"}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
