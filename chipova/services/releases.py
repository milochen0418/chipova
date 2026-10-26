"""Releases: a snapshot put forward as a tape-out preparation package, behind a gate.

    DRAFT ─request review─► IN_REVIEW ─approve─► APPROVED ─(an owner, by hand)─► FOUNDRY_READY
                                └─reject─► REJECTED

The gate (:func:`gate`): every check the project kind requires is PASS or WAIVED on that very
snapshot (:mod:`chipova.services.signoff`), and a reviewer or owner who is not the requester has
approved. Approving a release that fails the gate is refused with what is missing (blueprint
AC-11). Chipova never marks a release FOUNDRY_READY on its own: an owner does, after the gate
passes, with a statement of who checked the foundry's own requirements, which an open PDK's
results can't replace.

The package (:func:`build_package`) is a zip with the release manifest (snapshot, file hashes,
checklist, waivers, approvals, runs), the sources, the runs' manifests and their artifacts.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

from chipova import ids, paths
from chipova.db import db
from chipova.domain import machines, roles
from chipova.domain.models import Release, ReleaseStatus, RunStatus, SignoffStatus
from chipova.jobs import engine
from chipova.services import audit, projects, revisions, signoff
from chipova.services.actors import Actor

DISCLAIMER = (
    "Tape-out preparation package made by Chipova. It is NOT a foundry signoff: results on an open "
    "PDK (SkyWater's SKY130 is an experimental preview) say nothing about a foundry's acceptance, and "
    "a person with the foundry's rules and authority decides what is sent."
)
# Artifacts kept out of packages (big, and not evidence a reviewer needs).
SKIP_KINDS = {"vcd", "fst", "spice_raw"}
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024


def get(release_id: str) -> Release | None:
    if not ids.is_prefixed(release_id, "rel"):
        return None
    row = db().one("SELECT * FROM releases WHERE id = ?", (release_id,))
    return Release.from_row(row) if row else None


def of_project(project_id: str) -> list[Release]:
    return [Release.from_row(r) for r in db().query("SELECT * FROM releases WHERE project_id = ? ORDER BY created_at DESC", (project_id,))]


def _checklist(project_id: str, revision_id: str) -> list[dict]:
    return [c.model_dump(mode="json") for c in signoff.checklist(project_id, revision_id)]


def gate(release: Release) -> tuple[bool, list[str]]:
    """Whether the release may be approved, and what is missing."""
    missing = []
    for c in signoff.checklist(release.project_id, release.revision_id):
        if c.required and c.status not in (SignoffStatus.PASS, SignoffStatus.WAIVED):
            missing.append(f"{c.title}: {c.status.value}" + (f" ({c.why})" if c.why and c.status != SignoffStatus.FAIL else f" ({c.summary})" if c.summary else ""))
    approvers = [a for a in release.approvals if a.get("decision") == "approve" and a.get("user") != release.requested_by]
    if not approvers:
        missing.append("Approval: a reviewer or owner other than the requester must approve")
    return not missing, missing


def create(project_id: str, revision: str, title: str, actor: Actor) -> Release:
    projects.require(project_id, actor, roles.REQUEST_RELEASE)
    if actor.is_agent:
        raise projects.Denied("An AI agent may not start a release")
    rev = revisions.find(project_id, revision) if revision else revisions.latest(project_id)
    if rev is None:
        raise projects.NotFound("no such snapshot")
    r = Release(
        id=ids.new_id("rel"), project_id=project_id, revision_id=rev.id, title=(title or "").strip()[:200] or f"Release of {ids.short_revision(rev.id)}",
        status=ReleaseStatus.DRAFT, requested_by=actor.user, requested_by_name=actor.name, created_at=time.time(),
        checklist=_checklist(project_id, rev.id),
    )
    db().insert("releases", r.model_dump(mode="json"))
    audit.record("release.create", actor, project_id, r.id, {"revision": rev.id, "title": r.title})
    return r


def _move(r: Release, new: ReleaseStatus, **fields) -> Release:  # noqa: ANN003
    machines.check(machines.RELEASE, r.status, new)
    db().update("releases", {"id": r.id}, {"status": new.value, **fields})
    return get(r.id)  # type: ignore[return-value]


def request_review(release_id: str, actor: Actor) -> Release:
    r = _must(release_id)
    projects.require(r.project_id, actor, roles.REQUEST_RELEASE, release_id)
    r = _move(r, ReleaseStatus.IN_REVIEW, checklist=_checklist(r.project_id, r.revision_id))
    audit.record("release.request_review", actor, r.project_id, release_id)
    return r


def approve(release_id: str, actor: Actor, comment: str = "") -> Release:
    r = _must(release_id)
    projects.require(r.project_id, actor, roles.APPROVE_RELEASE, release_id)
    if actor.user == r.requested_by:
        raise projects.Denied("who asked for a release can't approve it")
    if r.status != ReleaseStatus.IN_REVIEW:
        raise ValueError(f"the release is {r.status.value}: ask for a review first")
    approvals = [*r.approvals, {"user": actor.user, "name": actor.name, "decision": "approve", "comment": (comment or "")[:2000], "at": time.time()}]
    trial = r.model_copy(update={"approvals": approvals})
    ok, missing = gate(trial)
    if not ok:
        audit.denied("release.approve", actor, r.project_id, release_id, "; ".join(missing))
        raise projects.Conflict("The gate is not passed, so it can't be approved: " + "; ".join(missing))
    r = _move(r, ReleaseStatus.APPROVED, approvals=approvals, checklist=_checklist(r.project_id, r.revision_id))
    audit.record("release.approve", actor, r.project_id, release_id, {"comment": comment})
    return r


def reject(release_id: str, actor: Actor, reason: str) -> Release:
    r = _must(release_id)
    projects.require(r.project_id, actor, roles.APPROVE_RELEASE, release_id)
    if not (reason or "").strip():
        raise ValueError("say why it is rejected")
    approvals = [*r.approvals, {"user": actor.user, "name": actor.name, "decision": "reject", "comment": reason[:2000], "at": time.time()}]
    r = _move(r, ReleaseStatus.REJECTED, approvals=approvals)
    audit.record("release.reject", actor, r.project_id, release_id, {"reason": reason})
    return r


def reopen(release_id: str, actor: Actor) -> Release:
    r = _must(release_id)
    projects.require(r.project_id, actor, roles.REQUEST_RELEASE, release_id)
    r = _move(r, ReleaseStatus.DRAFT, approvals=[])
    audit.record("release.reopen", actor, r.project_id, release_id)
    return r


def mark_foundry_ready(release_id: str, actor: Actor, statement: str) -> Release:
    """An owner's own declaration, after the gate passed: who checked the foundry's rules."""
    r = _must(release_id)
    projects.require(r.project_id, actor, roles.MANAGE, release_id)
    if actor.is_agent:
        raise projects.Denied("An AI agent may not do this")
    ok, missing = gate(r)
    if not ok:
        raise projects.Conflict("The gate is not passed: " + "; ".join(missing))
    statement = (statement or "").strip()
    if len(statement) < 20:
        raise ValueError("say who checked the foundry's requirements and how (at least a sentence)")
    approvals = [*r.approvals, {"user": actor.user, "name": actor.name, "decision": "foundry_ready", "comment": statement[:4000], "at": time.time()}]
    r = _move(r, ReleaseStatus.FOUNDRY_READY, approvals=approvals)
    audit.record("release.foundry_ready", actor, r.project_id, release_id, {"statement": statement})
    return r


def _must(release_id: str) -> Release:
    r = get(release_id)
    if r is None:
        raise projects.NotFound(f"there is no release {release_id!r}")
    return r


# ------------------------------------------------------------ the package


def package_path(r: Release) -> Path:
    return paths.project_dir(r.project_id) / "releases" / r.id / "package.zip"


def build_package(release_id: str, actor: Actor) -> Release:
    r = _must(release_id)
    projects.require(r.project_id, actor, roles.DOWNLOAD, release_id)
    rev = revisions.get(r.project_id, r.revision_id)
    project = projects.must(r.project_id)
    ok, missing = gate(r)
    runs = [x for x in engine.runs_of(r.project_id, limit=500, revision_id=r.revision_id) if x.status == RunStatus.SUCCEEDED]
    latest: dict[str, object] = {}
    for x in runs:  # newest first: one run per flow (and per source, for checks)
        latest.setdefault((x.flow_id, x.source_run), x)
    manifest = {
        "schema": "chipova.release-manifest/1",
        "disclaimer": DISCLAIMER,
        "release": {"id": r.id, "title": r.title, "status": r.status.value, "requested_by": r.requested_by, "created_at": r.created_at},
        "project": {"id": project.id, "title": project.title, "kind": project.kind.value},
        "revision": {"id": rev.id, "git_commit": rev.git_commit, "source_sha": rev.source_sha, "files": rev.files} if rev else None,
        "gate": {"passed": ok, "missing": missing},
        "checklist": _checklist(r.project_id, r.revision_id),
        "waivers": [w.model_dump(mode="json") for w in signoff.waivers(r.project_id, r.revision_id)],
        "approvals": r.approvals,
        "runs": [],
        "built_at": time.time(),
        "built_by": actor.user,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        if rev is not None:
            for path, data in revisions.files_of(r.project_id, rev).items():
                z.writestr(f"source/{path}", data)
        for run in latest.values():
            mpath = paths.run_dir(run.project_id, run.id) / "manifest.json"  # type: ignore[attr-defined]
            entry = {"id": run.id, "flow": run.flow_id, "manifest_sha256": "", "artifacts": []}  # type: ignore[attr-defined]
            if mpath.is_file():
                data = mpath.read_bytes()
                entry["manifest_sha256"] = hashlib.sha256(data).hexdigest()
                z.writestr(f"runs/{run.id}/manifest.json", data)  # type: ignore[attr-defined]
            for a in engine.artifacts_of(run.id):  # type: ignore[attr-defined]
                if a.kind in SKIP_KINDS or a.size > MAX_ARTIFACT_BYTES:
                    continue
                f = engine.out_dir(run) / a.name  # type: ignore[arg-type]
                if f.is_file():
                    z.write(f, f"runs/{run.id}/{a.name}")  # type: ignore[attr-defined]
                    entry["artifacts"].append({"name": a.name, "kind": a.kind, "sha256": a.sha256, "size": a.size})
            manifest["runs"].append(entry)
        body = json.dumps(manifest, indent=1, default=str).encode()
        z.writestr("RELEASE_MANIFEST.json", body)
        z.writestr("approval.json", json.dumps({"release": r.id, "status": r.status.value, "approvals": r.approvals, "gate": manifest["gate"]}, indent=1, default=str))
        z.writestr("README.txt", DISCLAIMER + "\n")
    out = package_path(r)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf.getvalue())
    sha = hashlib.sha256(buf.getvalue()).hexdigest()
    db().update("releases", {"id": r.id}, {"manifest_sha": hashlib.sha256(body).hexdigest(), "package_artifact": sha})
    audit.record("release.package", actor, r.project_id, r.id, {"sha256": sha, "runs": len(manifest["runs"])})
    return get(r.id)  # type: ignore[return-value]
