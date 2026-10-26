"""Tool profiles: the container images EDA runs use, and what each one has.

A profile is an image Chipova builds from a Dockerfile in ``infra/dockerfiles/`` on a base pinned
by digest. When it is installed, Chipova records the image's id and the versions its tools
report (in the ``profiles`` table); every run's manifest repeats them, so a result can always be
traced to exactly the tools that made it. A flow names the profiles that can run it, the first
installed one is used, and a flow whose profiles are all missing says so instead of pretending.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field

from chipova import paths
from chipova.db import db
from chipova.jobs import docker_runner

logger = logging.getLogger(__name__)

RE_DDNS_NETWORK = "re_ddns_ddns-net"
PKG_CACHE = "http://pkg-cache:3142"


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    image: str  # the tag runs use
    dockerfile: str  # folder under infra/dockerfiles
    base: str  # the pinned base image
    tools: tuple[str, ...]
    versions: dict[str, list[str]] = field(default_factory=dict)  # tool -> argv printing its version
    size: str = ""
    description: str = ""
    # Big bases are pulled on their own first, with progress (a build hides it).
    pull_base: bool = False


PROFILES: tuple[Profile, ...] = (
    Profile(
        id="eda-base-1",
        title="Chipova EDA base (Debian 13)",
        image="chipova/eda-base:1",
        dockerfile="eda-base",
        base="debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad",
        tools=("iverilog", "verilator", "yosys", "nextpnr-ice40", "icestorm", "nextpnr-ecp5", "prjtrellis", "nextpnr-gowin", "apicula", "ngspice", "graphviz"),
        versions={
            "iverilog": ["iverilog", "-V"],
            "verilator": ["verilator", "--version"],
            "yosys": ["yosys", "-V"],
            "nextpnr-ice40": ["nextpnr-ice40", "--version"],
            "nextpnr-ecp5": ["nextpnr-ecp5", "--version"],
            "nextpnr-gowin": ["nextpnr-gowin", "--version"],
            "prjtrellis": ["dpkg-query", "-W", "-f", "${Version}", "fpga-trellis"],
            "apicula": ["dpkg-query", "-W", "-f", "${Version}", "python3-apycula"],
            "ngspice": ["sh", "-c", "ngspice -v | grep -m1 -i ngspice"],
            "graphviz": ["dot", "-V"],
            "debian": ["cat", "/etc/debian_version"],
        },
        size="about 1.2 GB, built here from Debian packages",
        description="Lint, simulation, synthesis, FPGA place and route (Lattice iCE40 and ECP5, Gowin GW1N), SPICE: Debian's packages, native on Intel and ARM.",
    ),
    Profile(
        id="iic-osic-2026.10",
        title="IIC-OSIC-TOOLS 2026.10",
        image="chipova/eda-osic:2026.10-3",
        dockerfile="eda-osic",
        # The Dockerfile pins it by digest (sha256:306585de…); this tag is what is pulled first.
        base="hpretl/iic-osic-tools:2026.10",
        tools=(
            "siliconcompiler", "openroad", "yosys", "klayout", "magic", "netgen", "ngspice", "xschem",
            "verilator", "iverilog", "nextpnr-ice40", "icestorm", "sky130A", "gf180mcuD", "ihp-sg13g2",
        ),
        versions={
            "siliconcompiler": ["python3", "-c", "import siliconcompiler; print(siliconcompiler.__version__)"],
            "openroad": ["openroad", "-version"],
            "yosys": ["yosys", "-V"],
            "klayout": ["klayout", "-b", "-v"],
            "magic": ["magic", "--version"],
            "netgen": ["sh", "-c", "netgen -batch quit 2>&1 | head -2"],
            "ngspice": ["sh", "-c", "ngspice -v | grep -m1 -i ngspice"],
            "verilator": ["verilator", "--version"],
            "iverilog": ["iverilog", "-V"],
            "pdks": ["sh", "-c", "ls ${PDK_ROOT:-/foss/pdks}"],
            # The PDK data's own versions: open_pdks (the DRC/LVS decks), IHP's commit, and what
            # SiliconCompiler builds with (lambdapdk and which of its PDKs are baked, its IHP data).
            "pdk-data": ["sh", "-c", "echo open_pdks=$(ls /foss/pdks/ciel/sky130/versions | cut -c1-12) ihp-sg13g2=$(cut -c1-12 /foss/pdks/ihp-sg13g2/COMMIT) sc=$(ls /opt/sc-cache/dataroot | tr '\\n' ' ') baked=$(cd /opt/sc-cache/dataroot/lambdapdk-*/lambdapdk && echo */ | tr -d /)"],
            # The IHP chip template Full chip builds (its release tag and commit).
            "ams-template": ["cat", "/opt/chipova/ams-template/.chipova-template"],
        },
        size="about 4 GB to download, 17 GB on disk",
        description="The open-source IC design image of JKU Linz's Institute for Integrated Circuits: OpenROAD, KLayout, Magic, Netgen, Xschem, ngspice and the SkyWater 130, GF180 and IHP SG13G2 PDKs, with SiliconCompiler driving RTL to GDSII.",
        pull_base=True,
    ),
)

_by_id = {p.id: p for p in PROFILES}


def get(profile_id: str) -> Profile | None:
    return _by_id.get(profile_id)


# ------------------------------------------------------------ installed or not


def record(profile_id: str) -> dict:
    row = db().one("SELECT * FROM profiles WHERE id = ?", (profile_id,))
    if not row:
        return {}
    d = dict(row)
    try:
        d["versions"] = json.loads(d.get("versions") or "{}")
    except ValueError:
        d["versions"] = {}
    return d


def installed(profile: Profile) -> dict | None:
    """The local image of the profile ({"id", "digests", ...}), None when it isn't here."""
    try:
        return docker_runner.image_info(profile.image)
    except docker_runner.DockerUnavailable:
        return None


