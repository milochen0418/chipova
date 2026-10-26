"""``chipova.toml``: a project's settings for its runs, kept with its sources (so every snapshot
has the settings its runs used).

The settings form writes the whole file at once and only when nobody changed it meanwhile
(:func:`chipova.services.projects.save_settings` compares the file's hash); the file can also be
edited by hand, and a file that doesn't parse gives the defaults plus the error.
"""

from __future__ import annotations

import tomllib
from typing import Any

from chipova.domain.models import ProjectSettings

FILE = "chipova.toml"

# (section, key in the file) -> field of ProjectSettings
_FIELDS = {
    ("design", "top"): "top",
    ("design", "rtl"): "rtl",
    ("design", "sdc"): "sdc",
    ("design", "clock_port"): "clock_port",
    ("design", "clock_period_ns"): "clock_period_ns",
    ("sim", "testbench"): "testbench",
    ("sim", "sources"): "sim",
    ("asic", "pdk"): "pdk",
    ("fpga", "family"): "fpga_family",
    ("fpga", "device"): "fpga_device",
    ("fpga", "package"): "fpga_package",
    ("fpga", "pins"): "fpga_pins",
    ("fpga", "pcf"): "pcf",
    ("ams", "spice"): "spice",
    ("ams", "cace"): "cace",
    ("ams", "testbench"): "schematic_tb",
}

_HEADER = """\
# Chipova project settings: what the runs use. Change them in the project's Settings,
# or here (every snapshot keeps this file with the sources).
"""


def parse(text: str) -> tuple[ProjectSettings, str]:
    """The settings in the file's text, and "" or what is wrong with it."""
    try:
        data = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as e:
        return ProjectSettings(), f"{FILE}: {e}"
    values: dict[str, Any] = {}
    for (section, key), field in _FIELDS.items():
        part = data.get(section)
        if isinstance(part, dict) and key in part:
            values[field] = part[key]
    try:
        return ProjectSettings.model_validate(values), ""
    except Exception as e:  # noqa: BLE001 — a wrong type in the file
        return ProjectSettings(), f"{FILE}: {e}"


def dump(settings: ProjectSettings) -> str:
    out = [_HEADER]
    section = ""
    for (sec, key), field in _FIELDS.items():
        if sec != section:
            out.append(f"\n[{sec}]")
            section = sec
        out.append(f"{key} = {_toml(getattr(settings, field))}")
    return "\n".join(out) + "\n"


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value)) if isinstance(value, float) else str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'
