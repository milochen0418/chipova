"""Chipova's REST API (blueprint 8.2), for scripts, CI and integrations.

Every endpoint is a thin layer over the same services the pages use, so the same access rules,
state machines and audit log apply. Requests and answers are Pydantic models.

Who is calling: ``Authorization: Bearer <token>``, a personal API token made on a project's
Agents page (:func:`make_token`; an agent's token makes its calls an agent's), or the platform's
sign-in cookie. ``GET /api/runs/{id}/events`` streams a run's changes as server-sent events.

    GET  /api/projects                       POST /api/projects
    GET  /api/projects/{id}                  POST /api/projects/{id}/snapshots
    GET  /api/projects/{id}/revisions        POST /api/projects/{id}/runs
    GET  /api/projects/{id}/runs             GET  /api/runs/{run_id}
    GET  /api/runs/{run_id}/events           GET  /api/runs/{run_id}/artifacts
    POST /api/runs/{run_id}/approve          POST /api/projects/{id}/agent/propose
    POST /api/agent-actions/{id}/approve     POST /api/agent-actions/{id}/reject
    POST /api/projects/{id}/reviews          POST /api/projects/{id}/releases
    GET  /api/projects/{id}/signoff
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from chipova import ids, paths
from chipova.domain import machines
from chipova.domain.models import Artifact, Project, Revision, Run, RunStep, SignoffCheck
from chipova.jobs import engine, flows
from chipova.services import artifacts, projects, proposals, releases, revisions, reviews, signoff
from chipova.services.actors import Actor, agent

TOKEN_DAYS = 30


# ------------------------------------------------------------ tokens


def make_token(actor: Actor, days: int = TOKEN_DAYS) -> str:
    """A personal API token: calls made with it are this person's (or this agent's)."""
    payload = json.dumps({"u": actor.user, "n": actor.name, "k": actor.kind, "x": int(time.time()) + days * 86400}, separators=(",", ":"))
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(paths.secret(), b"api|" + body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"chv1.{body}.{sig}"


def read_token(token: str) -> Actor | None:
    try:
        prefix, body, sig = token.split(".")
    except ValueError:
        return None
    want = base64.urlsafe_b64encode(hmac.new(paths.secret(), b"api|" + body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    if prefix != "chv1" or not hmac.compare_digest(sig, want):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    if float(data.get("x", 0)) < time.time():
        return None
    if data.get("k") == "agent":
        return agent(str(data.get("u", "")).removeprefix("agent:"))
    return Actor(str(data.get("u", "")), str(data.get("n", "")), email=str(data.get("u", "")) if "@" in str(data.get("u", "")) else "")


def _cookie_actor(request: Request) -> Actor | None:
    import os

    secret = os.environ.get("DDNS_AUTH_SECRET", "")
    token = request.cookies.get(os.environ.get("DDNS_AUTH_COOKIE", "ddns_auth"), "")
    if not secret or not token:
        return None
    try:
        import jwt

        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None
    email = str(claims.get("email", "")).lower()
    return Actor(email, str(claims.get("name", "") or email), email=email) if email else None


def _actor(request: Request) -> Actor | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return read_token(token.strip())
    return _cookie_actor(request)


# ------------------------------------------------------------ schemas


class CreateProject(BaseModel):
    title: str = ""
    template: str = "digital_heartbeat"


class FreezeSnapshot(BaseModel):
    message: str = "Snapshot"


class SubmitRun(BaseModel):
    flow_id: str
    revision_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    source_run: str = ""


class ProposePatch(BaseModel):
    title: str
    changes: list[dict[str, Any]]
    rationale: str = ""
    plan: str = ""


class Decide(BaseModel):
    reason: str = ""


class ReviewIn(BaseModel):
    revision_id: str
    status: str
    comment: str = ""


class ReleaseIn(BaseModel):
    revision_id: str = ""
    title: str = ""


class ProjectOut(BaseModel):
    project: Project
    files: list[str]
    latest_revision: Revision | None
    role: str


class RunOut(BaseModel):
    run: Run
    steps: list[RunStep]
    queue_position: int = 0


class ArtifactOut(BaseModel):
    artifact: Artifact
    download_url: str


class SignoffOut(BaseModel):
    revision_id: str
    checks: list[SignoffCheck]


# ------------------------------------------------------------ handlers

Handler = Callable[[Request, Actor], Awaitable[Any]]


def endpoint(fn: Handler, body: type[BaseModel] | None = None):
    """Wraps a handler: who is calling, the body's model, errors as HTTP answers."""

    async def handle(request: Request) -> Response:
        actor = _actor(request)
        if actor is None or not actor.user:
            return JSONResponse({"error": "sign in, or send Authorization: Bearer <a Chipova API token>"}, status_code=401)
        try:
            args = []
            if body is not None:
                raw = await request.body()
                args.append(body.model_validate_json(raw or b"{}"))
            result = await fn(request, actor, *args)
        except ValidationError as e:
            return JSONResponse({"error": "invalid request", "detail": json.loads(e.json())}, status_code=400)
        except projects.Denied as e:
            return JSONResponse({"error": str(e)}, status_code=403)
        except projects.NotFound as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except (projects.Conflict, machines.InvalidTransition) as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except (ValueError, flows.FlowError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if isinstance(result, Response):
            return result
        if isinstance(result, BaseModel):
            return Response(result.model_dump_json(), media_type="application/json")
        return Response(json.dumps(_plain(result), default=str), media_type="application/json")

    return handle


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _pid(request: Request) -> str:
    return request.path_params.get("project_id", "")


async def list_projects(request: Request, actor: Actor):
    return {"projects": projects.visible_to(actor.user)}


async def create_project(request: Request, actor: Actor, body: CreateProject):
    if actor.is_agent:
        raise projects.Denied("An AI agent may not make projects")
    return await projects.create(body.title, body.template, actor)


async def get_project(request: Request, actor: Actor):
    p, a = projects.require(_pid(request), actor, "view")
    return ProjectOut(project=p, files=[f.path for f in projects.files(p.id)], latest_revision=revisions.latest(p.id), role=a.label)


async def freeze(request: Request, actor: Actor, body: FreezeSnapshot):
    return await revisions.freeze(_pid(request), body.message, actor)


async def list_revisions(request: Request, actor: Actor):
    projects.require(_pid(request), actor, "view")
    return {"revisions": revisions.history(_pid(request), 200)}


async def submit_run(request: Request, actor: Actor, body: SubmitRun):
    run = await engine.submit(_pid(request), body.flow_id, actor, revision=body.revision_id, params=body.params, via="agent" if actor.is_agent else "api", source_run=body.source_run)
    return RunOut(run=run, steps=engine.steps_of(run.id), queue_position=engine.queue_position(run))


async def list_runs(request: Request, actor: Actor):
    projects.require(_pid(request), actor, "view")
    return {"runs": engine.runs_of(_pid(request), limit=200)}


def _run(request: Request, actor: Actor) -> Run:
    run = engine.get(request.path_params.get("run_id", ""))
    if run is None:
        raise projects.NotFound("no such run")
    projects.require(run.project_id, actor, "view", run.id)
    return run


async def get_run(request: Request, actor: Actor):
    run = _run(request, actor)
    return RunOut(run=run, steps=engine.steps_of(run.id), queue_position=engine.queue_position(run))


async def run_events(request: Request, actor: Actor):
    """Server-sent events: the run and its steps whenever they change, until it ends."""
    run = _run(request, actor)

    async def stream():
        last = ""
        while True:
            r = engine.get(run.id)
            if r is None:
                return
            state = RunOut(run=r, steps=engine.steps_of(r.id), queue_position=engine.queue_position(r)).model_dump_json()
            if state != last:
                last = state
                yield f"event: run\ndata: {state}\n\n"
            if r.status.finished:
                yield "event: end\ndata: {}\n\n"
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


async def run_artifacts(request: Request, actor: Actor):
    run = _run(request, actor)
    projects.require(run.project_id, actor, "download", run.id)
    return {"artifacts": [ArtifactOut(artifact=a, download_url=artifacts.link(a.id, actor.user)) for a in engine.artifacts_of(run.id)]}


async def approve_run(request: Request, actor: Actor):
    return await engine.approve(request.path_params.get("run_id", ""), actor)


async def propose(request: Request, actor: Actor, body: ProposePatch):
    return proposals.propose(_pid(request), actor, body.title, body.changes, body.rationale, body.plan)


async def approve_action(request: Request, actor: Actor):
    return await proposals.accept(request.path_params.get("action_id", ""), actor)


async def reject_action(request: Request, actor: Actor, body: Decide):
    return proposals.reject(request.path_params.get("action_id", ""), actor, body.reason)


async def add_review(request: Request, actor: Actor, body: ReviewIn):
    return reviews.review(_pid(request), body.revision_id, body.status, body.comment, actor)


async def add_release(request: Request, actor: Actor, body: ReleaseIn):
    return releases.create(_pid(request), body.revision_id, body.title, actor)


async def get_signoff(request: Request, actor: Actor):
    pid = _pid(request)
    projects.require(pid, actor, "view")
    ref = request.query_params.get("revision", "")
    rev = revisions.find(pid, ref) if ref else revisions.latest(pid)
    if rev is None:
        raise projects.NotFound("no such snapshot")
    return SignoffOut(revision_id=rev.id, checks=signoff.checklist(pid, rev.id))


ROUTES = [
    ("/api/projects", "GET", endpoint(list_projects)),
    ("/api/projects", "POST", endpoint(create_project, CreateProject)),
    ("/api/projects/{project_id}", "GET", endpoint(get_project)),
    ("/api/projects/{project_id}/snapshots", "POST", endpoint(freeze, FreezeSnapshot)),
    ("/api/projects/{project_id}/revisions", "GET", endpoint(list_revisions)),
    ("/api/projects/{project_id}/runs", "POST", endpoint(submit_run, SubmitRun)),
    ("/api/projects/{project_id}/runs", "GET", endpoint(list_runs)),
    ("/api/runs/{run_id}", "GET", endpoint(get_run)),
    ("/api/runs/{run_id}/events", "GET", endpoint(run_events)),
    ("/api/runs/{run_id}/artifacts", "GET", endpoint(run_artifacts)),
    ("/api/runs/{run_id}/approve", "POST", endpoint(approve_run)),
    ("/api/projects/{project_id}/agent/propose", "POST", endpoint(propose, ProposePatch)),
    ("/api/agent-actions/{action_id}/approve", "POST", endpoint(approve_action)),
    ("/api/agent-actions/{action_id}/reject", "POST", endpoint(reject_action, Decide)),
    ("/api/projects/{project_id}/reviews", "POST", endpoint(add_review, ReviewIn)),
    ("/api/projects/{project_id}/releases", "POST", endpoint(add_release, ReleaseIn)),
    ("/api/projects/{project_id}/signoff", "GET", endpoint(get_signoff)),
]


def register_routes(app) -> None:  # noqa: ANN001 - Reflex App
    api = app._api
    have = {(getattr(r, "path", None), m) for r in api.routes for m in (getattr(r, "methods", None) or [])}
    for path, method, handler in ROUTES:
        if (path, method) not in have:
            api.add_route(path, handler, methods=[method])