def first_installed(profile_ids: list[str]) -> Profile | None:
    for pid in profile_ids:
        p = get(pid)
        if p is not None and installed(p) is not None:
            return p
    return None


# ------------------------------------------------------------ installing (pull + build)

# profile id -> {"status": "installing" | "done" | "error", "line": "...", "started": t}
progress: dict[str, dict] = {}
_install_lock = threading.Lock()


def _network() -> str | None:
    """The network builds use: the platform's (for the download cache), when there is one."""
    c = docker_runner.client()
    if os.path.exists("/.dockerenv"):
        try:
            own = c.containers.get(socket.gethostname())
            names = list(own.attrs["NetworkSettings"]["Networks"])
            return next((n for n in names if "ddns" in n), names[0] if names else None)
        except Exception:  # noqa: BLE001
            pass
    try:
        c.networks.get(RE_DDNS_NETWORK)
        return RE_DDNS_NETWORK
    except Exception:  # noqa: BLE001
        return None


def _has_pkg_cache() -> bool:
    try:
        return docker_runner.client().containers.get("pkg-cache").status == "running"
    except Exception:  # noqa: BLE001
        return False


def install(profile_id: str) -> None:
    """Builds the profile's image (pulling its base first when it is big) and records its
    versions; progress in ``progress[profile_id]``. Blocking: run it in a thread."""
    profile = get(profile_id)
    if profile is None:
        raise ValueError(f"no profile {profile_id!r}")
    with _install_lock:
        if progress.get(profile_id, {}).get("status") == "installing":
            return
        progress[profile_id] = {"status": "installing", "line": "Starting…", "started": time.time()}
    try:
        c = docker_runner.client()
        if profile.pull_base and docker_runner.image_info(profile.base) is None:
            repo, _, tag = profile.base.partition(":")
            layers: dict[str, tuple[int, int]] = {}
            for event in c.api.pull(repo, tag=tag or "latest", stream=True, decode=True):
                detail = event.get("progressDetail") or {}
                if event.get("id") and detail.get("total"):
                    layers[event["id"]] = (detail.get("current", 0), detail["total"])
                done = sum(cur for cur, _ in layers.values())
                total = sum(tot for _, tot in layers.values())
                if total:
                    progress[profile_id]["line"] = f"Downloading {profile.base}: {done / 1e9:.2f} / {total / 1e9:.2f} GB"
        net = _network()
        args = {"APT_MIRROR": f"{PKG_CACHE}/apt"} if net and _has_pkg_cache() else {}
        if net and _has_pkg_cache():
            args["PIP_INDEX_URL"] = f"{PKG_CACHE}/pypi/simple/"
            args["PIP_TRUSTED_HOST"] = "pkg-cache"
        folder = paths.repo_root() / "infra" / "dockerfiles" / profile.dockerfile
        for event in c.api.build(
            path=str(folder), tag=profile.image, rm=True, decode=True, buildargs=args,
            network_mode=net if args else None, pull=False,
        ):
            if "error" in event:
                raise RuntimeError(str(event["error"]).strip())
            line = str(event.get("stream", "")).strip()
            if line:
                progress[profile_id]["line"] = line[:200]
        probe(profile)
        progress[profile_id] = {"status": "done", "line": "Installed", "started": progress[profile_id]["started"]}
    except Exception as e:  # noqa: BLE001 — shown on the settings page
        logger.exception("Installing profile %s failed", profile_id)
        progress[profile_id] = {"status": "error", "line": str(e)[:500], "started": progress.get(profile_id, {}).get("started", time.time())}
        db().execute(
            "INSERT INTO profiles(id, status, detail) VALUES(?, 'error', ?) ON CONFLICT(id) DO UPDATE SET status = 'error', detail = excluded.detail",
            (profile_id, str(e)[:2000]),
        )


