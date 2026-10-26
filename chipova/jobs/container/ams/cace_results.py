#!/usr/bin/env python3
"""Turns one CACE 2.11 run into JSON (and one CSV table per parameter) for Chipova.

Runs inside the tool image (it needs PyYAML and CACE's own unit conversion, both there):

    python3 cace_results.py <project root> <datasheet, relative to the root> <output folder>
        [--log <the cace step's stdout log>]

What it reads, all written by CACE in <root>/runs/RUN_<timestamp>/ (the newest one):

- summary.md: CACE's own verdict, one row per spec'd result (min/typ/max and Pass/Fail/Error).
  This is copied as is into "cace_summary"; "status" is derived only from these rows.
- parameters/<name>/run_<i>/conditions.yaml and <template>_<i>.data: every simulation's
  conditions and raw values (SI units, as the simulator wrote them).
- parameters/<name>/*.png|*.svg: the plots CACE drew.
- the cace step's stdout (optional): the "Completed <parameter>: <result>" lines, the only place
  CACE prints a verdict for parameters without a spec (plot-only ones).

What it writes into <output folder>:

- cace_results.json
- cace_<parameter>.csv: one row per simulation and data row (conditions, then values), SI units.

"checks" per simulation are NOT from CACE: they apply the datasheet's limits to each single
simulation (with CACE's own unit conversion), so a reader sees which conditions broke a limit.
CACE's own verdict is per result over all conditions (minimum of the values against a minimum
limit, maximum against a maximum limit), and that is what "status" reports.

Exit code: 0 when it could read a summary, 1 when CACE left no summary (it failed early).
"""

import csv
import glob
import json
import os
import re
import sys

import yaml

STATUS_WORDS = {"pass": "PASS", "fail": "FAIL", "error": "ERROR", "skip": "SKIPPED",
                "cancel": "CANCELED", "unknown": "UNKNOWN"}


