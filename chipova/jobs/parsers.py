"""Problems and numbers read from the tools' own output.

Each tool reports errors in its own words; :func:`problems` turns a step's log into
:class:`~chipova.domain.models.Problem` rows (severity, file, line, column, message), with the
file as a path in the project (the container sees the sources under /work/src), so the
Problems panel can jump to the line. The raw logs are always kept as they are.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from chipova.domain.models import Problem, Severity

SRC = "/work/src/"
MAX_PROBLEMS = 500

_VERILATOR = re.compile(
    r"^%(?P<sev>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?: (?P<file>[^:\s]+):(?P<line>\d+):(?:(?P<col>\d+):)? ?(?P<msg>.*)$"
)
_VERILATOR_PLAIN = re.compile(r"^%(?P<sev>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?: (?P<msg>.*)$")
_IVERILOG = re.compile(r"^(?P<file>[^:\s]+\.(?:s?v|vh|svh)):(?P<line>\d+):\s*(?:(?P<sev>error|warning|sorry):\s*)?(?P<msg>.*)$", re.I)
_YOSYS_FILE = re.compile(r"^(?P<file>[^:\s]+\.(?:s?v|vh|svh)):(?P<line>\d+): (?P<sev>ERROR|Warning): (?P<msg>.*)$")
_YOSYS = re.compile(r"^(?P<sev>ERROR|Warning): (?P<msg>.*)$")
_NEXTPNR = re.compile(r"^(?P<sev>ERROR|Warning): (?P<msg>.*)$")
_OPENROAD = re.compile(r"^\[(?P<sev>ERROR|WARNING|CRITICAL) (?P<code>[A-Z]+-\d+)\] (?P<msg>.*)$")
_TB = re.compile(r"^(?:\s*\d+:\s*)?(?P<sev>FAIL|ERROR|FATAL)\b[:\s]*(?P<msg>.*)$")
_SPICE = re.compile(r"^(?P<sev>Error|Warning)(?: on line (?P<line>\d+))?\s*:?\s*(?P<msg>.*)$", re.I)
_VVP_ASSERT = re.compile(r"^(?P<sev>ERROR|FATAL|WARNING): (?P<file>[^:\s]+):(?P<line>\d+): (?P<msg>.*)$")


def _project_path(file: str) -> str:
    """A path the tool printed, as a path in the project ("" when it isn't one of its files)."""
    file = file.strip()
    if file.startswith(SRC):
        return file[len(SRC):]
    return ""


def _sev(word: str) -> Severity:
    w = (word or "").lower()
    if w in {"error", "fatal", "fail", "critical", "sorry"}:
        return Severity.ERROR
    if w == "warning":
        return Severity.WARNING
    return Severity.INFO


def problems(tool: str, step: str, lines: Iterable[str]) -> list[Problem]:
    out: list[Problem] = []
    parse = _PARSERS.get(tool, _generic)
    for line in lines:
        line = line.rstrip("\r\n")
        if not line or line.startswith("@@chipova"):
            continue
        p = parse(line, tool, step)
        if p is not None:
            out.append(p)
            if len(out) >= MAX_PROBLEMS:
                break
    return out


def _verilator(line: str, tool: str, step: str) -> Problem | None:
    m = _VERILATOR.match(line)
    if m:
        return Problem(
            severity=_sev(m["sev"]), tool=tool, step=step, file=_project_path(m["file"]),
            line=int(m["line"]), column=int(m["col"] or 0), code=m["code"] or "", message=m["msg"].strip(),
        )
    m = _VERILATOR_PLAIN.match(line)
    if m and not m["msg"].startswith("Exiting due to"):
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, code=m["code"] or "", message=m["msg"].strip())
    return None


def _iverilog(line: str, tool: str, step: str) -> Problem | None:
    m = _VVP_ASSERT.match(line)
    if m:
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, file=_project_path(m["file"]), line=int(m["line"]), message=m["msg"].strip())
    m = _IVERILOG.match(line)
    if m:
        sev = m["sev"] or ("warning" if "warning" in m["msg"].lower() else "error")
        return Problem(severity=_sev(sev), tool=tool, step=step, file=_project_path(m["file"]), line=int(m["line"]), message=m["msg"].strip())
    return _testbench(line, tool, step)


