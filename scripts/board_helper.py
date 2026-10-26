#!/usr/bin/env python3
"""Chipova's board helper: programs FPGA boards plugged into this computer with the bitstreams of
Chipova runs, when you ask for it in Chipova (a run's "Program a board…").

    python3 board_helper.py --url https://chipova.reflex-ddns.com --token chv1.… --name "Bench Mac"

- It needs openFPGALoader (https://trabucayre.github.io/openFPGALoader/; macOS:
  ``brew install openfpgaloader``; Debian/Ubuntu: ``sudo apt install openfpgaloader``).
- The token is your own API token (a project's Agents page → Make an API token): only you can send
  this helper work, and only for projects you may run.
- Every bitstream is checked against the SHA-256 Chipova recorded for it before anything is
  written to a board. ``--dry-run`` checks everything but doesn't run openFPGALoader.
- ``--url`` is Chipova's backend (behind re-ddns: the app's own address; a local run: its backend
  port, e.g. http://localhost:8000). ``--cafile`` trusts a private CA (re-ddns's), ``--insecure``
  skips the TLS check.

Standard library only; stop it with Ctrl-C.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BOARD = re.compile(r"^[A-Za-z0-9_]{1,40}$")
SUFFIX = re.compile(r"\.(bin|bit|fs|svf|jed)$")
HELLO_EVERY = 20.0


def log(*args) -> None:  # noqa: ANN002
    print(time.strftime("%H:%M:%S"), *args, flush=True)


class Chipova:
    def __init__(self, args: argparse.Namespace) -> None:
        self.base = args.url.rstrip("/")
        self.token = args.token
        if args.insecure:
            self.ssl = ssl._create_unverified_context()  # noqa: S323 — asked for
        else:
            self.ssl = ssl.create_default_context(cafile=args.cafile) if args.cafile else ssl.create_default_context()

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        req = urllib.request.Request(
            self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout, context=self.ssl) as r:  # noqa: S310 — the user's own server
            return json.loads(r.read() or b"{}")

    def download(self, path: str) -> bytes:
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=300, context=self.ssl) as r:  # noqa: S310
            return r.read()


def loader_version(loader: str) -> str:
    try:
        out = subprocess.run([loader, "--Version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(not found: {e})"
    return ((out.stdout or out.stderr).strip().splitlines() or [""])[0][:200]


def scan(loader: str) -> list[str]:
    """What openFPGALoader sees on USB (cables and boards), as it prints it."""
    try:
        out = subprocess.run([loader, "--scan-usb"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"(scan failed: {e})"]
    return [line.strip() for line in (out.stdout + out.stderr).splitlines() if line.strip()][:20]


def program(chipova: Chipova, args: argparse.Namespace, job: dict) -> tuple[str, str]:
    """Fetches and checks the bitstream, then programs the board: (status, log)."""
    board, name = job.get("board", ""), job.get("name", "")
    if not BOARD.match(board):
        return "FAILED", f"refused: {board!r} is not a board name"
    data = chipova.download(job["url"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != job.get("sha256"):
        return "FAILED", f"refused: the bitstream's SHA-256 is {digest}, Chipova recorded {job.get('sha256')}"
    checked = f"{name}: {len(data)} bytes, SHA-256 {digest} matches"
    if args.dry_run:
        return "DONE", f"{checked}\ndry run: openFPGALoader -b {board} not run"
    m = SUFFIX.search(name)
    suffix = m.group(0) if m else ".bin"
    with tempfile.TemporaryDirectory(prefix="chipova-board-") as tmp:
        path = os.path.join(tmp, "bitstream" + suffix)
        with open(path, "wb") as fh:
            fh.write(data)
        cmd = [args.loader, "-b", board, path]
        log("running", " ".join(cmd))
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            return "FAILED", f"{checked}\n{' '.join(cmd)}: {e}"
    text = (out.stdout + out.stderr).strip()
    return ("DONE" if out.returncode == 0 else "FAILED"), f"{checked}\n$ openFPGALoader -b {board} …\n{text[-8000:]}\nexit code {out.returncode}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Chipova's backend address")
    ap.add_argument("--token", default=os.environ.get("CHIPOVA_TOKEN", ""), help="your API token (or CHIPOVA_TOKEN)")
    ap.add_argument("--name", default=socket.gethostname(), help="what Chipova calls this helper")
    ap.add_argument("--loader", default="openFPGALoader", help="the openFPGALoader program")
    ap.add_argument("--dry-run", action="store_true", help="check bitstreams, don't program")
    ap.add_argument("--cafile", default="", help="a CA certificate to trust")
    ap.add_argument("--insecure", action="store_true", help="don't check the server's certificate")
    ap.add_argument("--once", action="store_true", help="handle one job, then stop (for tests)")
    args = ap.parse_args(argv)
    if not args.token:
        ap.error("give --token (or CHIPOVA_TOKEN)")
    chipova = Chipova(args)
    version = "dry run" if args.dry_run else loader_version(args.loader)
    helper_id, last_hello = "", 0.0
    log(f"board helper “{args.name}” for {chipova.base}; openFPGALoader: {version}")
    while True:
        try:
            if time.time() - last_hello > HELLO_EVERY:
                boards = [] if args.dry_run else scan(args.loader)
                helper_id = chipova.call("POST", "/api/boards/hello", {"name": args.name, "boards": boards, "loader": version})["id"]
                last_hello = time.time()
            work = chipova.call("GET", f"/api/boards/next?helper={helper_id}&wait=25", timeout=60).get("job")
            if not work:
                continue
            log(f"job {work['job']}: {work['board']} ← {work['name']} of {work['run']} ({work['project']})")
            chipova.call("POST", f"/api/boards/jobs/{work['job']}", {"status": "PROGRAMMING", "log": ""})
            try:
                status, text = program(chipova, args, work)
            except (OSError, urllib.error.URLError) as e:
                status, text = "FAILED", f"couldn't fetch the bitstream: {e}"
            chipova.call("POST", f"/api/boards/jobs/{work['job']}", {"status": status, "log": text})
            log(f"job {work['job']}: {status}")
            if args.once:
                return 0 if status == "DONE" else 1
        except urllib.error.HTTPError as e:
            log(f"Chipova said {e.code}: {e.read()[:300]!r}")
            if e.code in (401, 403):
                return 2
            time.sleep(5)
        except (urllib.error.URLError, OSError) as e:
            log(f"can't reach Chipova ({e}); trying again in 5 s")
            time.sleep(5)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