def status_of(text):
    word = (text or "").strip().split(" ")[0].lower()
    return STATUS_WORDS.get(word, (text or "").strip() or "UNKNOWN")


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def read_summary(path):
    """CACE's summary.md table, row by row (cells as CACE wrote them)."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    source = None
    for line in lines:
        m = re.match(r"\*\*netlist source\*\*:\s*(\S+)", line)
        if m:
            source = m.group(1)
    table = [ln for ln in lines if ln.startswith("|")]
    for line in table[2:]:  # header and separator first
        cells = [c.strip().replace("​", "") for c in line.strip().strip("|").split("|")]
        if len(cells) < 10:
            continue
        rows.append({
            "display": cells[0], "tool": cells[1], "result": cells[2],
            "min_limit": cells[3], "min_value": cells[4],
            "typ_target": cells[5], "typ_value": cells[6],
            "max_limit": cells[7], "max_value": cells[8],
            "status": status_of(cells[9]), "status_text": cells[9],
        })
    return source, rows


def read_completed(log_path):
    """{parameter display name: status} from the 'Completed X: Pass ✅' lines CACE prints."""
    done = {}
    if not log_path or not os.path.isfile(log_path):
        return done
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.search(r"Completed (.+?): (Pass|Fail|Error|Skip|Cancel|Unknown)\b", line)
            if m:
                done[m.group(1).strip()] = status_of(m.group(2))
    return done


def read_data(path, variables):
    """A CACE ascii result file, read the way CACE reads it: whitespace separated, one column
    per entry of 'variables' (None = ignored)."""
    columns = {v: [] for v in variables if v is not None}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            for i, entry in enumerate(line.split()):
                if i < len(variables) and variables[i] is not None:
                    try:
                        columns[variables[i]].append(float(entry))
                    except ValueError:
                        columns[variables[i]].append(None)
    return columns


def main(argv):
    if len(argv) < 4:
        sys.stderr.write(__doc__)
        return 2
    root, datasheet_rel, out_dir = argv[1], argv[2], argv[3]
    log_path = argv[argv.index("--log") + 1] if "--log" in argv else None
    os.makedirs(out_dir, exist_ok=True)

    from cace.common.spiceunits import spice_unit_convert  # CACE's own unit handling
    try:
        from importlib.metadata import version
        cace_version = version("cace")
    except Exception:  # noqa: BLE001
        cace_version = None

    with open(os.path.join(root, datasheet_rel), encoding="utf-8") as fh:
        sheet = yaml.safe_load(fh)
    runs_dir = os.path.join(root, (sheet.get("paths") or {}).get("runs", "runs"))
    runs = sorted(glob.glob(os.path.join(runs_dir, "RUN_*")))
    result = {
        "tool": "cace", "cace_version": cace_version, "datasheet": datasheet_rel,
        "name": sheet.get("name"), "pdk": sheet.get("PDK"), "run_dir": None,
        "netlist_source": None, "status": "NO_RESULT", "cace_summary": [], "parameters": {},
        "files": {},
    }
    if not runs:
        result["why"] = f"no CACE run folder in {runs_dir}"
        write(out_dir, result)
        return 1
    run = runs[-1]
    result["run_dir"] = os.path.relpath(run, root)
    for name in ("summary.md", "flow.log", "warning.log", "error.log"):
        if os.path.isfile(os.path.join(run, name)):
            result["files"][name] = os.path.relpath(os.path.join(run, name), root)

    summary = os.path.join(run, "summary.md")
    if os.path.isfile(summary):
        result["netlist_source"], result["cace_summary"] = read_summary(summary)
    completed = read_completed(log_path)

    statuses = []
    for pname, param in (sheet.get("parameters") or {}).items():
        display = param.get("display", pname)
        spec = param.get("spec") or {}
        tool = param.get("tool")
        toolname = tool if isinstance(tool, str) else next(iter(tool))
        cfg = {} if isinstance(tool, str) else (tool[toolname] or {})
        variables = cfg.get("variables") or []
        rows = [r for r in result["cace_summary"] if r["result"] in spec and r["display"] in
                [spec[r["result"]].get("display", display)]]
        if rows:
            order = ["ERROR", "FAIL", "UNKNOWN", "CANCELED", "SKIPPED", "PASS"]
            pstatus = min((r["status"] for r in rows), key=lambda s: order.index(s) if s in order else 0)
        else:
            pstatus = completed.get(display, "NO_SPEC" if not spec else "NOT_RUN")
        pdir = os.path.join(run, "parameters", pname)
        entry = {
            "display": display, "tool": toolname, "status": pstatus,
            "status_from": "summary.md" if rows else ("cace log" if display in completed else None),
            "spec": spec, "plots": [], "runs": [],
        }
        if os.path.isdir(pdir):
            entry["plots"] = sorted(os.path.relpath(p, root) for p in glob.glob(os.path.join(pdir, "*.png")) + glob.glob(os.path.join(pdir, "*.svg")))
            for name in ("simulation_summary.csv", "simulation_summary.md"):
                if os.path.isfile(os.path.join(pdir, name)):
                    entry.setdefault("files", {})[name] = os.path.relpath(os.path.join(pdir, name), root)
            template = cfg.get("template", "")
            stem = os.path.splitext(template)[0]
            suffix = cfg.get("suffix", ".data")
            table_rows, cond_names = [], []
            for rdir in sorted(glob.glob(os.path.join(pdir, "run_*"))):
                cfile = os.path.join(rdir, "conditions.yaml")
                if not os.path.isfile(cfile):
                    continue
                with open(cfile, encoding="utf-8") as fh:
                    conds = yaml.safe_load(fh) or {}
                n = conds.get("N")
                swept = {k: v for k, v in conds.items() if k not in
                         ("N", "simpath", "filename", "DUT_path", "DUT_name", "PDK", "PDK_ROOT",
                          "templates", "root", "netlist_source", "jobs", "include_DUT", "random")}
                data_file = os.path.join(rdir, f"{stem}_{n}{suffix}")
                values = read_data(data_file, variables) if os.path.isfile(data_file) else None
                one = {"run": os.path.basename(rdir), "conditions": swept,
                       "data_file": os.path.relpath(data_file, root) if values is not None else None}
                if values is None:
                    one["error"] = "no result file"
                elif all(len(v) <= 1 for v in values.values()):
                    one["values"] = {k: (v[0] if v else None) for k, v in values.items()}
                    checks = {}
                    for res, s in spec.items():
                        val = one["values"].get(res)
                        unit = s.get("unit") or param.get("unit")
                        for which, rule in (("minimum", "above"), ("maximum", "below")):
                            limit = (s.get(which) or {}).get("value")
                            if limit in (None, "any") or (s.get(which) or {}).get("fail") is False:
                                continue
                            lim = float(spice_unit_convert((str(unit), str(limit)))) if unit else float(limit)
                            ok = val is not None and (val >= lim if rule == "above" else val <= lim)
                            checks.setdefault(res, {})[which] = "pass" if ok else "fail"
                    one["checks"] = checks
                else:
                    one["rows"] = max(len(v) for v in values.values())
                entry["runs"].append(one)
                # table: one line per data row
                if values:
                    cond_names = cond_names or list(swept)
                    length = max((len(v) for v in values.values()), default=0)
                    for i in range(length):
                        table_rows.append([one["run"]] + [swept.get(c) for c in cond_names] +
                                          [values[k][i] if i < len(values[k]) else "" for k in values])
            if table_rows:
                names = [v for v in variables if v is not None]
                csv_path = os.path.join(out_dir, f"cace_{pname}.csv")
                with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(["run"] + cond_names + names)
                    w.writerows(table_rows)
                entry["table"] = os.path.basename(csv_path)
            failing = [r["run"] for r in entry["runs"] if any(
                v == "fail" for c in (r.get("checks") or {}).values() for v in c.values())]
            if spec:
                entry["runs_breaking_a_limit"] = failing
        result["parameters"][pname] = entry
        statuses.append(pstatus)

    if not result["cace_summary"]:
        result["status"] = "NO_RESULT"
        result["why"] = "CACE wrote no summary.md (it stopped before evaluating the parameters)"
    elif any(r["status"] == "ERROR" for r in result["cace_summary"]):
        result["status"] = "ERROR"
    elif any(r["status"] == "FAIL" for r in result["cace_summary"]):
        result["status"] = "FAIL"
    elif all(r["status"] == "PASS" for r in result["cace_summary"]):
        result["status"] = "PASS"
    else:
        result["status"] = "UNKNOWN"
    # plot-only parameters that didn't finish make the whole run an error, as CACE's exit code does
    if any(s in ("ERROR", "NOT_RUN") for s in statuses) and result["status"] == "PASS":
        result["status"] = "ERROR"
    write(out_dir, result)
    return 0 if result["cace_summary"] else 1


def write(out_dir, result):
    with open(os.path.join(out_dir, "cace_results.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
