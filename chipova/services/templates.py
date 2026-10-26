"""Project templates: the folders under ``templates/`` in the app's source.

A template is a folder with ``template.json`` (title, kind, description, order) and the files a
new project starts with, ``chipova.toml`` among them.
"""

from __future__ import annotations

import dataclasses
import json
from functools import lru_cache
from pathlib import Path

from chipova import ids, paths

TEMPLATES_DIR = paths.repo_root() / "templates"
DEFAULT = "digital_heartbeat"


@dataclasses.dataclass(frozen=True)
class Template:
    id: str
    title: str
    kind: str
    description: str
    order: int


@lru_cache(maxsize=1)
def templates() -> tuple[Template, ...]:
    out = []
    for folder in sorted(TEMPLATES_DIR.iterdir()) if TEMPLATES_DIR.is_dir() else []:
        meta = folder / "template.json"
        if not meta.is_file():
            continue
        d = json.loads(meta.read_text("utf-8"))
        out.append(Template(folder.name, d["title"], d["kind"], d.get("description", ""), int(d.get("order", 99))))
    return tuple(sorted(out, key=lambda t: t.order))


def get(template_id: str) -> Template | None:
    return next((t for t in templates() if t.id == template_id), None)


def files(template_id: str) -> dict[str, str]:
    """The template's files: {project path: text}."""
    if get(template_id) is None:
        raise ValueError(f"no template {template_id!r}")
    root = TEMPLATES_DIR / template_id
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name == "template.json" or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        out[ids.clean_path(rel)] = p.read_bytes().decode("utf-8")
    return out


def language(path: str) -> str:
    """The editor language of a file (Monaco's ids)."""
    name = Path(path).name.lower()
    ext = Path(name).suffix
    return {
        ".v": "systemverilog",
        ".vh": "systemverilog",
        ".sv": "systemverilog",
        ".svh": "systemverilog",
        ".sdc": "tcl",
        ".tcl": "tcl",
        ".xdc": "tcl",
        ".py": "python",
        ".md": "markdown",
        ".toml": "ini",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".spice": "plaintext",
        ".sp": "plaintext",
        ".cir": "plaintext",
        ".pcf": "plaintext",
    }.get(ext, "plaintext")
