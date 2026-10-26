"""Ids of the things Chipova keeps, and checks that an id from outside (a URL, an AI's call) is
one of them before it is used in a path or a query."""

from __future__ import annotations

import re
import secrets

# A project's id is also the token of its shared room (which can't hold "_") and a folder name.
_PROJECT = re.compile(r"^[a-f0-9]{10}$")
_FILE = re.compile(r"^[a-f0-9]{8}$")
_RUN = re.compile(r"^run-[a-f0-9]{10}$")
_REVISION = re.compile(r"^sha256:[a-f0-9]{64}$")
_PREFIXED = re.compile(r"^(ap|rv|cm|wv|rel|af)-[a-f0-9]{10}$")
# A path in a project: folders and names of letters, digits, "_", "-", "." (no "..", no "/" at
# either end), at most 8 levels.
_PATH_PART = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")


def new_project_id() -> str:
    return secrets.token_hex(5)


def new_file_id() -> str:
    return secrets.token_hex(4)


def new_run_id() -> str:
    return "run-" + secrets.token_hex(5)


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5)}"


def is_project(value: str) -> bool:
    return bool(value) and _PROJECT.match(value) is not None


def is_file(value: str) -> bool:
    return bool(value) and _FILE.match(value) is not None


def is_run(value: str) -> bool:
    return bool(value) and _RUN.match(value) is not None


def is_revision(value: str) -> bool:
    return bool(value) and _REVISION.match(value) is not None


def is_prefixed(value: str, prefix: str) -> bool:
    m = _PREFIXED.match(value or "")
    return m is not None and m.group(1) == prefix


def is_identifier(value: str) -> bool:
    """A Verilog identifier (a module, a signal)."""
    return bool(value) and _IDENT.match(value) is not None


def short_revision(revision_id: str) -> str:
    """What a revision is called on screen: the first 7 hex digits of its source hash."""
    return revision_id.split(":", 1)[-1][:7] if revision_id else ""


def clean_path(path: str) -> str:
    """A project file path, checked: ValueError for anything that could leave the project
    (``..``, absolute paths, odd characters)."""
    path = (path or "").strip().replace("\\", "/")
    parts = [p for p in path.split("/")]
    if not path or path.startswith("/") or len(parts) > 8:
        raise ValueError(f"not a project file path: {path!r}")
    for part in parts:
        if not _PATH_PART.match(part) or part in {".", ".."} or ".." in part:
            raise ValueError(f"not a project file path: {path!r} (use letters, digits, _ - . and /)")
    return "/".join(parts)


def doc_id(project_id: str, file_id: str) -> str:
    """The co-edited text of a file: its relay room (and Yjs document) name."""
    return f"{project_id}-{file_id}"


def split_doc_id(value: str) -> tuple[str, str]:
    """(project id, file id) of a relay room name; ValueError when it isn't one."""
    project_id, _, file_id = (value or "").partition("-")
    if not is_project(project_id) or not is_file(file_id):
        raise ValueError(f"not a document id: {value!r}")
    return project_id, file_id
