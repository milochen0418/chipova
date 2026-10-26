"""Programming a real board with a run's bitstream, through a helper on the computer the board is
plugged into (the blueprint's hardware worker): Chipova itself never touches USB.

A person starts the helper (``scripts/board_helper.py``, also served at
``/_chipova/board_helper.py``) on their bench computer with their own API token. It says hello
(its name, what openFPGALoader sees) and asks for work. Only that person may send it work: a
succeeded FPGA run of a project they may run, and the board to program. The helper downloads the
bitstream through a link signed for them, checks the SHA-256 Chipova recorded, runs openFPGALoader
for that board and reports. AI agents never program boards.

    job: QUEUED ─(the helper takes it)─► SENT ─► PROGRAMMING ─► DONE | FAILED
         QUEUED ─(the person)─► CANCELED
"""

from __future__ import annotations

import json
import re
import time

from starlette.requests import Request
from starlette.responses import Response

from chipova import ids, paths
from chipova.db import db
from chipova.domain import roles
from chipova.jobs import engine, flows
from chipova.services import artifacts, audit, projects
from chipova.services.actors import Actor

HELPER_PATH = "/_chipova/board_helper.py"
ONLINE = 60.0  # seconds since a helper's last hello or request for work
BOARD = re.compile(r"^[A-Za-z0-9_]{1,40}$")
# openFPGALoader's names (its --list-boards) for the boards of Chipova's templates, the first one
# each flow suggests: the iCEBreaker is its ice40_generic.
BOARDS = {
    "fpga_ice40": ["ice40_generic", "icebreaker-bitsy"],
    "fpga_ecp5": ["ulx3s", "orangeCrab", "colorlight"],
    "fpga_gowin": ["tangnano9k", "tangnano4k", "tangnano1k"],
}
FINAL = {"DONE", "FAILED", "CANCELED"}


def _row(r) -> dict:  # noqa: ANN001
    d = dict(r)
    if "boards" in d:
        try:
            d["boards"] = json.loads(d["boards"] or "[]")
        except ValueError:
            d["boards"] = []
    if "last_seen" in d:
        d["online"] = time.time() - (d["last_seen"] or 0) < ONLINE
    return d


def _not_agent(actor: Actor, what: str) -> None:
    if actor.is_agent:
        audit.denied("board." + what, actor, "", "", "an AI agent may not program boards")
        raise projects.Denied("An AI agent may not program boards")


# ------------------------------------------------------------ helpers


def hello(actor: Actor, name: str, boards: list[str], loader: str) -> dict:
    """A helper starting or still there: its record (one per person and name)."""
    _not_agent(actor, "helper")
    name = (name or "board helper").strip()[:60]
    now = time.time()
    row = db().one("SELECT * FROM board_helpers WHERE owner = ? AND name = ?", (actor.user, name))
    fields = {"boards": json.dumps([str(b)[:200] for b in (boards or [])][:20]), "loader": (loader or "")[:200], "last_seen": now, "owner_name": actor.name}
    if row is None:
        helper_id = ids.new_id("bh")
        db().insert("board_helpers", {"id": helper_id, "owner": actor.user, "name": name, "created_at": now, **fields})
        audit.record("board.helper", actor, "", helper_id, {"name": name})
    else:
        helper_id = row["id"]
        db().update("board_helpers", {"id": helper_id}, fields)
    return helper(helper_id)


def helper(helper_id: str) -> dict | None:
    row = db().one("SELECT * FROM board_helpers WHERE id = ?", (helper_id,))
    return _row(row) if row else None


def helpers_of(user: str) -> list[dict]:
    return [_row(r) for r in db().query("SELECT * FROM board_helpers WHERE owner = ? ORDER BY last_seen DESC", (user,))]


def _own_helper(helper_id: str, actor: Actor) -> dict:
    h = helper(helper_id)
    if h is None or h["owner"] != actor.user:
        raise projects.NotFound("no such board helper of yours")
    return h


# ------------------------------------------------------------ jobs


def bitstream_of(run) -> object | None:  # noqa: ANN001
    return next((a for a in engine.artifacts_of(run.id) if a.kind == "bitstream"), None)


