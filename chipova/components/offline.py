"""The editor's libraries from Chipova itself, never from a CDN, so editing works on a network
without internet (the blueprint's LAN-first):

- Monaco: the npm package Reflex installs (pinned to the version @monaco-editor/react's loader
  was made for), its own build served by the backend under ``/_chipova/monaco/<version>/vs``; the
  page's module code points the loader there before the first editor mounts;
- Yjs and y-websocket: bundled into the page, and handed to ``assets/chipova/collab.js`` on
  ``window.__chipYjs`` (one Yjs for both, as y-websocket needs).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import reflex as rx
from reflex.constants import Dirs
from reflex.utils.imports import ImportVar
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

logger = logging.getLogger(__name__)

# What @monaco-editor/loader 1.7 loads by default (from jsDelivr); the same build, served here.
MONACO_VERSION = "0.55.1"
YJS = "yjs@13.6.18"
Y_WEBSOCKET = "y-websocket@2.0.4"
MONACO_PATH = "/_chipova/monaco/{version}/{path:path}"
_TYPES = {".js": "text/javascript", ".css": "text/css", ".ttf": "font/ttf", ".json": "application/json", ".map": "application/json"}


class EditorLibraries(rx.Fragment):
    """Renders nothing: its module code sets up Monaco's loader and Yjs for the page."""

    lib_dependencies: list[str] = [f"monaco-editor@{MONACO_VERSION}", Y_WEBSOCKET]

    def add_imports(self):  # noqa: ANN201
        return {
            "@monaco-editor/react": ImportVar(tag="loader"),
            YJS: ImportVar(tag="*", alias="Y", is_default=True),
            Y_WEBSOCKET: ImportVar(tag="WebsocketProvider"),
            f"$/{Dirs.STATE_PATH}": "getBackendURL",
            "$/env.json": ImportVar(tag="env", is_default=True),
        }

    def add_custom_code(self) -> list[str]:
        return [
            "if (typeof window !== 'undefined') {"
            f" loader.config({{ paths: {{ vs: new URL('/_chipova/monaco/{MONACO_VERSION}/vs', getBackendURL(env.UPLOAD)).href }} }});"
            " window.__chipYjs = { Y, WebsocketProvider };"
            " }"
        ]


editor_libraries = EditorLibraries.create


def _root() -> Path:
    from reflex.utils.prerequisites import get_web_dir  # noqa: PLC0415

    return Path(get_web_dir()) / "node_modules" / "monaco-editor" / "min"


_checked = False


def _check_version(root: Path) -> None:
    global _checked
    if _checked:
        return
    _checked = True
    try:
        have = json.loads((root.parent / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return
    if have != MONACO_VERSION:
        logger.warning("monaco-editor %s is installed, the editor expects %s", have, MONACO_VERSION)


async def monaco_file(request: Request) -> Response:
    root = _root().resolve()
    target = (root / request.path_params.get("path", "")).resolve()
    if root not in target.parents or not target.is_file():
        return JSONResponse({"error": "no such file"}, status_code=404)
    _check_version(root)
    return FileResponse(
        target,
        media_type=_TYPES.get(target.suffix, "application/octet-stream"),
        # The version is in the path, so a file never changes; fonts need CORS across ports.
        headers={"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"},
    )


def register_routes(app) -> None:  # noqa: ANN001 - Reflex App
    api = app._api
    if not any(getattr(r, "path", None) == MONACO_PATH for r in api.routes):
        api.add_route(MONACO_PATH, monaco_file, methods=["GET"])
