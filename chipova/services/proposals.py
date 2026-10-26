"""AI proposals: an AI agent never changes files itself; it proposes a patch, and a person
decides (blueprint 7: Plan → Propose → Review → Execute).

A proposal keeps, per file, the text the AI read (``base``) and the text it proposes, plus the
snapshot that was the latest when it proposed (the context it worked on). Accepting it:

- applies each file through its co-edited document, so everyone sees the change at once; when
  people edited the file since the AI read it, the AI's change is merged into theirs
  (``git merge-file``), and a conflict stops it (nothing is applied, the person sees why);
- freezes a snapshot of the result, recorded on the proposal (``applied_revision``).

Rejecting needs a reason and changes nothing. A proposal nobody decided on expires after
``TTL`` seconds.
"""

from __future__ import annotations

import difflib
import hashlib
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from chipova import ids
from chipova.db import db
from chipova.domain import machines, roles
from chipova.domain.models import AgentAction, ApprovalStatus
from chipova.services import audit, projects, revisions
from chipova.services.actors import Actor

TTL = 7 * 24 * 3600
MAX_FILES = 50
MAX_TEXT = 1_000_000

# Told (project id, proposal id) when a proposal is made or decided.
listeners: list[Callable[[str, str], None]] = []


def _notify(project_id: str, action_id: str) -> None:
    for fn in list(listeners):
        try:
            fn(project_id, action_id)
        except Exception:  # noqa: BLE001
            pass


def get(action_id: str) -> AgentAction | None:
    if not ids.is_prefixed(action_id, "ap"):
        return None
    row = db().one("SELECT * FROM agent_actions WHERE id = ?", (action_id,))
    return AgentAction.from_row(row) if row else None


def of_project(project_id: str, limit: int = 100) -> list[AgentAction]:
    expire_old(project_id)
    rows = db().query("SELECT * FROM agent_actions WHERE project_id = ? ORDER BY created_at DESC LIMIT ?", (project_id, limit))
    return [AgentAction.from_row(r) for r in rows]


def pending_count(project_id: str) -> int:
    row = db().one("SELECT COUNT(*) AS n FROM agent_actions WHERE project_id = ? AND status = 'PROPOSED' AND expires_at > ?", (project_id, time.time()))
    return row["n"] if row else 0


def expire_old(project_id: str = "") -> None:
    sql = "UPDATE agent_actions SET status = 'EXPIRED', decided_at = ? WHERE status = 'PROPOSED' AND expires_at < ?"
    args: list[Any] = [time.time(), time.time()]
    if project_id:
        sql += " AND project_id = ?"
        args.append(project_id)
    db().execute(sql, args)


def propose(
    project_id: str,
    actor: Actor,
    title: str,
    changes: list[dict[str, Any]],
    rationale: str = "",
    plan: str = "",
) -> AgentAction:
    """Records an AI's patch for people to decide on. ``changes``: [{"path", "content"}] with the
    whole new text of each file (``"delete": true`` to delete one; a new path makes a file)."""
    projects.require(project_id, actor, roles.COMMENT)
    if not isinstance(changes, list) or not changes:
        raise ValueError("a proposal changes at least one file: changes=[{path, content}]")
    if len(changes) > MAX_FILES:
        raise ValueError(f"a proposal changes at most {MAX_FILES} files")
    files: list[dict[str, Any]] = []
    seen = set()
    for c in changes:
        if not isinstance(c, dict):
            raise ValueError("each change is {path, content} (or {path, delete: true})")
        path = ids.clean_path(str(c.get("path", "")))
        if path in seen:
            raise ValueError(f"{path} is changed twice")
        seen.add(path)
        entry = projects.file_by_path(project_id, path)
        delete = bool(c.get("delete"))
        content = c.get("content")
        if delete:
            if entry is None:
                raise ValueError(f"{path} doesn't exist, so it can't be deleted")
            op, new = "delete", ""
        else:
            if not isinstance(content, str):
                raise ValueError(f"give the whole new text of {path} as content")
            if len(content) > MAX_TEXT:
                raise ValueError(f"{path} is too long for a proposal")
            op, new = ("modify" if entry else "create"), content
        base = projects.read(project_id, entry.id) if entry else ""
        if op == "modify" and base == new:
            continue  # unchanged
        files.append({"path": path, "op": op, "base": base, "new": new, "base_sha": _sha(base)})
    if not files:
        raise ValueError("the proposal changes nothing: the files already read like that")
    latest = revisions.latest(project_id)
    now = time.time()
    action = AgentAction(
        id=ids.new_id("ap"),
        project_id=project_id,
        agent=actor.user,
        on_behalf_of=actor.on_behalf_of,
        kind="patch",
        title=(title or "").strip()[:200] or "Proposed change",
        rationale=(rationale or "").strip()[:5000],
        plan=(plan or "").strip()[:5000],
        base_revision=latest.id if latest else "",
        payload={"files": files},
        status=ApprovalStatus.PROPOSED,
        created_at=now,
        expires_at=now + TTL,
    )
    db().insert("agent_actions", action.model_dump(mode="json"))
    audit.record("proposal.create", actor, project_id, action.id, {"title": action.title, "files": [f["path"] for f in files]})
    _notify(project_id, action.id)
    return action


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def diffs(action: AgentAction) -> list[dict[str, Any]]:
    """Per file: path, op, unified diff (base → proposed), lines added and removed, and whether
    the file changed since the AI read it."""
    out = []
    for f in action.payload.get("files", []):
        old = f["base"].splitlines(keepends=True)
        new = f["new"].splitlines(keepends=True) if f["op"] != "delete" else []
        lines = list(difflib.unified_diff(old, new, f"a/{f['path']}", f"b/{f['path']}", n=3))
        added = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
        removed = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
        entry = projects.file_by_path(action.project_id, f["path"])
        now = projects.read(action.project_id, entry.id) if entry else ""
        moved = (now != f["base"]) if f["op"] != "create" else entry is not None
        out.append({
            "path": f["path"], "op": f["op"], "diff": "".join(lines), "added": added, "removed": removed,
            "changed_since": moved, "base": f["base"], "new": f["new"],
        })
    return out


