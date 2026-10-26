"""Measurements of real chips (blueprint FLOW-POSTSILICON): OpenHTF test records, sent by a bench
computer (``POST /api/projects/{id}/lab``) or uploaded on the Lab page, kept with the snapshot the
chips were made from, and lined up with what the design said before silicon (``lab/spec.csv``),
each in its own column, never mixed.

An OpenHTF record (its JSON output, ``openhtf.output.callbacks.json_factory``) gives the chip
(``dut_id``), the station, the outcome and, per phase, measurements with their value, units, limits
(validators such as ``2.5 <= x <= 2.62``) and outcome. A record whose metadata says ``simulated``
is kept as such: it tried the way here, it measured nothing, and the comparison leaves it out.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import statistics
import time

from chipova import ids, paths
from chipova.db import db
from chipova.domain import roles
from chipova.services import audit, projects, revisions
from chipova.services.actors import Actor

SPEC = "lab/spec.csv"
MAX_RECORD = 2_000_000
_RANGE = re.compile(r"^\s*(?:(?P<lo>[-+0-9.eE]+)\s*<=\s*)?x(?:\s*<=\s*(?P<hi>[-+0-9.eE]+))?\s*$")


def parse(record: dict) -> dict:
    """The parts of an OpenHTF record Chipova keeps (the whole record is kept too)."""
    if not isinstance(record, dict) or not isinstance(record.get("phases"), list):
        raise ValueError("that is not an OpenHTF test record (its JSON output has phases)")
    measurements = []
    for phase in record["phases"]:
        for name, m in (phase.get("measurements") or {}).items():
            value = m.get("measured_value")
            low = high = None
            for v in m.get("validators") or []:
                match = _RANGE.match(str(v))
                if match:
                    low = float(match["lo"]) if match["lo"] else low
                    high = float(match["hi"]) if match["hi"] else high
            unit = m.get("units") or {}
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            measurements.append({
                "name": str(name)[:100], "phase": str(phase.get("name", ""))[:100],
                "value": float(value) if numeric else None, "text": "" if numeric else str(value)[:200],
                "outcome": str(m.get("outcome", "")), "validators": [str(v)[:100] for v in m.get("validators") or []],
                "min": low, "max": high, "unit": str(unit.get("suffix") or unit.get("name") or "")[:20],
            })
    meta = record.get("metadata") or {}
    return {
        "dut": str(record.get("dut_id") or "")[:100], "station": str(record.get("station_id") or "")[:200],
        "test": str(meta.get("test_name") or "")[:200], "outcome": str(record.get("outcome") or "")[:20],
        "simulated": bool(meta.get("simulated")),
        "started_at": float(record.get("start_time_millis") or 0) / 1000, "ended_at": float(record.get("end_time_millis") or 0) / 1000,
        "measurements": measurements,
    }


def add(project_id: str, snapshot: str, record: dict, actor: Actor) -> dict:
    """Keeps a test record of chips made from ``snapshot`` (its id or short hash; "" = the latest)."""
    projects.require(project_id, actor, roles.EDIT)
    rev = revisions.find(project_id, snapshot) if snapshot else revisions.latest(project_id)
    if rev is None:
        raise projects.NotFound(f"there is no snapshot {snapshot!r}")
    raw = json.dumps(record, separators=(",", ":")).encode()
    if len(raw) > MAX_RECORD:
        raise ValueError("the record is too big (2 MB at most)")
    p = parse(record)
    result_id = ids.new_id("lab")
    folder = paths.project_dir(project_id) / "lab"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{result_id}.json").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    row = {
        "id": result_id, "project_id": project_id, "revision_id": rev.id, "dut": p["dut"], "station": p["station"],
        "test": p["test"], "outcome": p["outcome"], "simulated": int(p["simulated"]), "started_at": p["started_at"],
        "ended_at": p["ended_at"], "measurements": json.dumps(p["measurements"]), "sha256": sha,
        "uploaded_by": actor.user, "uploaded_by_name": actor.name, "created_at": time.time(),
    }
    db().insert("lab_results", row)
    audit.record("lab.add", actor, project_id, result_id, {"dut": p["dut"], "outcome": p["outcome"], "simulated": p["simulated"], "sha256": sha})
    return result(result_id)


def result(result_id: str) -> dict | None:
    row = db().one("SELECT * FROM lab_results WHERE id = ?", (result_id,))
    return _row(row) if row else None


def results(project_id: str) -> list[dict]:
    return [_row(r) for r in db().query("SELECT * FROM lab_results WHERE project_id = ? ORDER BY created_at DESC", (project_id,))]


def _row(r) -> dict:  # noqa: ANN001
    d = dict(r)
    d["measurements"] = json.loads(d.get("measurements") or "[]")
    d["simulated"] = bool(d.get("simulated"))
    return d


def spec(project_id: str) -> list[dict]:
    """``lab/spec.csv`` of the editors' text: name, unit, min, max, pre_silicon, source."""
    try:
        text = projects.read_path(project_id, SPEC)
    except (projects.NotFound, FileNotFoundError, ValueError):
        return []
    rows = []
    for row in csv.DictReader(io.StringIO("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")))):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("name"):
            rows.append({**row, **{k: _number(row.get(k, "")) for k in ("min", "max", "pre_silicon")}})
    return rows


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def compare(project_id: str) -> list[dict]:
    """Per measurement: the spec, the design's own (pre-silicon) value, and what real chips
    measured (simulated records left out)."""
    specs = {s["name"]: s for s in spec(project_id)}
    measured: dict[str, list[dict]] = {}
    simulated: dict[str, int] = {}
    for r in results(project_id):
        for m in r["measurements"]:
            if r["simulated"]:
                simulated[m["name"]] = simulated.get(m["name"], 0) + 1
            else:
                measured.setdefault(m["name"], []).append(m)
    out = []
    for name in list(specs) + sorted(set(measured) - set(specs)):
        s, ms = specs.get(name, {}), measured.get(name, [])
        values = [m["value"] for m in ms if m["value"] is not None]
        out.append({
            "name": name, "unit": s.get("unit") or next((m["unit"] for m in ms if m["unit"]), ""),
            "min": s.get("min"), "max": s.get("max"), "pre_silicon": s.get("pre_silicon"), "source": s.get("source", ""),
            "chips": len(ms), "passed": sum(1 for m in ms if m["outcome"] == "PASS"),
            "low": min(values) if values else None, "mean": statistics.fmean(values) if values else None, "high": max(values) if values else None,
            "simulated": simulated.get(name, 0),
        })
    return out
