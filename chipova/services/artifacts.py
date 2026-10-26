"""What runs leave behind, and getting at it from a browser.

An artifact is a file in a run's ``out`` folder, recorded with its SHA-256 and size. A page gets
links to them that are signed for one person and one artifact and expire (:func:`link`); every
use of a link checks again that the person may still download from the project, so taking
someone's access away also stops their links. Refusals are audited (blueprint AC-09). Nothing
is ever served from a path in the URL: an artifact is found by its id, its file by its record.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from chipova import ids, paths
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import Artifact
from chipova.jobs import engine, vcd
from chipova.services import audit, projects
from chipova.services.actors import Actor

LINK_TTL = 12 * 3600
DOWNLOAD_PATH = "/_chipova/a/{artifact_id}"
WAVE_PATH = "/_chipova/wave/{artifact_id}"
LAYOUT_PATH = "/_chipova/layout/{artifact_id}"
MANIFEST_PATH = "/_chipova/manifest/{run_id}"
RELEASE_PATH = "/_chipova/release/{release_id}"
# Kinds a browser may show inline (pictures); everything else downloads.
INLINE = {".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json"}


def get(artifact_id: str) -> Artifact | None:
    if not ids.is_prefixed(artifact_id, "af"):
        return None
    row = db().one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
    return Artifact.from_row(row) if row else None


def file_of(a: Artifact) -> Path:
    run = engine.get(a.run_id)
    base = paths.run_dir(a.project_id, a.run_id) / "out"
    target = (base / a.name).resolve()
    if run is None or base.resolve() not in target.parents:
        raise FileNotFoundError(a.name)
    return target


def _sign(artifact_id: str, user: str, exp: int) -> str:
    msg = f"{artifact_id}|{user}|{exp}".encode()
    return base64.urlsafe_b64encode(hmac.new(paths.secret(), msg, hashlib.sha256).digest()[:18]).decode().rstrip("=")


def query(artifact_id: str, user: str, ttl: int = LINK_TTL) -> str:
    """The query string that lets ``user`` fetch the artifact (a download, waveform data)."""
    exp = int(time.time()) + ttl
    u = base64.urlsafe_b64encode(user.encode()).decode().rstrip("=")
    return f"u={u}&x={exp}&s={_sign(artifact_id, user, exp)}"


def link(artifact_id: str, user: str, ttl: int = LINK_TTL) -> str:
    return DOWNLOAD_PATH.format(artifact_id=artifact_id) + "?" + query(artifact_id, user, ttl)


def _signed_user(request: Request, key: str) -> str:
    """The person a signed link is for ("" when it isn't genuine or has expired)."""
    try:
        u = request.query_params.get("u", "")
        user = base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode()
        exp = int(request.query_params.get("x", "0"))
    except (ValueError, UnicodeDecodeError):
        return ""
    sig = request.query_params.get("s", "")
    if not user or exp < time.time() or not hmac.compare_digest(sig, _sign(key, user, exp)):
        return ""
    return user


def _check(request: Request, artifact_id: str) -> tuple[Artifact, str] | Response:
    a = get(artifact_id)
    try:
        u = request.query_params.get("u", "")
        user = base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode()
        exp = int(request.query_params.get("x", "0"))
    except (ValueError, UnicodeDecodeError):
        user, exp = "", 0
    sig = request.query_params.get("s", "")
    if a is None:
        return JSONResponse({"error": "no such artifact"}, status_code=404)
    if not user or exp < time.time() or not hmac.compare_digest(sig, _sign(artifact_id, user, exp)):
        audit.denied("artifact.read", Actor(user or "anonymous", user or "anonymous"), a.project_id, artifact_id, "invalid or expired link")
        return JSONResponse({"error": "this link is invalid or has expired: open it again from the project"}, status_code=403)
    access = projects.access(a.project_id, user)
    if access is None or not access.can(roles.DOWNLOAD):
        audit.denied("artifact.read", Actor(user, user), a.project_id, artifact_id, "no access to the project")
        return JSONResponse({"error": "you have no access to this project"}, status_code=403)
    return a, user


async def download(request: Request) -> Response:
    checked = _check(request, request.path_params.get("artifact_id", ""))
    if isinstance(checked, Response):
        return checked
    a, user = checked
    try:
        path = file_of(a)
    except FileNotFoundError:
        return JSONResponse({"error": "the file is gone"}, status_code=410)
    audit.record("artifact.download", Actor(user, user), a.project_id, a.id, {"name": a.name})
    name = Path(a.name).name
    inline = request.query_params.get("inline") == "1" and path.suffix in INLINE
    headers = {
        "X-Content-Type-Options": "nosniff",
        # Never run anything an artifact holds (an SVG's scripts, say).
        "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
        "X-Chipova-SHA256": a.sha256,
    }
    if inline:
        return FileResponse(path, media_type=INLINE[path.suffix], headers=headers)
    return FileResponse(path, filename=name, headers=headers)


async def wave(request: Request) -> Response:
    """Waveform data for the viewer: ``op=meta`` (signals) or ``op=window&codes=a,b&t0=&t1=``."""
    checked = _check(request, request.path_params.get("artifact_id", ""))
    if isinstance(checked, Response):
        return checked
    a, _ = checked
    if a.kind != "vcd":
        return JSONResponse({"error": "not a waveform"}, status_code=400)
    try:
        import asyncio

        w = await asyncio.to_thread(vcd.load, file_of(a))
    except (OSError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    if request.query_params.get("op", "meta") == "meta":
        return JSONResponse(vcd.meta(w))
    try:
        t0 = int(float(request.query_params.get("t0", "0")))
        t1 = int(float(request.query_params.get("t1", str(w.end))))
    except ValueError:
        return JSONResponse({"error": "t0 and t1 are times"}, status_code=400)
    codes = [c for c in request.query_params.get("codes", "").split(",") if c]
    return JSONResponse(vcd.window(w, codes, t0, t1))


async def layout_view(request: Request) -> Response:
    """A layout artifact: ``op=info`` (top cell, size, layers, cells) or a picture of a window
    (``x0, y0, x1, y1`` in µm, ``w``, ``h``, ``hide=66/20,68/20``)."""
    import asyncio

    from chipova.jobs import layout

    checked = _check(request, request.path_params.get("artifact_id", ""))
    if isinstance(checked, Response):
        return checked
    a, _ = checked
    if a.kind not in ("gds", "oas"):
        return JSONResponse({"error": "not a layout"}, status_code=400)
    try:
        path = file_of(a)
    except FileNotFoundError:
        return JSONResponse({"error": "the file is gone"}, status_code=410)
    lyp = next((x for x in engine.artifacts_of(a.run_id) if x.name.endswith(".lyp")), None)
    lyp_path = file_of(lyp) if lyp is not None else None
    q = request.query_params
    if q.get("op", "info") == "info":
        return JSONResponse(await asyncio.to_thread(layout.info, path, lyp_path))
    try:
        box = (float(q["x0"]), float(q["y0"]), float(q["x1"]), float(q["y1"]))
        w, h = int(q.get("w", "800")), int(q.get("h", "600"))
    except (KeyError, ValueError):
        return JSONResponse({"error": "give x0, y0, x1, y1 (µm), w and h"}, status_code=400)
    hidden = [x for x in q.get("hide", "").split(",") if x]
    body, png = await asyncio.to_thread(layout.picture, path, box, w, h, hidden, lyp_path)
    if not body.get("ok"):
        return JSONResponse(body, status_code=422)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


async def manifest(request: Request) -> Response:
    """A run's manifest.json (what went in, what came out)."""
    run_id = request.path_params.get("run_id", "")
    run = engine.get(run_id)
    user = _signed_user(request, run_id)
    if run is None:
        return JSONResponse({"error": "no such run"}, status_code=404)
    access = projects.access(run.project_id, user) if user else None
    if access is None or not access.can(roles.DOWNLOAD):
        audit.denied("manifest.read", Actor(user or "anonymous", user or "anonymous"), run.project_id, run_id, "invalid link or no access")
        return JSONResponse({"error": "no access"}, status_code=403)
    path = paths.run_dir(run.project_id, run.id) / "manifest.json"
    if not path.is_file():
        return JSONResponse({"error": "the run has no manifest yet"}, status_code=404)
    return FileResponse(path, media_type="application/json", filename=f"{run.id}-manifest.json", headers={"X-Content-Type-Options": "nosniff"})


async def release_package(request: Request) -> Response:
    """A release's tape-out preparation package (zip)."""
    from chipova.services import releases

    release_id = request.path_params.get("release_id", "")
    r = releases.get(release_id)
    user = _signed_user(request, release_id)
    if r is None:
        return JSONResponse({"error": "no such release"}, status_code=404)
    access = projects.access(r.project_id, user) if user else None
    if access is None or not access.can(roles.DOWNLOAD):
        audit.denied("release.download", Actor(user or "anonymous", user or "anonymous"), r.project_id, release_id, "invalid link or no access")
        return JSONResponse({"error": "no access"}, status_code=403)
    path = releases.package_path(r)
    if not path.is_file():
        return JSONResponse({"error": "build the package first"}, status_code=404)
    audit.record("release.download", Actor(user, user), r.project_id, release_id)
    return FileResponse(path, media_type="application/zip", filename=f"{r.id}-tapeout-preparation.zip", headers={"X-Chipova-SHA256": r.package_artifact})


def verify(a: Artifact) -> bool:
    """Whether the file still has the SHA-256 recorded when its run ended."""
    try:
        h = hashlib.sha256()
        with open(file_of(a), "rb") as fh:
            while chunk := fh.read(1 << 20):
                h.update(chunk)
        return h.hexdigest() == a.sha256
    except OSError:
        return False


def read_text(a: Artifact, limit: int = 2_000_000) -> str:
    with open(file_of(a), "rb") as fh:
        return fh.read(limit).decode("utf-8", errors="replace")


def read_json(a: Artifact) -> dict:
    try:
        return json.loads(read_text(a))
    except ValueError:
        return {}


def register_routes(app) -> None:  # noqa: ANN001 - Reflex App
    api = app._api
    have = {getattr(r, "path", None) for r in api.routes}
    if DOWNLOAD_PATH not in have:
        api.add_route(DOWNLOAD_PATH, download, methods=["GET"])
    if WAVE_PATH not in have:
        api.add_route(WAVE_PATH, wave, methods=["GET"])
    if LAYOUT_PATH not in have:
        api.add_route(LAYOUT_PATH, layout_view, methods=["GET"])
    if MANIFEST_PATH not in have:
        api.add_route(MANIFEST_PATH, manifest, methods=["GET"])
    if RELEASE_PATH not in have:
        api.add_route(RELEASE_PATH, release_package, methods=["GET"])
