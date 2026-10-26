"""Chipova: an IC design studio that people and AI agents use together, from RTL to GDSII.

Pages: ``/`` lists the projects (:mod:`.components.home`); ``/p/<id>`` is a project, used together
by everyone who opens it: the files edited live (each with their own cursor), runs of the allowed
flows in sealed containers on frozen snapshots, the AI's proposals for people to decide on,
layouts, signoff and releases; ``/settings`` shows the tool profiles.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

import reflex as rx
from reflex_ddns_auth.intent import install_intent_host
from starlette.requests import Request
from starlette.responses import Response

from chipova import ids
from chipova.agents import ai_tools
from chipova.components.admin import admin_page
from chipova.components.code_view import code_view
from chipova.components.home import home_page
from chipova.components.layout_view import layout_view
from chipova.components.sections import agents_view, implement_view, settings_view, verify_view
from chipova.components.signoff_view import release_view, signoff_view
from chipova.components.together import BYE_PATH, call_keepalive
from chipova.components.workspace import workspace
from chipova.jobs import engine, flows_asic, layout
from chipova.services import api, artifacts, collab, presence, projects, proposals
from chipova.services.call import CALLS_ENABLED
from chipova.states.admin_state import AdminState
from chipova.states.home_state import HomeState
from chipova.states.ide import IdeState
from chipova.states import room as room_state
from chipova.states.room import note, push_later
from chipova.states.runs_state import RunState
from chipova.states.ui_state import AuthState

logger = logging.getLogger(__name__)

SWEEP_EVERY = 60.0


def project_page() -> rx.Component:
    return workspace({
        "code": code_view(),
        "verify": verify_view(),
        "implement": implement_view(),
        "layout": layout_view(),
        "signoff": signoff_view(),
        "release": release_view(),
        "agents": agents_view(),
        "settings": settings_view(),
    })


async def bye(request: Request) -> Response:
    """A closing tab's goodbye: the others in its project stop seeing it."""
    try:
        data = json.loads((await request.body())[:4096] or b"{}")
    except ValueError:
        return Response(status_code=400)
    token = str(data.get("token") or "") if isinstance(data, dict) else ""
    left = presence.leave(token) if token else ""
    if left:
        push_later(left, "people", "files")
    return Response(status_code=204)


async def _sweep() -> None:
    """Now and then: lets go of files nobody has open, and expires old proposals."""
    while True:
        await asyncio.sleep(SWEEP_EVERY)
        try:
            collab.sweep()
            proposals.expire_old()
        except Exception:  # noqa: BLE001
            logger.exception("The sweep failed")


@contextlib.asynccontextmanager
async def lifespan():
    """Starts the run queue (following runs a restart left running); at shutdown saves what
    waits to be saved and stops the layout renderer (runs go on in their containers)."""
    await engine.start()
    sweeper = asyncio.create_task(_sweep())
    try:
        yield
    finally:
        sweeper.cancel()
        collab.flush()
        await engine.stop()
        layout.renderer.close()


def _ai_activity(project_id: str, actor, what: str) -> None:  # noqa: ANN001
    """The AI is in the project while it works: among its people, and in its activity."""
    if not ids.is_project(project_id):
        return
    user = actor.user
    presence.join(project_id, user, "ai-" + str(abs(hash(user)) % 10**8), user, actor.name)
    note(project_id, actor.name, what, "ai")
    push_later(project_id, "people")


app = rx.App(
    head_components=[
        rx.el.script(src="/chipova/collab.js", defer=True),
        rx.el.script(src="/chipova/ide.js", defer=True),
        rx.el.script(src="/chipova/wave.js", defer=True),
        rx.el.script(src="/chipova/layout.js", defer=True),
    ],
)
_auth = [AuthState.load_auth] if AuthState is not None else []
app.add_page(home_page, route="/", title="Chipova", on_load=[*_auth, IdeState.leave_project, HomeState.refresh])
app.add_page(project_page, route="/p/[project_id]", title="Chipova", on_load=[*_auth, IdeState.on_load_project, RunState.select_latest])
app.add_page(admin_page, route="/settings", title="Tools · Chipova", on_load=[*_auth, IdeState.leave_project, AdminState.load])
# Dialogs of other apps (calls, the AI Hub's assistant) on every page.
install_intent_host(app)
if CALLS_ENABLED:
    app.extra_app_wraps[(8, "ChipovaCallKeepalive")] = lambda stateful: rx.fragment(call_keepalive())
app.register_lifespan_task(lifespan)
try:
    from reflex_base.registry import RegistrationContext

    room_state.registration = RegistrationContext.get()
except (ImportError, LookupError):  # another Reflex: pushes run in Reflex's own context anyway
    pass

# The services, connected: files' co-editing to the projects' records, runs and proposals to
# the rooms of their projects.
projects.wire()
_saved = collab.on_saved


def _on_saved(project_id: str, file_id: str) -> None:
    """A file's text was saved: whether the editors still match the latest snapshot."""
    if _saved is not None:
        _saved(project_id, file_id)
    push_later(project_id, "latest")


collab.on_saved = _on_saved
collab.on_presence = lambda project_id: push_later(project_id, "files")
engine.listeners.append(lambda project_id, run_id: push_later(project_id, "runs", "latest"))
proposals.listeners.append(lambda project_id, action_id: push_later(project_id, "proposals"))
ai_tools.activity = _ai_activity
flows_asic.register()

collab.register_routes(app)
artifacts.register_routes(app)
api.register_routes(app)
app._api.add_route(BYE_PATH, bye, methods=["POST"])

# What an AI may do here, for the AI Hub.
ai_tools.register(app)
