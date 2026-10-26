"""Xschem (and the other drawing tools of IIC-OSIC-TOOLS) in the browser, as the blueprint asks
for (§5 FLOW-AMS: "受控 noVNC／file exchange"): a desktop container of the tool image holding a
copy of the project's files, shown in the page through Chipova, for the person who opened it.
What they draw goes back to the project when they say so (Save), as their own edits.

- One desktop per person and project. It runs as user 1000, with a VNC password of its own,
  limited CPU, memory and processes. Inside the App Store it is on an internal Docker network
  that only Chipova's own container joins (no internet); run on a computer of its own, its ports
  are published on 127.0.0.1 only.
- Only someone who may edit the project opens one, and only they reach it: every request to
  ``/_chipova/desktop/<id>/<ticket>/…`` carries a ticket signed for them, and their access is
  checked again. Chipova serves noVNC's files from the desktop and bridges noVNC's WebSocket
  straight to the desktop's VNC server.
- Save never overwrites someone else's work: a file that changed in the project since it was
  copied into the desktop (and differs from the desktop's) is left alone and named.
- A desktop nobody has looked at for IDLE seconds is stopped; one a restart left running is
  picked up again.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import secrets
import socket
import tarfile
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from docker.errors import APIError, NotFound
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from chipova import ids, paths
from chipova.domain import roles
from chipova.jobs import docker_runner, profiles
from chipova.jobs.flows import OSIC
from chipova.services import audit, projects
from chipova.services.actors import Actor

logger = logging.getLogger(__name__)

LABEL = "chipova.desktop"
NETWORK = "chipova-desktops"
DESIGNS = "/foss/designs"
NOVNC, VNC = 6080, 5901
IDLE = 20 * 60
START_WAIT = 60.0
HTTP_PATH = "/_chipova/desktop/{sid}/{ticket}/{path:path}"
WS_PATH = "/_chipova/desktop/{sid}/{ticket}/websockify"
MAX_TEXT = 2_000_000
# The PDK names open_pdks gives the PDKs of the registry (what Xschem's setup reads from $PDK).
PDK_DIRS = {"skywater130": "sky130A", "ihp130": "ihp-sg13g2", "gf180": "gf180mcuD"}


@dataclass
class Desktop:
    id: str
    project_id: str
    user: str
    container: str
    password: str
    http: str  # where noVNC's files are (http://host:port)
    vnc: tuple[str, int]  # the VNC server
    base: dict[str, str] = field(default_factory=dict)  # path -> SHA-256 of the text copied in
    started: float = 0.0
    last_seen: float = 0.0
    viewers: int = 0


_desktops: dict[str, Desktop] = {}
_lock = threading.Lock()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pack(base: dict[str, str]) -> str:
    """The files' hashes as copied in, kept in a label (so a restart still knows them)."""
    return base64.b64encode(zlib.compress(json.dumps(base, separators=(",", ":")).encode())).decode()


def _unpack(text: str) -> dict[str, str]:
    try:
        return json.loads(zlib.decompress(base64.b64decode(text)))
    except (ValueError, zlib.error):
        return {}


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


# ------------------------------------------------------------ tickets


def ticket(sid: str, user: str, ttl: int = 12 * 3600) -> str:
    exp = int(time.time()) + ttl
    u = base64.urlsafe_b64encode(user.encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(paths.secret(), f"desktop|{sid}|{user}|{exp}".encode(), hashlib.sha256).digest()[:18]).decode()
    return f"{exp}.{u}.{sig}"


def _ticket_user(sid: str, value: str) -> str:
    try:
        exp, u, sig = value.split(".")
        user = base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode()
        if int(exp) < time.time():
            return ""
    except (ValueError, UnicodeDecodeError):
        return ""
    want = base64.urlsafe_b64encode(hmac.new(paths.secret(), f"desktop|{sid}|{user}|{exp}".encode(), hashlib.sha256).digest()[:18]).decode()
    return user if hmac.compare_digest(sig, want) else ""


