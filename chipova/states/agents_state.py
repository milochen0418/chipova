"""The Agents page: what AI agents did in the project (every tool call they made, allowed or
refused, from the audit log) and how to connect one."""

from __future__ import annotations

import dataclasses
import json
import os

import reflex as rx

from chipova.services import audit
from chipova.states.ide import IdeState


@dataclasses.dataclass
class AgentCall:
    at: float = 0.0
    agent: str = ""
    action: str = ""
    target: str = ""
    decision: str = ""
    detail: str = ""


class AgentsState(rx.State):
    calls: list[AgentCall] = []
    # A personal API token, shown once after it is made.
    token: str = ""

    @rx.var
    def hub_address(self) -> str:
        zone = os.environ.get("SERVICE_ZONE", "reflex-ddns.com")
        return f"https://ai.{zone}/api/mcp"

    @rx.event
    async def make_token(self):
        from chipova.services import api  # noqa: PLC0415
        from chipova.states.ui_state import UiState  # noqa: PLC0415

        actor = (await self.get_state(UiState)).actor()
        self.token = api.make_token(actor)
        audit.record("api.token", actor, (await self.get_state(IdeState)).project_id, actor.user)

    @rx.event
    async def load(self):
        ide = await self.get_state(IdeState)
        rows = []
        for e in audit.entries(ide.project_id, 300):
            if e.actor_kind != "agent" and not e.action.startswith(("proposal.", "run.approve", "run.reject")):
                continue
            detail = e.detail or ""
            if not detail and e.args:
                detail = json.dumps(e.args, ensure_ascii=False)[:240]
            rows.append(AgentCall(e.ts, e.actor.removeprefix("agent:") if e.actor_kind == "agent" else (e.actor_name or e.actor), e.action, e.target, e.decision, detail))
        self.calls = rows[:150]
