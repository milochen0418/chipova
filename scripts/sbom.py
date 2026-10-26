"""Writes a CycloneDX 1.5 SBOM of Chipova: the Python packages of its environment, the npm packages
of its compiled frontend, the libraries the browser loads, and the tool images with their pinned
bases, recorded tool versions and (for the Debian-based image) every installed package.

    poetry run python scripts/sbom.py [docs/sbom/chipova.cdx.json]

Run it in the environment the app runs in, after a first run (for .web), with Docker up and the
tool images installed (or their part is left out, and said so). Tool versions come from the data
folder's records, or are read from the images (CHIPOVA_HOME may point at a scratch folder)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# In the browser but not an npm package of the frontend (monaco-editor, yjs and y-websocket are:
# Chipova serves Monaco's files itself and bundles Yjs, components/offline.py).
BROWSER = [
    ("y-monaco", "0.1.6", "MIT", "vendored in assets/chipova/collab.js"),
]


def _license(m) -> str:  # noqa: ANN001
    lic = (m.get("License-Expression") or "").strip()
    if not lic:
        lic = (m.get("License") or "").strip().splitlines()[0][:80] if (m.get("License") or "").strip() else ""
    if not lic:
        classifiers = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
        lic = ", ".join(classifiers)
    return lic


def _component(kind: str, name: str, version: str, purl: str, license_: str = "", **extra) -> dict:  # noqa: ANN003
    c = {"type": kind, "name": name, "version": version, "purl": purl, "bom-ref": purl}
    if license_:
        c["licenses"] = [{"license": {"name": license_}}]
    if extra.get("properties"):
        c["properties"] = [{"name": k, "value": str(v)} for k, v in extra["properties"].items()]
    if extra.get("components"):
        c["components"] = extra["components"]
    return c


def python_components() -> list[dict]:
    out = {}
    for d in metadata.distributions():
        name = d.metadata["Name"]
        if name and name.lower() not in out:
            out[name.lower()] = _component("library", name, d.version, f"pkg:pypi/{name.lower()}@{d.version}", _license(d.metadata))
    return [out[k] for k in sorted(out)]


def npm_components() -> list[dict]:
    pkg = ROOT / ".web" / "package.json"
    if not pkg.is_file():
        return []
    deps = json.loads(pkg.read_text()).get("dependencies", {})
    out = []
    for name in sorted(deps):
        meta = ROOT / ".web" / "node_modules" / name / "package.json"
        info = json.loads(meta.read_text()) if meta.is_file() else {}
        version = info.get("version", deps[name])
        lic = info.get("license") if isinstance(info.get("license"), str) else ""
        out.append(_component("library", name, version, f"pkg:npm/{name.replace('@', '%40')}@{version}", lic))
    return out


def browser_components() -> list[dict]:
    return [_component("library", n, v, f"pkg:npm/{n}@{v}", lic, properties={"chipova:loaded-from": src}) for n, v, lic, src in BROWSER]


def image_components() -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    try:
        from chipova.jobs import docker_runner, profiles  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return [], [f"tool images left out: {e}"]
    out = []
    for p in profiles.PROFILES:
        info = docker_runner.image_info(p.image) if docker_runner.available() else None
        if info is None:
            notes.append(f"{p.image} is not installed here: left out")
            continue
        props = {"chipova:profile": p.id, "chipova:image-id": info.get("id", ""), "chipova:base": p.base}
        try:
            code, out_text = docker_runner.run_quick(p.image, ["sh", "-c", "sed -n 's/^ID=//p' /etc/os-release; command -v dpkg-query >/dev/null && dpkg-query -W -f '${Package}\\t${Version}\\n' || true"], timeout=120)
        except Exception:  # noqa: BLE001
            code, out_text = -1, ""
        lines = out_text.splitlines() if code == 0 else []
        distro = lines[0].strip().strip('"') if lines else "debian"
        inner = []
        for line in lines[1:]:
            name, _, version = line.partition("\t")
            if name and version:
                inner.append(_component("library", name, version, f"pkg:deb/{distro}/{name}@{version}"))
        versions = profiles.versions_of(p)  # read from the image when they were never recorded
        for tool, version in sorted(versions.items()):
            inner.append(_component("application", tool, version, f"pkg:generic/{tool}?image={p.image}", properties={"chipova:reported-as": version}))
        if not versions:
            notes.append(f"{p.image}: its tools' versions couldn't be read")
        out.append(_component("container", p.image, p.image.rsplit(":", 1)[-1], f"pkg:docker/{p.image.replace(':', '@', 1)}", properties=props, components=inner))
    return out, notes


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "sbom" / "chipova.cdx.json"
    images, notes = image_components()
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tools": [{"name": "chipova scripts/sbom.py"}],
            "component": _component("application", "chipova", "0.1.0", "pkg:generic/chipova@0.1.0", "MIT"),
            "properties": [{"name": "chipova:note", "value": n} for n in notes],
        },
        "components": [*python_components(), *npm_components(), *browser_components(), *images],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bom, indent=1) + "\n")
    counts = {"python": len(python_components()), "npm": len(npm_components()), "browser": len(BROWSER), "images": len(images)}
    print(f"wrote {target}: {counts}" + ("".join(f"\n  note: {n}" for n in notes)))


if __name__ == "__main__":
    main()
