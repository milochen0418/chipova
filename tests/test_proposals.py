"""AI proposals: people decide, nothing is overwritten silently (AC-02, AC-03)."""

from __future__ import annotations

import pytest

from chipova.domain.models import ApprovalStatus
from chipova.services import audit, projects, proposals, revisions
from chipova.services.actors import agent
from tests.conftest import ALICE, BOB

BOT = agent("claude-code", on_behalf_of=ALICE.user)


async def _project():
    p = await projects.create("", "digital_heartbeat", ALICE)
    f = projects.file_by_path(p.id, "rtl/heartbeat.v")
    return p, f


async def test_rejecting_keeps_the_source_and_the_reason():
    p, f = await _project()
    before = projects.read(p.id, f.id)
    a = proposals.propose(p.id, BOT, "Wider counter", [{"path": "rtl/heartbeat.v", "content": before.replace("N = 8", "N = 16")}], "more range")
    assert a.status == ApprovalStatus.PROPOSED and a.base_revision == revisions.latest(p.id).id
    with pytest.raises(ValueError):
        proposals.reject(a.id, BOB, "")  # a reason is needed
    r = proposals.reject(a.id, BOB, "N must stay 8 for the demo")
    assert r.status == ApprovalStatus.REJECTED and r.reason == "N must stay 8 for the demo" and r.decided_by == BOB.user
    assert projects.read(p.id, f.id) == before
    assert any(e.action == "proposal.reject" for e in audit.entries(p.id))


async def test_accepting_applies_it_and_freezes_a_snapshot():
    p, f = await _project()
    before_rev = revisions.latest(p.id)
    text = projects.read(p.id, f.id).replace("N = 8", "N = 10")
    a = proposals.propose(p.id, BOT, "N = 10", [
        {"path": "rtl/heartbeat.v", "content": text},
        {"path": "docs/notes.md", "content": "# Notes\n"},
    ])
    done = await proposals.accept(a.id, BOB)
    assert done.status == ApprovalStatus.APPROVED and done.decided_by == BOB.user
    assert projects.read(p.id, f.id) == text
    assert projects.file_by_path(p.id, "docs/notes.md") is not None
    rev = revisions.get(p.id, done.applied_revision)
    assert rev is not None and rev.id != before_rev.id and a.id in rev.message
    with pytest.raises(Exception):
        await proposals.accept(a.id, BOB)  # decided already


async def test_people_editing_meanwhile_are_merged_or_stop_it():
    p, f = await _project()
    base = projects.read(p.id, f.id)
    a = proposals.propose(p.id, BOT, "N = 12", [{"path": "rtl/heartbeat.v", "content": base.replace("N = 8", "N = 12")}])
    # Someone edits another part of the file meanwhile: merged.
    projects.write(p.id, f.id, base.replace("// Heartbeat:", "// The heartbeat:"), BOB)
    await proposals.accept(a.id, ALICE)
    now = projects.read(p.id, f.id)
    assert "N = 12" in now and "// The heartbeat:" in now
    # Someone edits the very line the AI changes: refused, nothing applied.
    b = proposals.propose(p.id, BOT, "N = 14", [{"path": "rtl/heartbeat.v", "content": now.replace("N = 12", "N = 14")}])
    projects.write(p.id, f.id, now.replace("N = 12", "N = 13"), BOB)
    with pytest.raises(projects.Conflict):
        await proposals.accept(b.id, ALICE)
    assert "N = 13" in projects.read(p.id, f.id)
    assert proposals.get(b.id).status == ApprovalStatus.PROPOSED


async def test_an_ai_cannot_decide_on_proposals():
    p, f = await _project()
    a = proposals.propose(p.id, BOT, "x", [{"path": "rtl/heartbeat.v", "content": "module heartbeat; endmodule\n"}])
    with pytest.raises(projects.Denied):
        await proposals.accept(a.id, BOT)
    with pytest.raises(projects.Denied):
        proposals.reject(a.id, BOT, "no")
    assert any(e.decision == "denied" for e in audit.entries(p.id))


async def test_proposals_cannot_reach_outside_the_project():
    p, _ = await _project()
    for bad in [{"path": "../../etc/passwd", "content": "x"}, {"path": "/abs.v", "content": "x"}, {"path": "rtl/heartbeat.v"}]:
        with pytest.raises(ValueError):
            proposals.propose(p.id, BOT, "bad", [bad])
