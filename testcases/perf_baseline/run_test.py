"""Baselines (blueprint §12, performance: measured, not promised): the co-editing delay between two
browsers, catching up after a dropped connection, queue waits with more runs than may run at once,
every artifact's SHA-256 on download, and the same FPGA build twice. Writes perf.json, with this
machine's CPU, memory and Docker, to OUTPUT_DIR."""

import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import _EDITOR, BACKEND_URL, OUTPUT_DIR, backend_get, editor_text, finish, launch, log, new_page, new_project, open_project, wait_for  # noqa: E402

KEYSTROKES = 40
DROPS = 5
QUEUED = 6


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BACKEND_URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def wait_runs(token: str, ids: list[str], timeout: float = 600) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        runs = [api("GET", f"/api/runs/{i}", token)["run"] for i in ids]
        if all(r["status"] in ("SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT") for r in runs):
            return runs
        time.sleep(0.5)
    raise AssertionError("the runs didn't end")


def spread(values: list[float]) -> dict:
    values = sorted(values)
    return {"n": len(values), "median": round(statistics.median(values), 1), "p95": round(values[max(0, round(0.95 * len(values)) - 1)], 1),
            "min": round(values[0], 1), "max": round(values[-1], 1)}


def machine() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version(), "cpus": os.cpu_count()}
    try:
        info["memory_gb"] = round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30, 1)
    except (OSError, ValueError):
        pass
    try:
        d = json.loads(subprocess.run(["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True, timeout=30).stdout)
        info["docker"] = {"server": d.get("ServerVersion"), "os": d.get("OperatingSystem"), "cpus": d.get("NCPU"), "memory_gb": round(d.get("MemTotal", 0) / 2**30, 1)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return info


errors: list[str] = []
results: dict = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "machine": machine(), "base_url": os.environ.get("BASE_URL", "")}
with sync_playwright() as pw:
    browser = launch(pw)
    a = new_page(browser, errors, "A")
    b = new_page(browser, errors, "B")
    pid = new_project(a, "Perf")
    open_project(b, pid)
    wait_for(lambda: a.evaluate(f"() => !{_EDITOR}.getOption(monaco.editor.EditorOption.readOnly)"), "A's editor is writable")

    # 1. Co-editing delay: A's edit (Monaco → Yjs → relay → Yjs → Monaco) until B's editor has it,
    # both stamped with the same clock (two tabs of one browser).
    b.evaluate(f"""() => {{ const e = {_EDITOR}; window.__seen = {{}};
        e.getModel().onDidChangeContent(() => {{ const now = Date.now();
            for (const m of (e.getModel().getValue().match(/@p\\d+@/g) || [])) if (!(m in window.__seen)) window.__seen[m] = now; }}); }}""")
    delays = []
    for i in range(KEYSTROKES):
        mark = f"@p{i}@"
        sent = a.evaluate(f"""(m) => {{ const e = {_EDITOR}; const model = e.getModel(); const end = model.getPositionAt(model.getValueLength());
            const t = Date.now(); e.executeEdits('perf', [{{ range: new monaco.Range(end.lineNumber, end.column, end.lineNumber, end.column), text: m }}]); return t; }}""", mark)
        b.wait_for_function("(m) => window.__seen && (m in window.__seen)", arg=mark, timeout=10000)
        delays.append(b.evaluate("(m) => window.__seen[m]", mark) - sent)
        time.sleep(0.05)
    results["coedit_delay_ms"] = spread(delays)
    log("co-editing delay (ms):", results["coedit_delay_ms"])

    # 2. A dropped connection: B is cut off for 3 s while both type; after it reconnects, how long
    # until both editors hold the same text with both edits.
    converge, ok = [], 0
    for k in range(DROPS):
        b.evaluate("() => window._chipYjs.provider.disconnect()")
        a.evaluate(f"(m) => {{ const e = {_EDITOR}; const model = e.getModel(); e.executeEdits('perf', [{{ range: new monaco.Range(1, 1, 1, 1), text: m }}]); }}", f"//a{k}\n")
        b.evaluate(f"(m) => {{ const e = {_EDITOR}; const model = e.getModel(); const end = model.getPositionAt(model.getValueLength());"
                   f" e.executeEdits('perf', [{{ range: new monaco.Range(end.lineNumber, end.column, end.lineNumber, end.column), text: m }}]); }}", f"\n//b{k}")
        time.sleep(3)
        t = time.time()
        b.evaluate("() => window._chipYjs.provider.connect()")
        try:
            wait_for(lambda: (ta := editor_text(a)) == editor_text(b) and f"//a{k}" in ta and f"//b{k}" in ta, "both edits everywhere", 20)
            converge.append((time.time() - t) * 1000)
            ok += 1
        except AssertionError as e:
            errors.append(f"drop {k}: {e}")
    results["reconnect"] = {"drops": DROPS, "converged": ok, "converge_ms": spread(converge) if converge else None, "offline_s": 3}
    log("after a 3 s drop:", results["reconnect"])
    b.close()

    # The rest goes through the REST API, as a script would.
    from chipova.services import api as chipova_api  # noqa: E402 — the app's own signing, with its secret
    from chipova.services.actors import Actor  # noqa: E402

    token = chipova_api.make_token(Actor("perf@example.com", "Perf", email="perf@example.com"))

    # 3. Queue waits: more lint runs at once than may run (CHIPOVA_MAX_PARALLEL_RUNS, 2).
    ids = [api("POST", f"/api/projects/{pid}/runs", token, {"flow_id": "rtl_lint"})["run"]["id"] for _ in range(QUEUED)]
    runs = wait_runs(token, ids)
    assert all(r["status"] == "SUCCEEDED" for r in runs), [r["status"] for r in runs]
    waits = [(r["started_at"] - r["queued_at"]) * 1000 for r in runs]
    lengths = [(r["ended_at"] - r["started_at"]) * 1000 for r in runs]
    overlap = max(sum(1 for o in runs if o["started_at"] <= r["started_at"] < o["ended_at"]) for r in runs)
    results["queue"] = {"runs": QUEUED, "flow": "rtl_lint", "wait_ms": spread(waits), "run_ms": spread(lengths), "most_at_once": overlap}
    log("queue:", results["queue"])

    # 4. Every artifact of a simulation downloads with the SHA-256 recorded for it.
    sim = api("POST", f"/api/projects/{pid}/runs", token, {"flow_id": "rtl_sim"})["run"]["id"]
    assert wait_runs(token, [sim])[0]["status"] == "SUCCEEDED"
    arts = api("GET", f"/api/runs/{sim}/artifacts", token)["artifacts"]
    same = 0
    for x in arts:
        code, data = backend_get(x["download_url"])
        same += code == 200 and hashlib.sha256(data).hexdigest() == x["artifact"]["sha256"]
    results["artifact_integrity"] = {"artifacts": len(arts), "sha256_match": same}
    log("artifacts:", results["artifact_integrity"])
    assert same == len(arts) > 0

    # 5. The same FPGA build twice, on the same snapshot.
    fpga = api("POST", "/api/projects", token, {"title": "Perf FPGA", "template": "fpga_blinky"})["id"]
    twice = [api("POST", f"/api/projects/{fpga}/runs", token, {"flow_id": "fpga_ice40"})["run"]["id"] for _ in range(2)]
    done = wait_runs(token, twice)
    assert all(r["status"] == "SUCCEEDED" for r in done), [r["error"] for r in done]
    shas = [{x["artifact"]["name"]: x["artifact"]["sha256"] for x in api("GET", f"/api/runs/{i}/artifacts", token)["artifacts"]} for i in twice]
    outputs = sorted(n for n in shas[0] if not n.startswith("steps/"))
    results["fpga_twice"] = {
        "same_snapshot": done[0]["revision_id"] == done[1]["revision_id"],
        "bitstream_identical": shas[0].get("fpga/blinky.bin") == shas[1].get("fpga/blinky.bin"),
        "outputs_identical": [n for n in outputs if shas[0][n] == shas[1].get(n)],
        "outputs_differing": [n for n in outputs if shas[0][n] != shas[1].get(n)],
        "run_s": [round(r["ended_at"] - r["started_at"], 1) for r in done],
    }
    log("FPGA twice:", results["fpga_twice"])
    browser.close()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "perf.json").write_text(json.dumps(results, indent=1))
log("machine:", results["machine"])
finish(errors)
