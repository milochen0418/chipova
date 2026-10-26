"""Runs a job's steps inside its container (Chipova copies this file in as /work/runner.py).

Python's standard library only: it runs in every EDA image. It reads /work/job.json, written by
the app from an allowed flow:

    {"run": "run-…", "env": {…}, "steps": [
        {"id": "lint", "title": "…", "argv": ["verilator", "--lint-only", …], "cwd": "/work/out/lint",
         "env": {…}, "timeout": 300, "allow_fail": false}, …]}

Each step's argv runs as it is (no shell), its output goes to /work/out/steps/<id>/stdout.log
and to this script's output, between marker lines the app follows live:

    @@chipova step-start <id> <unix time>
    @@chipova step-end <id> <exit code> <seconds>
    @@chipova step-skip <id>

A step that fails (and isn't allowed to) skips the ones after it. /work/out/result.json says how
each went; the script's own exit code is 0 only when every required step succeeded.
"""

import json
import os
import subprocess
import sys
import threading
import time

OUT = "/work/out"
MARK = "@@chipova"


def mark(*parts):
    sys.stdout.write("\n" + " ".join([MARK] + [str(p) for p in parts]) + "\n")
    sys.stdout.flush()


def run_step(step, base_env):
    cwd = step.get("cwd") or OUT
    os.makedirs(cwd, exist_ok=True)
    log_dir = os.path.join(OUT, "steps", step["id"])
    os.makedirs(log_dir, exist_ok=True)
    env = dict(base_env)
    env.update(step.get("env") or {})
    started = time.time()
    mark("step-start", step["id"], round(started, 3))
    timed_out = []
    with open(os.path.join(log_dir, "stdout.log"), "wb") as log:
        try:
            proc = subprocess.Popen(
                step["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except OSError as e:
            line = ("cannot start %s: %s\n" % (step["argv"][0], e)).encode()
            log.write(line)
            sys.stdout.buffer.write(line)
            mark("step-end", step["id"], 127, round(time.time() - started, 3))
            return 127, started, time.time()

        def kill():
            timed_out.append(True)
            try:
                proc.kill()
            except OSError:
                pass

        timer = threading.Timer(float(step.get("timeout") or 3600), kill)
        timer.daemon = True
        timer.start()
        for line in proc.stdout:
            log.write(line)
            sys.stdout.buffer.write(line)
        sys.stdout.flush()
        rc = proc.wait()
        timer.cancel()
        if timed_out:
            note = ("\nstep %s stopped: it ran longer than %ss\n" % (step["id"], step.get("timeout"))).encode()
            log.write(note)
            sys.stdout.buffer.write(note)
            rc = 124
    ended = time.time()
    mark("step-end", step["id"], rc, round(ended - started, 3))
    return rc, started, ended


def main():
    with open("/work/job.json", encoding="utf-8") as fh:
        job = json.load(fh)
    os.makedirs(OUT, exist_ok=True)
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/work/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": "/work/tmp",
    }
    # What the image itself sets up for its tools (PDK_ROOT, tool paths): kept.
    for key, value in os.environ.items():
        if key not in base_env and not key.startswith(("CHIPOVA_SECRET", "DOCKER_")):
            base_env[key] = value
    base_env.update(job.get("env") or {})
    os.makedirs(base_env["HOME"], exist_ok=True)
    os.makedirs(base_env["TMPDIR"], exist_ok=True)
    results = []
    failed = False
    for step in job["steps"]:
        if failed:
            mark("step-skip", step["id"])
            results.append({"id": step["id"], "status": "SKIPPED"})
            continue
        rc, started, ended = run_step(step, base_env)
        ok = rc == 0
        results.append({
            "id": step["id"], "status": "SUCCEEDED" if ok else "FAILED", "exit_code": rc,
            "started": started, "ended": ended,
        })
        if not ok and not step.get("allow_fail"):
            failed = True
    with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as fh:
        json.dump({"run": job.get("run"), "steps": results}, fh, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
