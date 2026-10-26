"""The co-edited text of each project file, held by the server as one more peer of the browsers.

Each file is its own Yjs document (pycrdt here, as in Codoc in CAD and Cellora), named
``<project>-<file>`` (:func:`chipova.ids.doc_id`). Every browser editing a file keeps a copy and
syncs it with the server's over ``/_chipova/yjs/<doc>`` (the y-websocket protocol), and the
server passes each change on to the other browsers on that file. Because it holds a copy
itself, the server can change the text too (an approved AI patch, a restored file: they reach
everyone the way typing does), and a snapshot takes the text as it is right now.

Who may connect: the socket's URL carries a ticket (:func:`make_ticket`) that the page got for
its person; the server checks the person's access to the project at connect (``access_of``, set
by the app). No access closes the socket (4403) and is audited; a viewer's socket is read-only
(the server never applies its changes). :func:`refresh_access` checks open sockets again after
the project's members or link change.

Kept on disk per file (``<project>/docs/<file>``): ``.ystate`` (the whole document) and
``.ylog`` (every change since, appended as it happens), so a crash loses nothing; saving
(SAVE_DELAY after a change) writes the plain text to the working copy (``work/<path>``) and
compacts the log into the state. A file with neither starts from its working-copy text.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from pathlib import Path
from typing import Any, Callable

from pycrdt import (
    Awareness,
    Decoder,
    Doc,
    Encoder,
    Text,
    YMessageType,
    create_awareness_message,
    create_sync_message,
    create_update_message,
    handle_sync_message,
    read_message,
)
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from chipova import ids, paths

logger = logging.getLogger(__name__)

PATH = "/_chipova/yjs/{doc_id}"
# The Y.Text the browsers bind their editor to (assets/chipova/yjs_collab.js).
TEXT_NAME = "monaco"
# A browser this far behind is closed; it reconnects and syncs from scratch.
MAX_PENDING = 2000
SAVE_DELAY = 1.5
# A file nobody has open is let go of after this long (saved first).
IDLE = 600.0
TICKET_TTL = 24 * 3600

# Set by the app (chipova.services.projects):
# (project id, person) -> Access (chipova.domain.roles), None when the project doesn't exist.
access_of: Callable[[str, Any], Any] | None = None
# (project id, file id) -> the file's path in the project, None when it doesn't exist.
path_of: Callable[[str, str], str | None] | None = None
# Told of every denied connection: (project id, user, why).
on_denied: Callable[[str, str, str], None] | None = None
# Told when a file's text changed (after it is saved): (project id, file id).
on_saved: Callable[[str, str], None] | None = None
# Told when someone opens or closes a file: (project id).
on_presence: Callable[[str], None] | None = None


# ------------------------------------------------------------ tickets


def make_ticket(user: str, name: str, project_id: str, ttl: int = TICKET_TTL) -> str:
    """What a page puts in its socket URL to say who it is, for one project."""
    payload = json.dumps({"u": user, "n": name, "p": project_id, "x": int(time.time()) + ttl}, separators=(",", ":"))
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(paths.secret(), body.encode(), hashlib.sha256).digest()
    return body + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def read_ticket(ticket: str, project_id: str) -> dict[str, Any] | None:
    """The ticket's person ({"u", "n"}), when it is genuine, current and for this project."""
    body, _, sig = (ticket or "").partition(".")
    if not body or not sig:
        return None
    want = hmac.new(paths.secret(), body.encode(), hashlib.sha256).digest()
    try:
        got = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(want, got) or not isinstance(data, dict):
        return None
    if data.get("p") != project_id or float(data.get("x", 0)) < time.time():
        return None
    return data


# ------------------------------------------------------------ rooms


