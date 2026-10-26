"""Projects: their records, files, settings and who may do what in them.

A project's files are co-edited texts (:mod:`chipova.services.collab`): reading or changing a
file here goes through its document, so a change reaches everyone who has it open at once and
the working copy on disk follows a moment later. Functions that touch file texts are async and
run on the server's event loop, where the documents live.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import time

from chipova import ids, paths
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import FileEntry, LinkAccess, Membership, Project, ProjectKind, ProjectSettings, Role
from chipova.services import audit, collab, revisions, settings_file, templates
from chipova.services.actors import Actor


class Denied(PermissionError):
    """The person (or AI) may not do this; the message says why, for them to read."""


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    """Someone else changed it meanwhile."""


# ------------------------------------------------------------ records


def get(project_id: str) -> Project | None:
    if not ids.is_project(project_id):
        return None
    row = db().one("SELECT * FROM projects WHERE id = ? AND deleted = 0", (project_id,))
    return Project.from_row(row) if row else None


def must(project_id: str) -> Project:
    p = get(project_id)
    if p is None:
        raise NotFound(f"there is no project {project_id!r}")
    return p


def member_role(project_id: str, user: str) -> Role | None:
    row = db().one("SELECT role FROM memberships WHERE project_id = ? AND user = ?", (project_id, user))
    return Role(row["role"]) if row else None


def members(project_id: str) -> list[Membership]:
    rows = db().query("SELECT * FROM memberships WHERE project_id = ? ORDER BY added_at", (project_id,))
    return [Membership.from_row(r) for r in rows]


def access(project_id: str, user: str, agent: bool = False) -> roles.Access | None:
    """What ``user`` may do in the project (None when there is no such project)."""
    p = get(project_id)
    if p is None:
        return None
    return roles.access(member_role(project_id, user) if user else None, p.link_access, agent)


def access_of(project: Project, actor: Actor) -> roles.Access:
    """An actor's access. An AI agent is a member itself (``agent:<name>``), else has the access
    of the person it works for when known, else what the project's link gives; always minus what
    agents never do."""
    member = member_role(project.id, actor.user) if actor.user else None
    if member is None and actor.is_agent and actor.on_behalf_of:
        member = member_role(project.id, actor.on_behalf_of)
    return roles.access(member, project.link_access, agent=actor.is_agent)


def require(project_id: str, actor: Actor, action: str, target: str = "") -> tuple[Project, roles.Access]:
    """The project and the actor's access, when the actor may do ``action``; Denied (audited)
    otherwise."""
    p = get(project_id)
    if p is None:
        raise NotFound(f"there is no project {project_id!r}")
    a = access_of(p, actor)
    if not a.can(action):
        audit.denied(action, actor, project_id, target, f"{a.label} may not {action}")
        who = "An AI agent" if actor.is_agent and action in roles.NEVER_FOR_AGENTS else a.label
        raise Denied(f"{who} may not {_ACTION_WORDS.get(action, action)} in this project")
    return p, a


_ACTION_WORDS = {
    roles.VIEW: "see it",
    roles.EDIT: "edit files",
    roles.SNAPSHOT: "freeze snapshots",
    roles.RUN: "start runs",
    roles.DECIDE_PROPOSAL: "accept or reject AI proposals",
    roles.APPROVE_RUN: "approve runs",
    roles.REVIEW: "review revisions",
    roles.APPROVE_WAIVER: "approve waivers",
    roles.APPROVE_RELEASE: "approve releases",
    roles.REQUEST_RELEASE: "ask for a release",
    roles.MANAGE: "change the project's settings and members",
    roles.DOWNLOAD: "download artifacts",
    roles.COMMENT: "comment",
}


def visible_to(user: str) -> list[Project]:
    """The projects someone may see: anyone with the link may, and members of private ones."""
    rows = db().query(
        "SELECT p.* FROM projects p WHERE p.deleted = 0 AND (p.link_access != 'none' OR EXISTS ("
        "SELECT 1 FROM memberships m WHERE m.project_id = p.id AND m.user = ?)) ORDER BY p.updated_at DESC",
        (user,),
    )
    return [Project.from_row(r) for r in rows]


def touch(project_id: str) -> None:
    db().execute("UPDATE projects SET updated_at = ? WHERE id = ?", (time.time(), project_id))


# ------------------------------------------------------------ creating


async def create(title: str, template_id: str, actor: Actor) -> Project:
    """A new project from a template, owned by ``actor``."""
    template = templates.get(template_id)
    if template is None:
        raise ValueError(f"there is no template {template_id!r}")
    now = time.time()
    project = Project(
        id=ids.new_project_id(),
        title=(title or "").strip()[:120] or template.title.split(" (")[0],
        kind=ProjectKind(template.kind),
        template=template_id,
        owner=actor.user,
        owner_name=actor.name,
        link_access=LinkAccess.EDITOR,
        created_at=now,
        updated_at=now,
    )
    db().insert("projects", project.model_dump(mode="json"))
    db().insert(
        "memberships",
        {"project_id": project.id, "user": actor.user, "role": Role.OWNER.value, "added_by": actor.user, "added_at": now},
    )
    paths.project_dir(project.id).mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(revisions.init_repo, project.id)
    for path, text in templates.files(template_id).items():
        _add_file_row(project.id, path, actor)
        entry = file_by_path(project.id, path)
        collab.create(project.id, entry.id, text)
    audit.record("project.create", actor, project.id, project.id, {"title": project.title, "template": template_id})
    # The template as it came: the first snapshot, so the first runs have something to run.
    await revisions.freeze(project.id, "Created from the template " + template.title, actor)
    return project


# ------------------------------------------------------------ files


def files(project_id: str) -> list[FileEntry]:
    rows = db().query("SELECT * FROM files WHERE project_id = ? ORDER BY path", (project_id,))
    return [FileEntry.from_row(r) for r in rows]


def file_by_path(project_id: str, path: str) -> FileEntry | None:
    row = db().one("SELECT * FROM files WHERE project_id = ? AND path = ?", (project_id, path))
    return FileEntry.from_row(row) if row else None


def file_by_id(project_id: str, file_id: str) -> FileEntry | None:
    if not ids.is_file(file_id):
        return None
    row = db().one("SELECT * FROM files WHERE project_id = ? AND id = ?", (project_id, file_id))
    return FileEntry.from_row(row) if row else None


def path_of(project_id: str, file_id: str) -> str | None:
    f = file_by_id(project_id, file_id)
    return f.path if f else None


def _add_file_row(project_id: str, path: str, actor: Actor) -> FileEntry:
    now = time.time()
    entry = FileEntry(project_id=project_id, id=ids.new_file_id(), path=path, created_at=now, updated_at=now, updated_by=actor.user)
    db().insert("files", entry.model_dump(mode="json"))
    return entry


def read(project_id: str, file_id: str) -> str:
    """The file's text right now (as everyone editing it sees it)."""
    if file_by_id(project_id, file_id) is None:
        raise NotFound(f"there is no file {file_id!r}")
    return collab.text(project_id, file_id)


