"""Snapshots (revisions): a project's files frozen as they were, the only input a run takes.

Each project has a bare git repository (``<project>/repo.git``); freezing commits the working
copy, as it is in the editors right now, onto ``main``. A revision's id is
``sha256:<hash of its source manifest>`` (each file's path and SHA-256, sorted), so freezing the
same files again gives the same revision, and the id says what went into a run without trusting
git. The commit is kept too, for history and diffs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from chipova import ids, paths
from chipova.db import db
from chipova.domain import roles
from chipova.domain.models import Revision
from chipova.services import audit
from chipova.services.actors import Actor

_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(project_id: str) -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(project_id, threading.Lock())


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    env.update(extra or {})
    return env


def _git(project_id: str, *args: str, env: dict[str, str] | None = None, data: bytes | None = None) -> bytes:
    repo = paths.repo_dir(project_id)
    done = subprocess.run(
        ["git", f"--git-dir={repo}", *args],
        input=data,
        capture_output=True,
        env=_env(env),
        timeout=120,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {done.stderr.decode(errors='replace').strip()[:500]}")
    return done.stdout


def init_repo(project_id: str) -> None:
    repo = paths.repo_dir(project_id)
    if (repo / "HEAD").is_file():
        return
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "-q", "--initial-branch=main", str(repo)], check=True, env=_env(), capture_output=True, timeout=60)


def manifest(files: dict[str, bytes]) -> list[dict]:
    """Each file's path, SHA-256 and size, sorted by path."""
    return [{"path": p, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for p, b in sorted(files.items())]


def source_sha(entries: list[dict]) -> str:
    canonical = json.dumps([[e["path"], e["sha256"]] for e in entries], separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _commit(project_id: str, files: dict[str, bytes], message: str, actor: Actor, parent: str) -> str:
    who = {
        "GIT_AUTHOR_NAME": actor.name or actor.user,
        "GIT_AUTHOR_EMAIL": actor.email or f"{actor.user}@chipova.local",
        "GIT_COMMITTER_NAME": "Chipova",
        "GIT_COMMITTER_EMAIL": "chipova@chipova.local",
    }
    with tempfile.TemporaryDirectory(prefix="chipova-freeze-") as tmp:
        wt = Path(tmp) / "wt"
        wt.mkdir()
        for path, data in files.items():
            target = wt / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        env = {**who, "GIT_WORK_TREE": str(wt), "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(project_id, "add", "-A", "--force", ".", env=env)
        tree = _git(project_id, "write-tree", env=env).decode().strip()
        args = ["commit-tree", tree, "-m", message]
        if parent:
            args += ["-p", parent]
        commit = _git(project_id, *args, env=who).decode().strip()
        _git(project_id, "update-ref", "refs/heads/main", commit)
        return commit


async def freeze(project_id: str, message: str, actor: Actor) -> Revision:
    """Freezes the working copy as it is in the editors now (the same files as an earlier
    snapshot give that snapshot back)."""
    from chipova.services import projects

    projects.require(project_id, actor, roles.SNAPSHOT)
    texts = projects.working_copy(project_id)
    return await freeze_files(project_id, {p: t.encode("utf-8") for p, t in texts.items()}, message, actor)


async def freeze_files(project_id: str, files: dict[str, bytes], message: str, actor: Actor) -> Revision:
    entries = manifest(files)
    sha = source_sha(entries)
    rev_id = f"sha256:{sha}"
    message = (message or "").strip()[:500] or "Snapshot"

    def work() -> tuple[Revision, bool]:
        with _lock(project_id):
            existing = get(project_id, rev_id)
            if existing is not None:
                return existing, False
            parent = latest(project_id)
            commit = _commit(project_id, files, message, actor, parent.git_commit if parent else "")
            rev = Revision(
                id=rev_id,
                project_id=project_id,
                git_commit=commit,
                source_sha=sha,
                parent=parent.id if parent else "",
                message=message,
                created_by=actor.user,
                created_by_name=actor.name,
                created_at=time.time(),
                files=entries,
            )
            db().insert("revisions", rev.model_dump(mode="json"))
            return rev, True

    rev, new = await asyncio.to_thread(work)
    audit.record("snapshot.freeze" if new else "snapshot.same", actor, project_id, rev.id, {"message": message, "files": len(entries)})
    return rev


def get(project_id: str, revision_id: str) -> Revision | None:
    if not ids.is_revision(revision_id):
        return None
    row = db().one("SELECT * FROM revisions WHERE project_id = ? AND id = ?", (project_id, revision_id))
    return Revision.from_row(row) if row else None


def find(project_id: str, ref: str) -> Revision | None:
    """A revision by its id or a prefix of its hash (as shown on screen, 7+ characters)."""
    ref = (ref or "").strip().lower()
    if ids.is_revision(ref):
        return get(project_id, ref)
    ref = ref.removeprefix("sha256:")
    if len(ref) < 7 or not all(c in "0123456789abcdef" for c in ref):
        return None
    rows = db().query("SELECT * FROM revisions WHERE project_id = ? AND source_sha LIKE ?", (project_id, ref + "%"))
    return Revision.from_row(rows[0]) if len(rows) == 1 else None


def latest(project_id: str) -> Revision | None:
    row = db().one("SELECT * FROM revisions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,))
    return Revision.from_row(row) if row else None


def history(project_id: str, limit: int = 100) -> list[Revision]:
    rows = db().query("SELECT * FROM revisions WHERE project_id = ? ORDER BY created_at DESC LIMIT ?", (project_id, limit))
    return [Revision.from_row(r) for r in rows]


def archive(project_id: str, revision: Revision, prefix: str = "src/") -> bytes:
    """The revision's files as a tar (what a run's container gets)."""
    return _git(project_id, "archive", "--format=tar", f"--prefix={prefix}", revision.git_commit)


def show(project_id: str, revision: Revision, path: str) -> bytes:
    return _git(project_id, "show", f"{revision.git_commit}:{ids.clean_path(path)}")


def files_of(project_id: str, revision: Revision) -> dict[str, bytes]:
    return {e["path"]: show(project_id, revision, e["path"]) for e in revision.files}


def diff(project_id: str, old: Revision, new: Revision, path: str = "") -> str:
    args = ["diff", "--no-color", "-M", old.git_commit, new.git_commit]
    if path:
        args += ["--", ids.clean_path(path)]
    return _git(project_id, *args).decode("utf-8", errors="replace")


def differs_from_working(project_id: str, revision: Revision | None, working: dict[str, str]) -> bool:
    """Whether the working copy has changed since the revision."""
    if revision is None:
        return True
    return source_sha(manifest({p: t.encode("utf-8") for p, t in working.items()})) != revision.source_sha
