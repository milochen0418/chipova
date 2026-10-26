"""Where Chipova keeps its data.

``CHIPOVA_HOME`` moves it; the default is ``~/Library/Application Support/chipova`` on macOS and
``~/.local/share/chipova`` on Linux (on re_ddns that folder is the volume
``smart-app-chipova-data``). It lies outside the project folder, so writing it never triggers a
Reflex hot reload.

    <home>/chipova.db                       projects, revisions, runs, reviews, audit (SQLite)
    <home>/secret                           signs collaboration tickets and download links
    <home>/projects/<project>/repo.git      the snapshots (a bare git repository)
    <home>/projects/<project>/work/<path>   the working copy as last saved
    <home>/projects/<project>/docs/<file>   the co-edited text of each file (Yjs state + log)
    <home>/projects/<project>/runs/<run>/   manifest.json, steps/<node>/stdout.log, artifacts/
    <home>/cache/                           layout pictures, parsed waveforms
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def _default_home() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "chipova"


def home() -> Path:
    return Path(os.environ.get("CHIPOVA_HOME") or _default_home())


def db_file() -> Path:
    return home() / "chipova.db"


def project_dir(project_id: str) -> Path:
    return home() / "projects" / project_id


def repo_dir(project_id: str) -> Path:
    return project_dir(project_id) / "repo.git"


def work_dir(project_id: str) -> Path:
    return project_dir(project_id) / "work"


def docs_dir(project_id: str) -> Path:
    return project_dir(project_id) / "docs"


def run_dir(project_id: str, run_id: str) -> Path:
    return project_dir(project_id) / "runs" / run_id


def cache_dir() -> Path:
    return home() / "cache"


def secret() -> bytes:
    """This installation's signing key (made on first use, kept in the data folder)."""
    path = home() / "secret"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        tmp = path.with_name("secret.tmp")
        tmp.write_bytes(key)
        os.chmod(tmp, 0o600)
        try:
            os.link(tmp, path)  # the first writer wins; a second one reads the first's key
        except FileExistsError:
            pass
        finally:
            tmp.unlink(missing_ok=True)
        return path.read_bytes()


def repo_root() -> Path:
    """The app's source folder (templates, infra)."""
    return Path(__file__).resolve().parent.parent