def probe_in_background(profile_id: str) -> None:
    """Reads an installed image's tool versions in a thread (they were never recorded here),
    showing it like an install in ``progress``."""
    profile = get(profile_id)
    with _install_lock:
        if profile is None or progress.get(profile_id, {}).get("status") == "installing":
            return
        progress[profile_id] = {"status": "installing", "line": "Reading the tools' versions…", "started": time.time()}

    def work() -> None:
        try:
            probe(profile)
            progress[profile_id] = {"status": "done", "line": "", "started": time.time()}
        except Exception as e:  # noqa: BLE001
            progress[profile_id] = {"status": "error", "line": str(e)[:500], "started": time.time()}

    threading.Thread(target=work, daemon=True, name=f"probe-{profile_id}").start()


def probe(profile: Profile) -> dict:
    """Reads the tools' versions in the installed image and records them with its id."""
    info = docker_runner.image_info(profile.image)
    if info is None:
        raise RuntimeError(f"{profile.image} is not installed")
    versions: dict[str, str] = {}
    for tool, argv in profile.versions.items():
        try:
            code, out = docker_runner.run_quick(profile.image, argv)
        except Exception as e:  # noqa: BLE001
            code, out = -1, str(e)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        text = (" ".join(lines) if tool == "pdks" else (lines[0] if lines else ""))[:200]
        versions[tool] = text if code == 0 else f"(unavailable: {text[:80]})"
    base = docker_runner.image_info(profile.base)
    row = {
        "id": profile.id,
        "image": profile.image,
        "image_id": info["id"],
        "digest": (base or {}).get("digests", [""])[0] if base and base.get("digests") else profile.base,
        "versions": json.dumps(versions, sort_keys=True),
        "installed_at": time.time(),
        "status": "installed",
        "detail": "",
    }
    db().execute(
        "INSERT INTO profiles(id, image, image_id, digest, versions, installed_at, status, detail) "
        "VALUES(:id, :image, :image_id, :digest, :versions, :installed_at, :status, :detail) "
        "ON CONFLICT(id) DO UPDATE SET image = excluded.image, image_id = excluded.image_id, digest = excluded.digest, "
        "versions = excluded.versions, installed_at = excluded.installed_at, status = excluded.status, detail = ''",
        row,
    )
    return versions


def versions_of(profile: Profile) -> dict:
    """The recorded versions, probing once when the image is here but was never probed (built
    by hand, say)."""
    rec = record(profile.id)
    info = installed(profile)
    if info is None:
        return {}
    if rec.get("image_id") != info["id"] or not rec.get("versions"):
        try:
            return probe(profile)
        except Exception:  # noqa: BLE001
            logger.exception("Reading the versions of %s failed", profile.id)
            return {}
    return rec["versions"]