def _testbench(line: str, tool: str, step: str) -> Problem | None:
    """A testbench's own verdict lines ("FAIL …", "ERROR …"), as the templates print them."""
    m = _TB.match(line)
    if m:
        return Problem(severity=Severity.ERROR, tool=tool, step=step, message=line.strip())
    return None


def _yosys(line: str, tool: str, step: str) -> Problem | None:
    m = _YOSYS_FILE.match(line)
    if m:
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, file=_project_path(m["file"]), line=int(m["line"]), message=m["msg"].strip())
    m = _YOSYS.match(line)
    if m:
        msg = m["msg"].strip()
        file, lineno = "", 0
        loc = re.search(r"(/work/src/[^\s:]+):(\d+)", msg)
        if loc:
            file, lineno = _project_path(loc.group(1)), int(loc.group(2))
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, file=file, line=lineno, message=msg)
    return None


def _nextpnr(line: str, tool: str, step: str) -> Problem | None:
    m = _NEXTPNR.match(line)
    if m:
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, message=m["msg"].strip())
    return None


def _openroad(line: str, tool: str, step: str) -> Problem | None:
    m = _OPENROAD.match(line.strip())
    if m:
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, code=m["code"], message=m["msg"].strip())
    return None


def _spice(line: str, tool: str, step: str) -> Problem | None:
    m = _SPICE.match(line.strip())
    if m and m["msg"]:
        return Problem(severity=_sev(m["sev"]), tool=tool, step=step, line=int(m["line"] or 0), message=m["msg"].strip())
    return None


def _generic(line: str, tool: str, step: str) -> Problem | None:
    s = line.strip()
    if s.startswith(("ERROR", "Error:", "FATAL")):
        return Problem(severity=Severity.ERROR, tool=tool, step=step, message=s)
    return None


_PARSERS = {
    "verilator": _verilator,
    "iverilog": _iverilog,
    "vvp": _iverilog,
    "simulation": _testbench,
    "yosys": _yosys,
    "nextpnr": _nextpnr,
    "icepack": _generic,
    "openroad": _openroad,
    "siliconcompiler": _openroad,
    "ngspice": _spice,
}


# ------------------------------------------------------------ numbers


def sim_verdict(lines: Iterable[str]) -> dict:
    """What a testbench said: how many PASS and FAIL/ERROR lines."""
    passed = failed = 0
    for line in lines:
        s = line.strip()
        s = re.sub(r"^\d+:\s*", "", s)
        if s.startswith("PASS"):
            passed += 1
        elif re.match(r"^(FAIL|ERROR|FATAL)\b", s):
            failed += 1
    return {"pass_lines": passed, "fail_lines": failed}


def yosys_stat(stat_json: str) -> dict:
    """Cells and wires from ``stat -json`` (the top module, or the design's totals)."""
    try:
        data = json.loads(stat_json)
    except ValueError:
        return {}
    design = data.get("design") or {}
    modules = data.get("modules") or {}
    top = design if design else (next(iter(modules.values())) if modules else {})
    cells = top.get("num_cells", top.get("cells"))
    out = {
        "cells": cells,
        "wires": top.get("num_wires"),
        "wire_bits": top.get("num_wire_bits"),
        "cell_types": top.get("num_cells_by_type") or {},
    }
    return {k: v for k, v in out.items() if v not in (None, {})}


def nextpnr_report(report_json: str) -> dict:
    """Fmax per clock and utilisation from nextpnr's ``--report``."""
    try:
        data = json.loads(report_json)
    except ValueError:
        return {}
    out: dict = {"fmax": {}, "utilization": {}}
    for clock, v in (data.get("fmax") or {}).items():
        out["fmax"][clock] = {"achieved_mhz": round(float(v.get("achieved", 0)), 2), "constraint_mhz": round(float(v.get("constraint", 0)), 2)}
    for kind, v in (data.get("utilization") or {}).items():
        if v.get("used"):
            out["utilization"][kind] = {"used": v.get("used"), "available": v.get("available")}
    return out


_MEAS = re.compile(r"^\s*(?P<name>[A-Za-z_][\w]*)\s*=\s*(?P<value>[-+0-9.eE]+)")


def spice_measures(lines: Iterable[str]) -> dict:
    """``name = value`` lines that ngspice prints for .meas / meas."""
    out = {}
    for line in lines:
        m = _MEAS.match(line)
        if m:
            try:
                out[m["name"].lower()] = float(m["value"])
            except ValueError:
                pass
    return out
