"""Signoff never says PASS without evidence on that snapshot; releases are gated (AC-07, AC-11)."""

from __future__ import annotations

import time
import zipfile

import pytest

from chipova import ids
from chipova.db import db
from chipova.domain.models import ApprovalStatus, ReleaseStatus, Role, Run, RunStatus, SignoffStatus
from chipova.services import projects, releases, revisions, signoff
from chipova.services.actors import agent
from tests.conftest import ALICE, BOB, CAROL


def fake_run(project_id: str, revision_id: str, flow: str, status: RunStatus, summary: dict | None = None, problems: dict | None = None) -> Run:
    """A finished run's record, as the engine leaves it (no container needed)."""
    r = Run(
        id=ids.new_run_id(), project_id=project_id, revision_id=revision_id, flow_id=flow, status=status,
        approval_status=ApprovalStatus.NONE, created_at=time.time(), ended_at=time.time(),
        summary=summary or {}, problems=problems or {"errors": 0, "warnings": 0},
    )
    db().insert("runs", r.model_dump(mode="json"))
    return r


def by_cat(checks):
    return {c.category: c for c in checks}


async def test_checks_come_only_from_runs_on_that_snapshot():
    p = await projects.create("", "digital_heartbeat", ALICE)
    rev = revisions.latest(p.id)
    checks = by_cat(signoff.checklist(p.id, rev.id))
    assert checks["sim"].status == SignoffStatus.NOT_RUN
    # No DRC deck / ASIC flow set up here: BLOCKED, never PASS (AC-07).
    assert checks["drc"].status == SignoffStatus.BLOCKED and checks["drc"].required
    assert checks["pex"].status == SignoffStatus.NOT_CONFIGURED and not checks["pex"].required
    fake_run(p.id, rev.id, "rtl_sim", RunStatus.SUCCEEDED, {"pass_lines": 1, "fail_lines": 0})
    assert by_cat(signoff.checklist(p.id, rev.id))["sim"].status == SignoffStatus.PASS
    # A newer snapshot has proved nothing yet.
    f = projects.file_by_path(p.id, "rtl/heartbeat.v")
    projects.write(p.id, f.id, projects.read(p.id, f.id) + "\n// changed\n", ALICE)
    rev2 = await revisions.freeze(p.id, "changed", ALICE)
    assert by_cat(signoff.checklist(p.id, rev2.id))["sim"].status == SignoffStatus.NOT_RUN
    fake_run(p.id, rev2.id, "rtl_sim", RunStatus.SUCCEEDED, {"pass_lines": 1, "fail_lines": 2})
    assert by_cat(signoff.checklist(p.id, rev2.id))["sim"].status == SignoffStatus.FAIL


async def test_waivers_need_a_reason_and_another_approver_and_never_pass():
    p = await projects.create("", "digital_heartbeat", ALICE)
    projects.set_member(p.id, CAROL.user, Role.REVIEWER, ALICE)
    rev = revisions.latest(p.id)
    with pytest.raises(ValueError):
        signoff.request_waiver(p.id, rev.id, "drc", "", "short", ALICE)
    with pytest.raises(projects.Denied):
        signoff.request_waiver(p.id, rev.id, "drc", "", "an AI can't waive anything at all", agent("x"))
    w = signoff.request_waiver(p.id, rev.id, "drc", "met.1", "Known false positive on the test structure, checked by hand", ALICE)
    with pytest.raises(projects.Denied):
        signoff.decide_waiver(w.id, True, ALICE)  # the requester
    signoff.decide_waiver(w.id, True, CAROL)
    drc = by_cat(signoff.checklist(p.id, rev.id))["drc"]
    assert drc.status == SignoffStatus.WAIVED and drc.waivers[0].approved_by == CAROL.user


async def test_a_release_is_gated_and_lists_what_is_missing():
    p = await projects.create("", "fpga_blinky", ALICE)
    projects.set_member(p.id, CAROL.user, Role.REVIEWER, ALICE)
    rev = revisions.latest(p.id)
    r = releases.create(p.id, "", "First bitstream", ALICE)
    releases.request_review(r.id, ALICE)
    with pytest.raises(projects.Denied):
        releases.approve(r.id, ALICE)  # the requester
    with pytest.raises(projects.Conflict) as e:
        releases.approve(r.id, CAROL)
    assert "Functional simulation" in str(e.value) and "FPGA timing" in str(e.value)
    assert releases.get(r.id).status == ReleaseStatus.IN_REVIEW
    fake_run(p.id, rev.id, "rtl_sim", RunStatus.SUCCEEDED, {"pass_lines": 1, "fail_lines": 0})
    fake_run(p.id, rev.id, "fpga_ice40", RunStatus.SUCCEEDED, {"fmax": {"CLK": {"achieved_mhz": 90.0, "constraint_mhz": 12.0}}})
    done = releases.approve(r.id, CAROL, "looks good")
    assert done.status == ReleaseStatus.APPROVED
    # Never FOUNDRY_READY by itself; only an owner, with a real statement.
    with pytest.raises(ValueError):
        releases.mark_foundry_ready(r.id, ALICE, "ok")
    with pytest.raises(projects.Denied):
        releases.mark_foundry_ready(r.id, CAROL, "Checked by the foundry liaison against their rule list v3.")
    pkg = releases.build_package(r.id, ALICE)
    with zipfile.ZipFile(releases.package_path(pkg)) as z:
        names = z.namelist()
    assert "RELEASE_MANIFEST.json" in names and "source/rtl/blinky.v" in names and "approval.json" in names


async def test_an_asic_release_without_lvs_is_blocked():
    p = await projects.create("", "digital_heartbeat", ALICE)
    projects.set_member(p.id, BOB.user, Role.REVIEWER, ALICE)
    rev = revisions.latest(p.id)
    fake_run(p.id, rev.id, "rtl_sim", RunStatus.SUCCEEDED, {"pass_lines": 1, "fail_lines": 0})
    r = releases.create(p.id, rev.id, "", ALICE)
    releases.request_review(r.id, ALICE)
    ok, missing = releases.gate(releases.get(r.id))
    assert not ok and any(m.startswith("LVS") for m in missing) and any(m.startswith("Approval") for m in missing)


async def test_compare_lines_up_two_builds_numbers():
    """Comparing two runs shows their PPA side by side (blueprint Phase 2), not only their inputs."""
    from chipova.jobs import engine  # noqa: PLC0415

    p = await projects.create("", "digital_heartbeat", ALICE)
    rev = revisions.latest(p.id)
    labels = {"cells": "Cells", "fmax_mhz": "Fmax (MHz)"}
    a = fake_run(p.id, rev.id, "asic_sc", RunStatus.SUCCEEDED, {"_labels": labels, "headline": "76 cells", "cells": 76, "fmax_mhz": 253.2, "pdk": "skywater130"})
    b = fake_run(p.id, rev.id, "asic_sc", RunStatus.SUCCEEDED, {"_labels": labels, "headline": "99 cells", "cells": 99, "fmax_mhz": 253.2, "pdk": "skywater130"})
    rows = {r["what"]: r for r in engine.compare(a, b)}
    assert rows["Cells"]["a"] == 76 and rows["Cells"]["b"] == 99 and not rows["Cells"]["same"]
    assert rows["Fmax (MHz)"]["same"] and rows["pdk"]["same"]
    assert "headline" not in rows and "_labels" not in rows
