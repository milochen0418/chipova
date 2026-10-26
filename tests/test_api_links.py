"""The REST API and download links (AC-09, AC-10 at the HTTP layer): the caller comes only from a
genuine token; a private project is refused on every route, and each refusal is audited; a viewer
reads but can't freeze or run; an AI's token can't decide; a run that isn't an allowed flow is
refused before anything runs; a download link works only for its person, unchanged and in time,
and says the SHA-256 recorded for the file."""

from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from chipova import ids, paths
from chipova.db import db
from chipova.domain.models import ApprovalStatus, Artifact, LinkAccess, Role, Run, RunStatus
from chipova.services import api, artifacts, projects, proposals, revisions
from chipova.services.actors import agent
from tests.conftest import ALICE, BOB

AI = agent("claude-code")


@pytest.fixture
def client():
    routes = [Route(path, handler, methods=[method]) for path, method, handler in api.ROUTES]
    routes.append(Route(artifacts.DOWNLOAD_PATH, artifacts.download, methods=["GET"]))
    with TestClient(Starlette(routes=routes)) as c:
        yield c


def bearer(actor) -> dict:  # noqa: ANN001
    return {"Authorization": f"Bearer {api.make_token(actor)}"}


def denied(project_id: str, user: str) -> list[str]:
    rows = db().query("SELECT action FROM audit WHERE project_id = ? AND actor = ? AND decision = 'denied'", (project_id, user))
    return [r["action"] for r in rows]


def test_a_token_names_its_caller_and_nobody_else():
    assert api.read_token(api.make_token(ALICE)).user == ALICE.user
    ai = api.read_token(api.make_token(AI))
    assert ai.is_agent and ai.user == "agent:claude-code"
    prefix, _, sig = api.make_token(ALICE).split(".")
    as_bob = json.dumps({"u": BOB.user, "n": "Bob", "k": "human", "x": int(time.time()) + 3600}).encode()
    assert api.read_token(f"{prefix}.{base64.urlsafe_b64encode(as_bob).decode().rstrip('=')}.{sig}") is None
    assert api.read_token(api.make_token(ALICE, days=-1)) is None
    assert api.read_token("chv1.nonsense") is None


async def test_a_private_project_is_refused_on_every_route(client):
    p = await projects.create("Secret", "digital_heartbeat", ALICE)
    projects.set_link_access(p.id, LinkAccess.NONE, ALICE)
    assert client.get(f"/api/projects/{p.id}").status_code == 401
    assert client.get(f"/api/projects/{p.id}", headers=bearer(ALICE)).status_code == 200
    for method, path in [
        ("GET", f"/api/projects/{p.id}"),
        ("GET", f"/api/projects/{p.id}/revisions"),
        ("GET", f"/api/projects/{p.id}/signoff"),
        ("POST", f"/api/projects/{p.id}/snapshots"),
        ("POST", f"/api/projects/{p.id}/runs"),
    ]:
        body = {"flow_id": "rtl_lint"} if path.endswith("/runs") else {}
        r = client.request(method, path, headers=bearer(BOB), json=body)
        assert r.status_code == 403, (method, path, r.status_code, r.text)
    assert len(denied(p.id, BOB.user)) >= 5
    assert not any(p.id == x.id for x in projects.visible_to(BOB.user))


async def test_a_viewer_reads_but_cannot_freeze_or_run(client):
    p = await projects.create("Shared", "digital_heartbeat", ALICE)
    projects.set_link_access(p.id, LinkAccess.NONE, ALICE)
    projects.set_member(p.id, BOB.user, Role.VIEWER, ALICE)
    r = client.get(f"/api/projects/{p.id}", headers=bearer(BOB))
    assert r.status_code == 200 and "rtl/heartbeat.v" in r.json()["files"]
    assert client.post(f"/api/projects/{p.id}/snapshots", headers=bearer(BOB), json={"message": "mine"}).status_code == 403
    assert client.post(f"/api/projects/{p.id}/runs", headers=bearer(BOB), json={"flow_id": "rtl_lint"}).status_code == 403
    assert len(revisions.history(p.id)) == 1


