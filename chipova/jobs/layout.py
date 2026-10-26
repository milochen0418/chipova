"""Pictures of layouts (GDS/OASIS) at any zoom, drawn by KLayout's Python module.

The page's layout viewer (assets/chipova/layout.js) asks for the window it shows; a separate
process (:mod:`chipova.jobs.layout_worker`) draws it with ``klayout.lay.LayoutView``, the real
KLayout renderer (in the PDK's layer colours when the run kept its ``.lyp``), keeping the last
few layouts loaded. A render that hangs or crashes the worker costs one picture: the worker is
started again with the next one.

These pictures are a preview for looking and talking about a layout. They are not a DRC or LVS
result.
"""

from __future__ import annotations

import json
import select
import struct
import subprocess
import sys
import threading
from pathlib import Path

TIMEOUT = 30.0
WORKER = Path(__file__).with_name("layout_worker.py")


class _Renderer:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None

    def _start(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def _stop(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(5)
            except Exception:  # noqa: BLE001
                pass
        self.proc = None

    def _read(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            ready, _, _ = select.select([self.proc.stdout], [], [], TIMEOUT)  # type: ignore[union-attr]
            if not ready:
                raise TimeoutError
            chunk = self.proc.stdout.read1(n - len(out))  # type: ignore[union-attr]
            if not chunk:
                raise EOFError
            out += chunk
        return out

    def ask(self, req: dict) -> tuple[dict, bytes]:
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            try:
                data = json.dumps(req).encode()
                self.proc.stdin.write(struct.pack(">I", len(data)) + data)  # type: ignore[union-attr]
                self.proc.stdin.flush()  # type: ignore[union-attr]
                (n,) = struct.unpack(">I", self._read(4))
                body = json.loads(self._read(n))
                extra = self._read(body["png"]) if body.get("ok") and isinstance(body.get("png"), int) else b""
                return body, extra
            except TimeoutError:
                self._stop()
                return {"ok": False, "error": "the layout took too long to draw"}, b""
            except (EOFError, OSError, ValueError) as e:
                self._stop()
                return {"ok": False, "error": f"the layout renderer stopped: {e}"}, b""

    def close(self) -> None:
        with self.lock:
            self._stop()


renderer = _Renderer()


def info(path: Path, lyp: Path | None = None) -> dict:
    body, _ = renderer.ask({"op": "info", "path": str(path), "lyp": str(lyp or "")})
    return body


def picture(path: Path, box: tuple[float, float, float, float], w: int, h: int, hidden: list[str], lyp: Path | None = None) -> tuple[dict, bytes]:
    w = max(16, min(int(w), 4096))
    h = max(16, min(int(h), 4096))
    return renderer.ask({"op": "png", "path": str(path), "lyp": str(lyp or ""), "box": list(box), "w": w, "h": h, "hidden": hidden})
