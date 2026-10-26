"""Reviews of revisions: a reviewer's verdict on one snapshot (it never carries over to another)."""

from __future__ import annotations

import time

from chipova import ids
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import Review
from chipova.services import audit, projects, revisions
from chipova.services.actors import Actor

VERDICTS = ("approved", "changes_requested", "commented")


def review(project_id: str, revision_id: str, status: str, comment: str, actor: Actor) -> Review:
    projects.require(project_id, actor, roles.REVIEW if status != "commented" else roles.COMMENT, revision_id)
    if status not in VERDICTS:
        raise ValueError(f"a review is one of {', '.join(VERDICTS)}")
    if revisions.get(project_id, revision_id) is None:
        raise projects.NotFound("no such snapshot")
    r = Review(id=ids.new_id("rv"), project_id=project_id, revision_id=revision_id, reviewer=actor.user, reviewer_name=actor.name,
               status=status, comment=(comment or "").strip()[:4000], created_at=time.time())
    db().insert("reviews", r.model_dump(mode="json"))
    audit.record("review", actor, project_id, r.id, {"revision": revision_id, "status": status})
    return r


def of_revision(project_id: str, revision_id: str) -> list[Review]:
    rows = db().query("SELECT * FROM reviews WHERE project_id = ? AND revision_id = ? ORDER BY created_at DESC", (project_id, revision_id))
    return [Review.from_row(r) for r in rows]