def request(project_id: str, run_id: str, helper_id: str, board: str, actor: Actor) -> dict:
    """Asks the person's own helper to program ``board`` with the run's bitstream."""
    _not_agent(actor, "request")
    projects.require(project_id, actor, roles.PROGRAM_BOARD, run_id)
    run = engine.get(run_id)
    if run is None or run.project_id != project_id or run.flow_id not in flows.FPGA_FLOWS or run.status.value != "SUCCEEDED":
        raise ValueError("only a succeeded Build FPGA run has a bitstream to program")
    bit = bitstream_of(run)
    if bit is None:
        raise ValueError("that run kept no bitstream")
    h = _own_helper(helper_id, actor)
    if not h["online"]:
        raise ValueError(f"the board helper “{h['name']}” isn't running (last seen {int(time.time() - h['last_seen'])} s ago)")
    if not BOARD.match(board or ""):
        raise ValueError("give openFPGALoader's name of the board, e.g. ice40_generic (iCEBreaker), ulx3s, tangnano9k")
    now = time.time()
    job = {
        "id": ids.new_id("bj"), "project_id": project_id, "run_id": run.id, "artifact_id": bit.id, "helper_id": h["id"],
        "board": board, "status": "QUEUED", "requested_by": actor.user, "requested_by_name": actor.name, "log": "",
        "created_at": now, "updated_at": now,
    }
    db().insert("board_jobs", job)
    audit.record("board.request", actor, project_id, job["id"], {"run": run.id, "board": board, "helper": h["name"], "sha256": bit.sha256})
    return job


def job(job_id: str) -> dict | None:
    row = db().one("SELECT * FROM board_jobs WHERE id = ?", (job_id,))
    return dict(row) if row else None


def jobs_of_run(run_id: str) -> list[dict]:
    return [dict(r) for r in db().query("SELECT * FROM board_jobs WHERE run_id = ? ORDER BY created_at DESC", (run_id,))]


def take(helper_id: str, actor: Actor) -> dict | None:
    """The helper's next job (then SENT), with where to fetch the bitstream and its SHA-256."""
    h = _own_helper(helper_id, actor)
    db().update("board_helpers", {"id": h["id"]}, {"last_seen": time.time()})
    row = db().one("SELECT * FROM board_jobs WHERE helper_id = ? AND status = 'QUEUED' ORDER BY created_at LIMIT 1", (h["id"],))
    if row is None:
        return None
    j = dict(row)
    _set(j["id"], "SENT", "")
    a = artifacts.get(j["artifact_id"])
    project = projects.get(j["project_id"])
    return {
        "job": j["id"], "board": j["board"], "run": j["run_id"], "project": project.title if project else "",
        "name": a.name if a else "", "size": a.size if a else 0, "sha256": a.sha256 if a else "",
        "url": artifacts.link(j["artifact_id"], actor.user) if a else "",
    }


def report(job_id: str, actor: Actor, status: str, log: str) -> dict:
    j = job(job_id)
    if j is None:
        raise projects.NotFound("no such job")
    _own_helper(j["helper_id"], actor)
    if status not in ("PROGRAMMING", "DONE", "FAILED"):
        raise ValueError("a job is PROGRAMMING, DONE or FAILED")
    if j["status"] in FINAL:
        raise projects.Conflict(f"the job is already {j['status']}")
    _set(job_id, status, log)
    if status in FINAL:
        audit.record("board.program", actor, j["project_id"], job_id, {"run": j["run_id"], "board": j["board"]},
                     decision="ok" if status == "DONE" else "error", detail=(log or "")[-300:])
    return job(job_id)


def cancel(job_id: str, actor: Actor) -> dict:
    j = job(job_id)
    if j is None or j["requested_by"] != actor.user:
        raise projects.NotFound("no such job of yours")
    if j["status"] != "QUEUED":
        raise projects.Conflict("the helper has it already")
    _set(job_id, "CANCELED", "")
    return job(job_id)


def _set(job_id: str, status: str, log: str) -> None:
    fields = {"status": status, "updated_at": time.time()}
    if log:
        fields["log"] = log[-20000:]
    db().update("board_jobs", {"id": job_id}, fields)
    for listener in listeners:
        try:
            listener(job_id)
        except Exception:  # noqa: BLE001
            pass


listeners: list = []


def helper_script() -> bytes:
    return (paths.repo_root() / "scripts" / "board_helper.py").read_bytes()


async def download_helper(request: Request) -> Response:
    return Response(helper_script(), media_type="text/x-python", headers={"Content-Disposition": 'attachment; filename="board_helper.py"'})


def register_routes(app) -> None:  # noqa: ANN001 - Reflex App
    api = app._api
    if not any(getattr(r, "path", None) == HELPER_PATH for r in api.routes):
        api.add_route(HELPER_PATH, download_helper, methods=["GET"])