def read_path(project_id: str, path: str) -> str:
    entry = file_by_path(project_id, ids.clean_path(path))
    if entry is None:
        raise NotFound(f"there is no file {path!r} in this project")
    return collab.text(project_id, entry.id)


def write(project_id: str, file_id: str, text: str, actor: Actor) -> None:
    """Changes a file's text for everyone (a person's edit from the server side, an approved
    patch, a restored file)."""
    if file_by_id(project_id, file_id) is None:
        raise NotFound(f"there is no file {file_id!r}")
    collab.set_text(project_id, file_id, text)
    db().execute("UPDATE files SET updated_at = ?, updated_by = ? WHERE project_id = ? AND id = ?", (time.time(), actor.user, project_id, file_id))
    touch(project_id)


def add_file(project_id: str, path: str, text: str, actor: Actor) -> FileEntry:
    require(project_id, actor, roles.EDIT, path)
    path = ids.clean_path(path)
    if file_by_path(project_id, path) is not None:
        raise Conflict(f"{path} already exists")
    if len(files(project_id)) >= 500:
        raise Conflict("a project holds at most 500 files")
    entry = _add_file_row(project_id, path, actor)
    collab.create(project_id, entry.id, text)
    touch(project_id)
    audit.record("file.create", actor, project_id, path)
    return entry


def rename_file(project_id: str, file_id: str, new_path: str, actor: Actor) -> FileEntry:
    require(project_id, actor, roles.EDIT, file_id)
    entry = file_by_id(project_id, file_id)
    if entry is None:
        raise NotFound(f"there is no file {file_id!r}")
    new_path = ids.clean_path(new_path)
    if new_path == entry.path:
        return entry
    if file_by_path(project_id, new_path) is not None:
        raise Conflict(f"{new_path} already exists")
    db().execute("UPDATE files SET path = ?, updated_at = ?, updated_by = ? WHERE project_id = ? AND id = ?", (new_path, time.time(), actor.user, project_id, file_id))
    old = paths.work_dir(project_id) / entry.path
    if old.is_file():
        target = paths.work_dir(project_id) / new_path
        target.parent.mkdir(parents=True, exist_ok=True)
        old.replace(target)
    touch(project_id)
    audit.record("file.rename", actor, project_id, entry.path, {"to": new_path})
    return file_by_id(project_id, file_id)  # type: ignore[return-value]


def delete_file(project_id: str, file_id: str, actor: Actor) -> None:
    require(project_id, actor, roles.EDIT, file_id)
    entry = file_by_id(project_id, file_id)
    if entry is None:
        return
    if entry.path == settings_file.FILE:
        raise Conflict(f"{settings_file.FILE} holds the project's settings and stays")
    db().execute("DELETE FROM files WHERE project_id = ? AND id = ?", (project_id, file_id))
    collab.delete(project_id, file_id)
    (paths.work_dir(project_id) / entry.path).unlink(missing_ok=True)
    touch(project_id)
    audit.record("file.delete", actor, project_id, entry.path)