class _Client:
    """A browser's socket on a file, with its own queue of messages to send."""

    def __init__(self, ws: WebSocket, user: str, writable: bool) -> None:
        self.ws = ws
        self.user = user
        self.writable = writable
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        # The awareness clients this socket announced: Yjs clientID -> latest clock.
        self.aware: dict[int, int] = {}
        self.task: asyncio.Task | None = None
        self.close_code = 1013

    def send(self, data: bytes) -> None:
        if self.queue.qsize() > MAX_PENDING:
            self.queue.put_nowait(None)
            return
        self.queue.put_nowait(data)

    def close(self, code: int) -> None:
        self.close_code = code
        self.queue.put_nowait(None)

    async def run(self) -> None:
        while True:
            data = await self.queue.get()
            if data is None:
                try:
                    await self.ws.close(code=self.close_code)
                except Exception:  # noqa: BLE001
                    pass
                return
            try:
                await self.ws.send_bytes(data)
            except Exception:  # noqa: BLE001
                return


class Room:
    """A file's text, and the browsers editing it."""

    def __init__(self, doc_id: str) -> None:
        self.id = doc_id
        self.project_id, self.file_id = ids.split_doc_id(doc_id)
        self.doc = Doc()
        self.text = self.doc.get(TEXT_NAME, type=Text)
        self.clients: dict[WebSocket, _Client] = {}
        self.awareness = Awareness(self.doc)
        self.awareness.set_local_state(None)  # the server itself is nobody
        self._origin: WebSocket | None = None
        self._loading = False
        self._log = None
        self.dirty = False
        self.last_active = time.time()
        self.doc.observe(self._on_update)

    # -- disk

    @property
    def _base(self) -> Path:
        return paths.docs_dir(self.project_id) / self.file_id

    def load(self, seed: str | None = None) -> None:
        """Reads the file's document from disk; a file with none starts from ``seed`` (or its
        working-copy text)."""
        state = self._base.with_suffix(".ystate")
        log = self._base.with_suffix(".ylog")
        self._loading = True
        try:
            had = False
            if state.is_file():
                self.doc.apply_update(state.read_bytes())
                had = True
            if log.is_file():
                for update in _frames(log.read_bytes()):
                    try:
                        self.doc.apply_update(update)
                        had = True
                    except Exception:  # noqa: BLE001 — a torn last frame after a crash
                        logger.warning("collab: %s: skipping an unreadable change", self.id)
            if not had:
                if seed is None:
                    seed = _work_text(self.project_id, self.file_id)
                if seed:
                    self.text.insert(0, seed)
        finally:
            self._loading = False
        if not state.is_file():
            self.compact()

    def _append(self, update: bytes) -> None:
        if self._log is None:
            self._base.parent.mkdir(parents=True, exist_ok=True)
            self._log = open(self._base.with_suffix(".ylog"), "ab")  # noqa: SIM115
        self._log.write(struct.pack(">I", len(update)) + update)
        self._log.flush()

    def compact(self) -> None:
        """Folds the change log into the saved document."""
        self._base.parent.mkdir(parents=True, exist_ok=True)
        state = self._base.with_suffix(".ystate")
        tmp = state.with_name(state.name + ".tmp")
        tmp.write_bytes(self.doc.get_update())
        os.replace(tmp, state)
        if self._log is not None:
            self._log.close()
            self._log = None
        log = self._base.with_suffix(".ylog")
        if log.exists():
            log.write_bytes(b"")

    def save(self) -> None:
        """Writes the text to the working copy and compacts."""
        path = path_of(self.project_id, self.file_id) if path_of else None
        if path is None:
            return  # deleted meanwhile
        target = paths.work_dir(self.project_id) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(self.value.encode("utf-8"))
        os.replace(tmp, target)
        self.compact()
        self.dirty = False

    def close_files(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    # -- text

    @property
    def value(self) -> str:
        return str(self.text)

    def replace(self, new: str) -> None:
        """Makes the text ``new``, changing only the part that differs."""
        _replace_text(self.text, self.value, new)

    async def type(self, new: str, duration: float = 1.5, steps: int = 40) -> None:
        """Makes the text ``new`` the way someone typing would: what goes away goes at once,
        what's new comes in a piece at a time, over about ``duration`` seconds."""
        old = self.value
        start, end_old, end_new = _differing(old, new)
        if old[start:end_old]:
            self.replace(old[:start] + old[end_old:])
        middle = new[start:end_new]
        if not middle:
            return
        count = max(1, min(steps, len(middle)))
        size = -(-len(middle) // count)
        at = start
        for i in range(0, len(middle), size):
            piece = middle[i : i + size]
            current = self.value
            at = min(at, len(current))
            self.text.insert(len(current[:at].encode("utf-8")), piece)
            at += len(piece)
            await asyncio.sleep(duration / count)

    def _on_update(self, event: Any) -> None:
        if self._loading:
            return
        update = event.update
        try:
            self._append(update)
        except OSError:
            logger.exception("collab: %s: cannot log a change", self.id)
        message = create_update_message(update)
        for ws, client in list(self.clients.items()):
            if ws is not self._origin:
                client.send(message)
        self.last_active = time.time()
        self.dirty = True
        _schedule_save(self)

    # -- sockets

    async def serve(self, ws: WebSocket, user: str, writable: bool) -> None:
        """One browser's socket, from its first sync until it closes."""
        client = _Client(ws, user, writable)
        self.clients[ws] = client
        _told(self.project_id)
        client.task = asyncio.create_task(client.run())
        client.send(create_sync_message(self.doc))
        others = [cid for cid in self.awareness.states if cid != self.awareness.client_id]
        if others:
            client.send(create_awareness_message(self.awareness.encode_awareness_update(others)))
        try:
            while True:
                data = await ws.receive_bytes()
                if not data:
                    continue
                self.last_active = time.time()
                kind = data[0]
                if kind == YMessageType.SYNC:
                    # A viewer's socket may ask for the text (step 1) but not change it.
                    if not client.writable and len(data) > 1 and data[1] != 0:
                        continue
                    self._origin = ws
                    try:
                        reply = handle_sync_message(data[1:], self.doc)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("collab: %s: bad sync message: %s", self.id, e)
                        reply = None
                    finally:
                        self._origin = None
                    if reply is not None:
                        client.send(reply)
                elif kind == YMessageType.AWARENESS:
                    self._awareness(client, data)
                elif kind == 3:  # y-websocket's "query awareness": send everyone's
                    ids_ = [cid for cid in self.awareness.states if cid != self.awareness.client_id]
                    if ids_:
                        client.send(create_awareness_message(self.awareness.encode_awareness_update(ids_)))
        except (WebSocketDisconnect, RuntimeError):  # closed, or receive after close
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("collab: %s: socket error: %s", self.id, e)
        finally:
            self.clients.pop(ws, None)
            client.queue.put_nowait(None)
            self._goodbye(client)
            self.last_active = time.time()
            _told(self.project_id)

    def _awareness(self, client: _Client, data: bytes) -> None:
        try:
            update = read_message(data[1:])
            for cid, clock, here in _awareness_entries(update):
                if here:
                    client.aware[cid] = clock
                else:
                    client.aware.pop(cid, None)
            self.awareness.apply_awareness_update(update, client.ws)
        except Exception as e:  # noqa: BLE001
            logger.warning("collab: %s: bad awareness message: %s", self.id, e)
            return
        for other in list(self.clients.values()):
            if other is not client:
                other.send(data)

    def _goodbye(self, client: _Client) -> None:
        """The socket closed: its browser's cursors go away for the others."""
        if not client.aware:
            return
        message = create_awareness_message(_awareness_null(client.aware))
        try:
            self.awareness.remove_awareness_states(list(client.aware), "closed")
        except Exception:  # noqa: BLE001
            pass
        for other in list(self.clients.values()):
            other.send(message)


_rooms: dict[str, Room] = {}
_timers: dict[str, asyncio.TimerHandle] = {}


def _told(project_id: str) -> None:
    if on_presence is not None:
        try:
            on_presence(project_id)
        except Exception:  # noqa: BLE001
            logger.exception("collab: on_presence failed")


def room(doc_id: str, seed: str | None = None) -> Room:
    """The file's text, read from disk when nobody had it open."""
    r = _rooms.get(doc_id)
    if r is None:
        r = Room(doc_id)
        r.load(seed)
        _rooms[doc_id] = r
    return r


def text(project_id: str, file_id: str) -> str:
    return room(ids.doc_id(project_id, file_id)).value


def set_text(project_id: str, file_id: str, new: str) -> None:
    room(ids.doc_id(project_id, file_id)).replace(new)


def create(project_id: str, file_id: str, initial: str) -> Room:
    """A new file's document, starting with ``initial`` (saved at once)."""
    doc_id = ids.doc_id(project_id, file_id)
    forget(doc_id)
    base = paths.docs_dir(project_id) / file_id
    for suffix in (".ystate", ".ylog"):
        base.with_suffix(suffix).unlink(missing_ok=True)
    r = Room(doc_id)
    r.load(initial)
    _rooms[doc_id] = r
    r.save()
    return r


def forget(doc_id: str, close_code: int = 4410) -> None:
    """Lets go of a file's document (deleted): its sockets close."""
    r = _rooms.pop(doc_id, None)
    timer = _timers.pop(doc_id, None)
    if timer is not None:
        timer.cancel()
    if r is not None:
        for client in list(r.clients.values()):
            client.close(close_code)
        r.close_files()


def delete(project_id: str, file_id: str) -> None:
    forget(ids.doc_id(project_id, file_id))
    base = paths.docs_dir(project_id) / file_id
    for suffix in (".ystate", ".ylog"):
        base.with_suffix(suffix).unlink(missing_ok=True)


def forget_project(project_id: str) -> None:
    for doc_id in [d for d, r in _rooms.items() if r.project_id == project_id]:
        forget(doc_id)


def refresh_access(project_id: str) -> None:
    """Checks the open sockets of a project again (its members or link changed)."""
    if access_of is None:
        return
    for r in [r for r in _rooms.values() if r.project_id == project_id]:
        for client in list(r.clients.values()):
            access = access_of(project_id, client.user)
            if access is None or not access.can("view"):
                client.close(4403)
            else:
                client.writable = access.can("edit")


def _schedule_save(r: Room) -> None:
    if r.id in _timers:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # not on the server's loop (a test, a script): save now
        r.save()
        return
    _timers[r.id] = loop.call_later(SAVE_DELAY, _save_now, r.id)


def _save_now(doc_id: str) -> None:
    _timers.pop(doc_id, None)
    r = _rooms.get(doc_id)
    if r is None or not r.dirty:
        return
    try:
        r.save()
    except Exception:  # noqa: BLE001 — kept in the log; the next change tries again
        logger.exception("collab: saving %s failed", doc_id)
        return
    if on_saved is not None:
        try:
            on_saved(r.project_id, r.file_id)
        except Exception:  # noqa: BLE001
            logger.exception("collab: on_saved failed")


def flush() -> None:
    """Saves now what waits to be saved (the app is stopping)."""
    for doc_id in list(_timers):
        _timers.pop(doc_id).cancel()
    for r in list(_rooms.values()):
        if r.dirty:
            try:
                r.save()
            except Exception:  # noqa: BLE001
                logger.exception("collab: saving %s at shutdown failed", r.id)
        r.close_files()


def sweep(idle: float = IDLE) -> None:
    """Lets go of the files nobody has had open for ``idle`` seconds."""
    now = time.time()
    for doc_id, r in list(_rooms.items()):
        if r.clients or now - r.last_active < idle or doc_id in _timers:
            continue
        if r.dirty:
            r.save()
        r.close_files()
        _rooms.pop(doc_id, None)


def editors_of(project_id: str) -> dict[str, set[str]]:
    """Who has which file of a project open: {file id: {user}}."""
    out: dict[str, set[str]] = {}
    for r in _rooms.values():
        if r.project_id == project_id and r.clients:
            out[r.file_id] = {c.user for c in r.clients.values()}
    return out


# ------------------------------------------------------------ the socket endpoint


async def _endpoint(websocket: WebSocket) -> None:
    # Accepted before anything is checked, so that a refusal reaches the browser with its reason
    # (a 44xx close code: the editor stops retrying and says so); refusing the handshake itself
    # only shows the browser a broken connection, which it would retry forever.
    await websocket.accept()
    doc_id: str = websocket.path_params.get("doc_id", "")
    try:
        project_id, file_id = ids.split_doc_id(doc_id)
    except ValueError:
        await websocket.close(code=4400)
        return
    who = read_ticket(websocket.query_params.get("t", ""), project_id)
    if who is None:
        if on_denied:
            on_denied(project_id, "", "collaboration socket without a valid ticket")
        await websocket.close(code=4401)
        return
    user = str(who.get("u", ""))
    access = access_of(project_id, user) if access_of else None
    if access is None or not access.can("view"):
        if on_denied:
            on_denied(project_id, user, f"collaboration socket for {doc_id} refused: no access")
        await websocket.close(code=4403)
        return
    if path_of is not None and path_of(project_id, file_id) is None:
        await websocket.close(code=4404)
        return
    await room(doc_id).serve(websocket, user, access.can("edit"))


def register_routes(app) -> None:  # noqa: ANN001 - Reflex App
    api = getattr(app, "_api", None)
    if api is None:
        raise RuntimeError("Cannot find the Starlette app of the Reflex App.")
    if PATH not in {getattr(r, "path", None) for r in api.routes}:
        api.routes.append(WebSocketRoute(PATH, _endpoint))


# ------------------------------------------------------------ helpers


def _work_text(project_id: str, file_id: str) -> str:
    path = path_of(project_id, file_id) if path_of else None
    if path is None:
        return ""
    try:
        return (paths.work_dir(project_id) / path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _frames(data: bytes) -> list[bytes]:
    out, at = [], 0
    while at + 4 <= len(data):
        (size,) = struct.unpack(">I", data[at : at + 4])
        if at + 4 + size > len(data):
            break  # torn last frame
        out.append(data[at + 4 : at + 4 + size])
        at += 4 + size
    return out


def _differing(old: str, new: str) -> tuple[int, int, int]:
    """Where ``old`` and ``new`` differ: (start, end in old, end in new)."""
    start = 0
    limit = min(len(old), len(new))
    while start < limit and old[start] == new[start]:
        start += 1
    end_old, end_new = len(old), len(new)
    while end_old > start and end_new > start and old[end_old - 1] == new[end_new - 1]:
        end_old -= 1
        end_new -= 1
    return start, end_old, end_new


def _replace_text(ytext: Text, old: str, new: str) -> None:
    """Turns ``old`` (the text's content) into ``new`` by replacing only the middle that differs."""
    if old == new:
        return
    start, end_old, end_new = _differing(old, new)
    # pycrdt counts text positions in UTF-8 bytes (an emoji is 4), Python in characters.
    at = len(old[:start].encode("utf-8"))
    gone = len(old[start:end_old].encode("utf-8"))
    with ytext.doc.transaction():
        if gone:
            del ytext[at : at + gone]
        if end_new > start:
            ytext.insert(at, new[start:end_new])


def _awareness_entries(update: bytes) -> list[tuple[int, int, bool]]:
    """(clientID, clock, still here) for each client of an awareness update."""
    decoder = Decoder(update)
    out = []
    for _ in range(decoder.read_var_uint()):
        cid = decoder.read_var_uint()
        clock = decoder.read_var_uint()
        state = decoder.read_var_string()
        out.append((cid, clock, bool(state) and state != "null"))
    return out


def _awareness_null(clients: dict[int, int]) -> bytes:
    """An awareness update saying these clients left: state null, clock + 1."""
    encoder = Encoder()
    encoder.write_var_uint(len(clients))
    for cid, clock in clients.items():
        encoder.write_var_uint(cid)
        encoder.write_var_uint(clock + 1)
        encoder.write_var_string("null")
    return encoder.to_bytes()
