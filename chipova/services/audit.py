"""The audit log: who did what, when, and whether it was allowed (blueprint 7.2 and 13).

Every change, every run, every AI tool call and every refusal is a row. Nothing is ever deleted
from it, also not with its project.
"""

from __future__ import annotations

import time
from typing import Any

from chipova.db import db
from chipova.domain.models import AuditEntry
from chipova.services.actors import Actor


def record(
    action: str,
    actor: Actor | None = None,
    project_id: str = "",
    target: str = "",
    args: dict[str, Any] | None = None,
    decision: str = "ok",
    detail: str = "",
) -> None:
    db().insert(
        "audit",
        {
            "ts": time.time(),
            "project_id": project_id,
            "actor": actor.user if actor else "system",
            "actor_name": actor.name if actor else "Chipova",
            "actor_kind": actor.kind if actor else "system",
            "action": action,
            "target": target,
            "args": _short(args or {}),
            "decision": decision,
            "detail": detail[:2000],
        },
    )


def denied(action: str, actor: Actor | None, project_id: str = "", target: str = "", detail: str = "", args: dict | None = None) -> None:
    record(action, actor, project_id, target, args, decision="denied", detail=detail)


def entries(project_id: str, limit: int = 200) -> list[AuditEntry]:
    rows = db().query("SELECT * FROM audit WHERE project_id = ? ORDER BY id DESC LIMIT ?", (project_id, limit))
    return [AuditEntry.from_row(r) for r in rows]


def _short(args: dict[str, Any]) -> dict[str, Any]:
    """Arguments as logged: long texts (whole files) are cut, so the log stays readable."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 300:
            out[k] = v[:300] + f"… ({len(v)} chars)"
        elif isinstance(v, list) and len(str(v)) > 600:
            out[k] = f"[{len(v)} items]"
        else:
            out[k] = v
    return out