def working_copy(project_id: str) -> dict[str, str]:
    """Every file's text as it is right now: {path: text}."""
    return {f.path: collab.text(project_id, f.id) for f in files(project_id)}


# ------------------------------------------------------------ settings (chipova.toml)


def settings(project_id: str) -> tuple[ProjectSettings, str, str]:
    """(the settings, what is wrong with the file or "", the file's hash for save_settings)."""
    entry = file_by_path(project_id, settings_file.FILE)
    text = collab.text(project_id, entry.id) if entry else ""
    parsed, error = settings_file.parse(text)
    return parsed, error, hashlib.sha256(text.encode()).hexdigest()


def save_settings(project_id: str, new: ProjectSettings, expected_sha: str, actor: Actor) -> str:
    """Writes the settings, when the file is still as it was read (``expected_sha``); Conflict
    otherwise. Returns the new hash."""
    require(project_id, actor, roles.EDIT, settings_file.FILE)
    entry = file_by_path(project_id, settings_file.FILE)
    current = collab.text(project_id, entry.id) if entry else ""
    if expected_sha and hashlib.sha256(current.encode()).hexdigest() != expected_sha:
        raise Conflict("someone changed the settings meanwhile: look at theirs and save again")
    text = settings_file.dump(new)
    if entry is None:
        entry = _add_file_row(project_id, settings_file.FILE, actor)
        collab.create(project_id, entry.id, text)
    else:
        write(project_id, entry.id, text, actor)
    audit.record("settings.save", actor, project_id, settings_file.FILE, new.model_dump())
    return hashlib.sha256(text.encode()).hexdigest()


# ------------------------------------------------------------ the project itself


def rename(project_id: str, title: str, actor: Actor) -> None:
    require(project_id, actor, roles.EDIT)
    title = (title or "").strip()[:120]
    if title:
        db().execute("UPDATE projects SET title = ?, updated_at = ? WHERE id = ?", (title, time.time(), project_id))
        audit.record("project.rename", actor, project_id, project_id, {"title": title})


def set_link_access(project_id: str, value: LinkAccess, actor: Actor) -> None:
    require(project_id, actor, roles.MANAGE)
    db().execute("UPDATE projects SET link_access = ? WHERE id = ?", (value.value, project_id))
    audit.record("project.link_access", actor, project_id, project_id, {"link_access": value.value})
    collab.refresh_access(project_id)


def set_member(project_id: str, user: str, role: Role | None, actor: Actor) -> None:
    """Adds a member (an e-mail), changes their role, or removes them (role None)."""
    p, _ = require(project_id, actor, roles.MANAGE)
    user = (user or "").strip().lower()
    if not user or ("@" not in user and not user.startswith(("guest-", "agent:"))):
        raise ValueError("a member is given by their e-mail address (or agent:<name> for an AI)")
    if user == p.owner and role != Role.OWNER:
        raise Conflict("the owner stays the owner")
    if role is None:
        db().execute("DELETE FROM memberships WHERE project_id = ? AND user = ?", (project_id, user))
    else:
        db().execute(
            "INSERT INTO memberships(project_id, user, role, added_by, added_at) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(project_id, user) DO UPDATE SET role = excluded.role",
            (project_id, user, role.value, actor.user, time.time()),
        )
    audit.record("project.member", actor, project_id, user, {"role": role.value if role else None})
    collab.refresh_access(project_id)


def set_ai_may_run(project_id: str, flows: list[str], actor: Actor) -> None:
    require(project_id, actor, roles.MANAGE)
    db().execute("UPDATE projects SET ai_may_run = ? WHERE id = ?", (_json(sorted(set(flows))), project_id))
    audit.record("project.ai_policy", actor, project_id, project_id, {"ai_may_run": sorted(set(flows))})


def delete(project_id: str, actor: Actor) -> None:
    """Deletes the project and its files; the audit log keeps its history."""
    require(project_id, actor, roles.MANAGE)
    db().execute("UPDATE projects SET deleted = 1 WHERE id = ?", (project_id,))
    collab.forget_project(project_id)
    shutil.rmtree(paths.project_dir(project_id), ignore_errors=True)
    audit.record("project.delete", actor, project_id, project_id)


def _json(value) -> str:  # noqa: ANN001
    import json

    return json.dumps(value)


def wire() -> None:
    """Connects the co-editing relay to the projects' records."""

    def _access(project_id: str, user: str):  # noqa: ANN202
        return access(project_id, user)

    def _denied(project_id: str, user: str, why: str) -> None:
        audit.record("collab.connect", Actor(user or "anonymous", user or "anonymous"), project_id, "", decision="denied", detail=why)

    def _saved(project_id: str, file_id: str) -> None:
        db().execute("UPDATE files SET updated_at = ? WHERE project_id = ? AND id = ?", (time.time(), project_id, file_id))
        touch(project_id)

    collab.access_of = _access
    collab.path_of = path_of
    collab.on_denied = _denied
    collab.on_saved = _saved