async def test_runs_are_only_allowed_flows_with_their_parameters(client):
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    for body in (
        {"flow_id": "shell", "params": {"cmd": "id"}},
        {"flow_id": "rtl_lint", "params": {"top": "x; id"}},
        {"flow_id": "rtl_lint", "params": {"argv": ["id"]}},
        {"flow_id": "rtl_lint", "revision_id": "sha256:" + "0" * 64},
    ):
        r = client.post(f"/api/projects/{p.id}/runs", headers=bearer(AI), json=body)
        assert r.status_code == 400, (body, r.status_code, r.text)
    assert db().one("SELECT COUNT(*) AS n FROM runs WHERE project_id = ?", (p.id,))["n"] == 0
    assert denied(p.id, AI.user).count("run.submit") == 4


async def test_an_ai_token_proposes_but_never_decides(client):
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    text = projects.read(p.id, projects.file_by_path(p.id, "rtl/heartbeat.v").id)
    r = client.post(f"/api/projects/{p.id}/agent/propose", headers=bearer(AI),
                    json={"title": "6 bits", "changes": [{"path": "rtl/heartbeat.v", "content": text.replace("N = 8", "N = 6")}]})
    assert r.status_code == 200, r.text
    action = r.json()["id"]
    assert client.post(f"/api/agent-actions/{action}/approve", headers=bearer(AI)).status_code == 403
    assert client.post(f"/api/agent-actions/{action}/reject", headers=bearer(AI), json={"reason": "no"}).status_code == 403
    assert proposals.get(action).status == ApprovalStatus.PROPOSED
    # A run an AI asked for waits for a person; the AI can't approve it either.
    run = _run(p.id, approval=ApprovalStatus.PROPOSED)
    assert client.post(f"/api/runs/{run.id}/approve", headers=bearer(AI)).status_code == 403
    assert db().one("SELECT status FROM runs WHERE id = ?", (run.id,))["status"] == RunStatus.CREATED.value


async def test_a_download_link_is_its_persons_unchanged_and_in_time(client):
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    projects.set_link_access(p.id, LinkAccess.NONE, ALICE)
    run = _run(p.id, status=RunStatus.SUCCEEDED)
    data = b"$timescale 1ns $end\n"
    out = paths.run_dir(p.id, run.id) / "out" / "sim"
    out.mkdir(parents=True)
    (out / "wave.vcd").write_bytes(data)
    a = Artifact(id=ids.new_id("af"), run_id=run.id, project_id=p.id, kind="vcd", name="sim/wave.vcd",
                 sha256=hashlib.sha256(data).hexdigest(), size=len(data), created_at=time.time())
    db().insert("artifacts", a.model_dump(mode="json"))
    r = client.get(artifacts.link(a.id, ALICE.user))
    assert r.status_code == 200 and r.content == data
    assert r.headers["X-Chipova-SHA256"] == hashlib.sha256(r.content).hexdigest()
    assert artifacts.verify(a)
    # Bob has no access, even with a genuine link of his own.
    assert client.get(artifacts.link(a.id, BOB.user)).status_code == 403
    # Alice's link with Bob's name in it, or out of time, is no link.
    as_bob = artifacts.link(a.id, ALICE.user).replace("u=" + base64.urlsafe_b64encode(ALICE.user.encode()).decode().rstrip("="),
                                                      "u=" + base64.urlsafe_b64encode(BOB.user.encode()).decode().rstrip("="))
    assert client.get(as_bob).status_code == 403
    assert client.get(artifacts.link(a.id, ALICE.user, ttl=-10)).status_code == 403
    assert set(denied(p.id, BOB.user)) == {"artifact.read"}
    # A file changed after its run no longer verifies.
    (out / "wave.vcd").write_bytes(data + b"x")
    assert not artifacts.verify(a)


def _run(project_id: str, status: RunStatus = RunStatus.CREATED, approval: ApprovalStatus = ApprovalStatus.NONE) -> Run:
    run = Run(id=ids.new_run_id(), project_id=project_id, revision_id=revisions.latest(project_id).id, flow_id="rtl_sim",
              status=status, approval_status=approval, requested_by=AI.user, requested_by_name=AI.name, requested_via="ai", created_at=time.time())
    db().insert("runs", run.model_dump(mode="json"))
    return run