def _merge(base: str, mine: str, theirs: str) -> tuple[str, bool]:
    """Three-way merge: (merged text, clean). ``mine`` is the file now, ``theirs`` the AI's."""
    with tempfile.TemporaryDirectory(prefix="chipova-merge-") as tmp:
        p = Path(tmp)
        (p / "mine").write_text(mine, "utf-8")
        (p / "base").write_text(base, "utf-8")
        (p / "theirs").write_text(theirs, "utf-8")
        done = subprocess.run(
            ["git", "merge-file", "-p", "-L", "now", "-L", "read by the AI", "-L", "proposed", str(p / "mine"), str(p / "base"), str(p / "theirs")],
            capture_output=True, timeout=60, check=False,
        )
    if done.returncode < 0:
        raise RuntimeError(done.stderr.decode(errors="replace"))
    return done.stdout.decode("utf-8", errors="replace"), done.returncode == 0


async def accept(action_id: str, actor: Actor, note: str = "") -> AgentAction:
    """Applies the proposal for everyone and freezes a snapshot of the result."""
    action = get(action_id)
    if action is None:
        raise projects.NotFound(f"there is no proposal {action_id!r}")
    projects.require(action.project_id, actor, roles.DECIDE_PROPOSAL, action_id)
    expire_old(action.project_id)
    action = get(action_id)  # type: ignore[assignment]
    machines.check(machines.APPROVAL, action.status, ApprovalStatus.APPROVED)
    plan: list[tuple[dict, str]] = []
    conflicts = []
    for f in action.payload.get("files", []):
        entry = projects.file_by_path(action.project_id, f["path"])
        if f["op"] == "create":
            if entry is not None:
                conflicts.append(f"{f['path']} was created meanwhile")
            plan.append((f, f["new"]))
        elif entry is None:
            conflicts.append(f"{f['path']} was deleted meanwhile")
        elif f["op"] == "delete":
            plan.append((f, ""))
        else:
            now = projects.read(action.project_id, entry.id)
            if now == f["base"]:
                plan.append((f, f["new"]))
            else:
                merged, clean = _merge(f["base"], now, f["new"])
                if not clean:
                    conflicts.append(f"{f['path']} was edited where the AI changed it")
                plan.append((f, merged))
    if conflicts:
        audit.record("proposal.accept", actor, action.project_id, action_id, decision="error", detail="; ".join(conflicts))
        raise projects.Conflict("Can't apply it as it is: " + "; ".join(conflicts) + ". Ask the AI to propose it again on the current text.")
    for f, text in plan:
        if f["op"] == "create":
            projects.add_file(action.project_id, f["path"], text, actor)
        elif f["op"] == "delete":
            entry = projects.file_by_path(action.project_id, f["path"])
            projects.delete_file(action.project_id, entry.id, actor)  # type: ignore[union-attr]
        else:
            entry = projects.file_by_path(action.project_id, f["path"])
            projects.write(action.project_id, entry.id, text, actor)  # type: ignore[union-attr]
    rev = await revisions.freeze(action.project_id, f"AI proposal accepted: {action.title} ({action.id}, by {action.agent}, accepted by {actor.name})", actor)
    db().update("agent_actions", {"id": action_id}, {
        "status": ApprovalStatus.APPROVED.value, "decided_by": actor.user, "decided_by_name": actor.name,
        "decided_at": time.time(), "reason": (note or "").strip()[:2000], "applied_revision": rev.id,
    })
    audit.record("proposal.accept", actor, action.project_id, action_id, {"revision": rev.id})
    _notify(action.project_id, action_id)
    return get(action_id)  # type: ignore[return-value]


def reject(action_id: str, actor: Actor, reason: str) -> AgentAction:
    """Records that a person turned the proposal down, and why; nothing changes."""
    action = get(action_id)
    if action is None:
        raise projects.NotFound(f"there is no proposal {action_id!r}")
    projects.require(action.project_id, actor, roles.DECIDE_PROPOSAL, action_id)
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("say why it is rejected: the AI reads the reason")
    expire_old(action.project_id)
    action = get(action_id)  # type: ignore[assignment]
    machines.check(machines.APPROVAL, action.status, ApprovalStatus.REJECTED)
    db().update("agent_actions", {"id": action_id}, {
        "status": ApprovalStatus.REJECTED.value, "decided_by": actor.user, "decided_by_name": actor.name,
        "decided_at": time.time(), "reason": reason[:2000],
    })
    audit.record("proposal.reject", actor, action.project_id, action_id, {"reason": reason})
    _notify(action.project_id, action_id)
    return get(action_id)  # type: ignore[return-value]