def _allowed(sid: str, value: str) -> Desktop | None:
    """The desktop, when the ticket is genuine, its person's and they may still edit."""
    d = _desktops.get(sid)
    user = _ticket_user(sid, value)
    if d is None or not user or user != d.user:
        return None
    access = projects.access(d.project_id, user)
    if access is None or not access.can(roles.EDIT):
        return None
    d.last_seen = time.time()
    return d


# ------------------------------------------------------------ starting and stopping


def _files_tar(project_id: str, folder: str) -> tuple[bytes, dict[str, str]]:
    """The project's files under ``folder``, every folder the desktop's user's (to save in)."""
    files = projects.working_copy(project_id)
    folders = {folder}
    for path in files:
        parent = Path(path).parent
        while str(parent) != ".":
            folders.add(f"{folder}/{parent}")
            parent = parent.parent
    buf, base = io.BytesIO(), {}
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for d in sorted(folders):
            info = tarfile.TarInfo(d.lstrip("/"))
            info.type, info.mode, info.uid, info.gid = tarfile.DIRTYPE, 0o755, 1000, 1000
            tar.addfile(info)
        for path, text in sorted(files.items()):
            data = text.encode()
            info = tarfile.TarInfo(f"{folder}/{path}".lstrip("/"))
            info.size, info.mode, info.uid, info.gid, info.mtime = len(data), 0o644, 1000, 1000, time.time()
            tar.addfile(info, io.BytesIO(data))
            base[path] = _sha(text)
    return buf.getvalue(), base


def _network(c) -> str:  # noqa: ANN001 — docker client
    """The internal network desktops are on, with Chipova's own container on it too."""
    try:
        net = c.networks.get(NETWORK)
    except NotFound:
        net = c.networks.create(NETWORK, driver="bridge", internal=True, labels={LABEL: "network"})
    me = c.containers.get(socket.gethostname())
    if me.id not in (net.attrs.get("Containers") or {}):
        try:
            net.connect(me)
        except APIError as e:
            if "already exists" not in str(e):
                raise
    return NETWORK


def _image() -> str:
    profile = profiles.get(OSIC)
    if profile is None or profiles.installed(profile) is None:
        raise ValueError("Xschem's desktop needs the IIC-OSIC-TOOLS tool image: install it on Tools & settings")
    return profile.image


def start(project_id: str, actor: Actor, pdk: str = "") -> Desktop:
    """The person's desktop on the project (a running one, or a new one): blocking, for a thread."""
    if actor.is_agent:
        raise projects.Denied("An AI agent may not open a desktop")
    projects.require(project_id, actor, roles.EDIT)
    running = of(project_id, actor.user)
    if running is not None:
        try:
            if docker_runner.client().containers.get(running.container).status == "running":
                return running
        except NotFound:
            pass
        with _lock:
            _desktops.pop(running.id, None)
    c = docker_runner.client()
    image = _image()
    sid = ids.new_id("dt")
    password = secrets.token_urlsafe(6)[:8]  # VNC passwords are at most 8 characters
    folder = f"{DESIGNS}/{project_id}"
    workspace, base = _files_tar(project_id, folder)
    internal = _in_container()
    kwargs = {"network": _network(c)} if internal else {"ports": {f"{NOVNC}/tcp": ("127.0.0.1", None), f"{VNC}/tcp": ("127.0.0.1", None)}}
    container = c.containers.create(
        image,
        entrypoint=["/dockerstartup/scripts/ui_startup.sh"],
        command=["--vnc", "--wait"],
        name=f"chipova-desktop-{sid}",
        user="1000:1000",
        working_dir=folder,
        environment={
            "NO_VNC_PORT": str(NOVNC), "VNC_PW": password, "VNC_RESOLUTION": "1600x1000", "IIC_OSIC_TOOLS_QUIET": "1",
            "PDK_ROOT": "/foss/pdks", "PDK": PDK_DIRS.get(pdk, "sky130A"),
        },
        labels={LABEL: sid, docker_runner.LABEL_PROJECT: project_id, "chipova.user": actor.user, "chipova.vnc": password,
                "chipova.base": _pack(base)},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        nano_cpus=int(2 * 1e9),
        mem_limit="2048m",
        pids_limit=2048,
        detach=True,
        **kwargs,
    )
    try:
        if not container.put_archive("/", workspace):
            raise RuntimeError("cannot copy the project's files into the desktop")
        container.start()
        d = _adopt(container)
        _wait_ready(d)
    except Exception:
        container.remove(force=True)
        raise
    audit.record("desktop.open", actor, project_id, sid, {"image": image})
    return d


