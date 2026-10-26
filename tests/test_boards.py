"""Programming a board through a person's own board helper: only the helper's owner sends it work,
only for a succeeded FPGA run of a project they may run; AI agents and viewers never; the helper
gets the bitstream through a link signed for its owner, with the SHA-256 to check, and the job
goes QUEUED → SENT → PROGRAMMING → DONE once."""

from __future__ import annotations

import hashlib
import time

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from chipova import ids, paths
from chipova.db import db
from chipova.domain.models import Artifact, LinkAccess, Role, Run, RunStatus
from chipova.services import api, artifacts, boards, projects, revisions
from chipova.services.actors import agent
from tests.conftest import ALICE, BOB

BITSTREAM = b"\x7e\xaa\x99\x7e" + bytes(range(256)) * 64


async def _fpga_run(owner=ALICE):  # noqa: ANN001, ANN202
    p = await projects.create("Blinky", "fpga_blinky", owner)
    run = Run(id=ids.new_run_id(), project_id=p.id, revision_id=revisions.latest(p.id).id, flow_id="fpga_ice40",
              status=RunStatus.SUCCEEDED, requested_by=owner.user, created_at=time.time())
    db().insert("runs", run.model_dump(mode="json"))
    out = paths.run_dir(p.id, run.id) / "out" / "fpga"
    out.mkdir(parents=True)
    (out / "blinky.bin").write_bytes(BITSTREAM)
    a = Artifact(id=ids.new_id("af"), run_id=run.id, project_id=p.id, kind="bitstream", name="fpga/blinky.bin",
                 sha256=hashlib.sha256(BITSTREAM).hexdigest(), size=len(BITSTREAM), created_at=time.time())
    db().insert("artifacts", a.model_dump(mode="json"))
    return p, run


async def test_only_the_helpers_owner_sends_it_work_and_never_an_ai():
    p, run = await _fpga_run()
    mine = boards.hello(ALICE, "Bench", ["Bus 001 Device 004: FTDI"], "openFPGALoader v1.2.0")
    assert boards.hello(ALICE, "Bench", [], "x")["id"] == mine["id"], "the same helper again"
    bobs = boards.hello(BOB, "Bob's bench", [], "x")
    with pytest.raises(projects.NotFound):
        boards.request(p.id, run.id, bobs["id"], "ice40_generic", ALICE)  # someone else's helper
    with pytest.raises(projects.Denied):
        boards.request(p.id, run.id, mine["id"], "ice40_generic", agent("claude-code", on_behalf_of=ALICE.user))
    with pytest.raises(ValueError):
        boards.request(p.id, run.id, mine["id"], "--force", ALICE)  # not a board name
    projects.set_link_access(p.id, LinkAccess.NONE, ALICE)
    projects.set_member(p.id, BOB.user, Role.VIEWER, ALICE)
    with pytest.raises(projects.Denied):
        boards.request(p.id, run.id, bobs["id"], "ice40_generic", BOB)  # a viewer
    db().execute("UPDATE board_helpers SET last_seen = 0 WHERE id = ?", (mine["id"],))
    with pytest.raises(ValueError, match="isn't running"):
        boards.request(p.id, run.id, mine["id"], "ice40_generic", ALICE)
    assert db().one("SELECT COUNT(*) AS n FROM board_jobs")["n"] == 0


async def test_a_job_from_request_to_done_through_the_api():
    p, run = await _fpga_run()
    routes = [Route(path, handler, methods=[method]) for path, method, handler in api.ROUTES]
    routes.append(Route(artifacts.DOWNLOAD_PATH, artifacts.download, methods=["GET"]))
    auth = {"Authorization": f"Bearer {api.make_token(ALICE)}"}
    with TestClient(Starlette(routes=routes)) as client:
        helper = client.post("/api/boards/hello", headers=auth, json={"name": "Bench", "boards": [], "loader": "dry run"}).json()
        assert client.get(f"/api/boards/next?helper={helper['id']}", headers=auth).json() == {"job": None}
        job = client.post(f"/api/runs/{run.id}/program", headers=auth, json={"helper_id": helper["id"], "board": "ice40_generic"}).json()
        assert job["status"] == "QUEUED"
        bob = {"Authorization": f"Bearer {api.make_token(BOB)}"}
        assert client.get(f"/api/boards/next?helper={helper['id']}", headers=bob).status_code == 404
        work = client.get(f"/api/boards/next?helper={helper['id']}&wait=2", headers=auth).json()["job"]
        assert work["job"] == job["id"] and work["board"] == "ice40_generic" and boards.job(job["id"])["status"] == "SENT"
        data = client.get(work["url"]).content
        assert hashlib.sha256(data).hexdigest() == work["sha256"] and data == BITSTREAM
        assert client.post(f"/api/boards/jobs/{job['id']}", headers=bob, json={"status": "DONE"}).status_code == 404
        assert client.post(f"/api/boards/jobs/{job['id']}", headers=auth, json={"status": "PROGRAMMING"}).status_code == 200
        done = client.post(f"/api/boards/jobs/{job['id']}", headers=auth, json={"status": "DONE", "log": "SHA-256 matches"}).json()
        assert done["status"] == "DONE" and "matches" in done["log"]
        assert client.post(f"/api/boards/jobs/{job['id']}", headers=auth, json={"status": "FAILED"}).status_code == 409
    logged = [r["action"] for r in db().query("SELECT action FROM audit WHERE project_id = ? ORDER BY ts", (p.id,))]
    assert "board.request" in logged and "board.program" in logged