def _adopt(container) -> Desktop:  # noqa: ANN001
    """A desktop's record from its container (one just started, or one a restart left)."""
    container.reload()
    labels = container.labels
    sid = labels[LABEL]
    if _in_container():
        http, vnc = f"http://{container.name}:{NOVNC}", (container.name, VNC)
    else:
        ports = container.attrs["NetworkSettings"]["Ports"]
        http = f"http://127.0.0.1:{ports[f'{NOVNC}/tcp'][0]['HostPort']}"
        vnc = ("127.0.0.1", int(ports[f"{VNC}/tcp"][0]["HostPort"]))
    base = _unpack(labels.get("chipova.base", ""))
    now = time.time()
    d = Desktop(sid, labels.get(docker_runner.LABEL_PROJECT, ""), labels.get("chipova.user", ""), container.name, labels.get("chipova.vnc", ""),
                http, vnc, base, now, now)
    with _lock:
        _desktops[sid] = d
    return d


def _wait_ready(d: Desktop) -> None:
    end = time.time() + START_WAIT
    while time.time() < end:
        try:
            if httpx.get(f"{d.http}/vnc.html", timeout=2).status_code == 200:
                with socket.create_connection(d.vnc, timeout=2):
                    return
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError("the desktop didn't come up in time")


def open_file(sid: str, actor: Actor, path: str) -> None:
    """Opens one of the project's files in Xschem on the desktop."""
    d = _own(sid, actor)
    folder, _, name = ids.clean_path(path).rpartition("/")
    # From the file's own folder: Xschem reads the xschemrc there (the project's symbols, the
    # PDK); PWD as a shell would set it (IHP's xschemrc reads it).
    workdir = f"{DESIGNS}/{d.project_id}" + (f"/{folder}" if folder else "")
    container = docker_runner.client().containers.get(d.container)
    container.exec_run(["xschem", name], user="1000:1000", workdir=workdir, environment={"DISPLAY": ":1", "PWD": workdir}, detach=True)


def _own(sid: str, actor: Actor) -> Desktop:
    d = _desktops.get(sid)
    if d is None or d.user != actor.user:
        raise projects.NotFound("no such desktop of yours")
    projects.require(d.project_id, actor, roles.EDIT)
    return d


def of(project_id: str, user: str) -> Desktop | None:
    return next((d for d in _desktops.values() if d.project_id == project_id and d.user == user), None)


def fetch(sid: str, actor: Actor) -> tuple[dict[str, str], list[str]]:
    """The desktop's text files ({path: text}) and those it can't give back (too big, not
    text): blocking, for a thread."""
    d = _own(sid, actor)
    container = docker_runner.client().containers.get(d.container)
    stream, _ = container.get_archive(f"{DESIGNS}/{d.project_id}")
    files, skipped = {}, []
    with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            try:
                path = ids.clean_path(member.name.split("/", 1)[1] if "/" in member.name else "")
            except ValueError:
                continue
            if member.size > MAX_TEXT:
                skipped.append(path)
                continue
            try:
                files[path] = tar.extractfile(member).read().decode("utf-8")  # type: ignore[union-attr]
            except UnicodeDecodeError:
                skipped.append(path)
    return files, skipped


def save(sid: str, actor: Actor, files: dict[str, str], skipped: list[str]) -> dict:
    """Puts the desktop's files (from :func:`fetch`) into the project, as the person's edits:
    changed ones written, new ones added; one also changed in the project meanwhile is left
    alone. Runs on the event loop: the co-edited documents change with it."""
    d = _own(sid, actor)
    changed, added, conflicts = [], [], []
    for path, text in sorted(files.items()):
        entry = projects.file_by_path(d.project_id, path)
        if entry is None:
            projects.add_file(d.project_id, path, text, actor)
            added.append(path)
            d.base[path] = _sha(text)
            continue
        now = projects.read(d.project_id, entry.id)
        if now == text or _sha(text) == d.base.get(path):
            continue
        if _sha(now) != d.base.get(path):
            conflicts.append(path)  # both changed it: the project's text stays
            continue
        projects.write(d.project_id, entry.id, text, actor)
        changed.append(path)
        d.base[path] = _sha(text)
    audit.record("desktop.save", actor, d.project_id, sid, {"changed": changed, "added": added, "conflicts": conflicts, "skipped": skipped})
    return {"changed": changed, "added": added, "conflicts": conflicts, "skipped": skipped}


def stop(sid: str, actor: Actor | None = None) -> None:
    d = _desktops.get(sid)
    if d is None:
        return
    if actor is not None:
        _own(sid, actor)
    with _lock:
        _desktops.pop(sid, None)
    try:
        docker_runner.client().containers.get(d.container).remove(force=True)
    except (NotFound, APIError, docker_runner.DockerUnavailable):
        pass
    audit.record("desktop.close", actor, d.project_id, sid)


def recover() -> None:
    """Picks up the desktops a restart left running."""
    try:
        for container in docker_runner.client().containers.list(filters={"label": LABEL}):
            if container.labels.get(LABEL, "") not in ("", "network"):
                _adopt(container)
    except (docker_runner.DockerUnavailable, APIError) as e:
        logger.warning("Couldn't look for desktops: %s", e)


def sweep() -> None:
    """Stops desktops nobody has looked at for IDLE seconds."""
    now = time.time()
    for d in list(_desktops.values()):
        if d.viewers == 0 and now - d.last_seen > IDLE:
            stop(d.id)


# ------------------------------------------------------------ the way in


async def http_proxy(request: Request) -> Response:
    d = _allowed(request.path_params.get("sid", ""), request.path_params.get("ticket", ""))
    if d is None:
        return JSONResponse({"error": "no access to this desktop"}, status_code=403)
    path = request.path_params.get("path", "")
    if ".." in path.split("/"):
        return JSONResponse({"error": "no such file"}, status_code=404)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{d.http}/{path}")
    except httpx.HTTPError:
        return JSONResponse({"error": "the desktop isn't answering"}, status_code=502)
    if r.status_code == 404 and path == "package.json":
        # noVNC asks for its version; the image's copy ships without the file.
        return JSONResponse({"version": "IIC-OSIC-TOOLS"})
    headers = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "cache-control", "last-modified", "etag")}
    return Response(r.content, status_code=r.status_code, headers=headers)


async def ws_bridge(ws: WebSocket) -> None:
    """noVNC's WebSocket, bridged straight to the desktop's VNC server."""
    d = _allowed(ws.path_params.get("sid", ""), ws.path_params.get("ticket", ""))
    offered = ws.scope.get("subprotocols") or []
    await ws.accept(subprotocol="binary" if "binary" in offered else None)
    if d is None:
        await ws.close(code=4403)
        return
    try:
        reader, writer = await asyncio.open_connection(*d.vnc)
    except OSError:
        await ws.close(code=4502)
        return
    d.viewers += 1

    async def browser_to_vnc() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            writer.write(data)
            await writer.drain()
            d.last_seen = time.time()

    async def vnc_to_browser() -> None:
        while chunk := await reader.read(65536):
            await ws.send_bytes(chunk)

    tasks = [asyncio.create_task(browser_to_vnc()), asyncio.create_task(vnc_to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        writer.close()
        d.viewers = max(0, d.viewers - 1)
        d.last_seen = time.time()
        try:
            await ws.close()
        except RuntimeError:
            pass


def register_routes(app) -> None:  # noqa: ANN001 - Reflex App
    api = app._api
    have = {getattr(r, "path", None) for r in api.routes}
    if WS_PATH not in have:
        api.routes.append(WebSocketRoute(WS_PATH, ws_bridge))
    if HTTP_PATH not in have:
        api.add_route(HTTP_PATH, http_proxy, methods=["GET"])
