"""Measurements of real chips (FLOW-POSTSILICON): OpenHTF records are read as OpenHTF writes them,
kept with their snapshot, and lined up with the spec and the design's own values; a simulated
record never counts as a chip; only people who may edit add records, never an AI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from chipova.domain.models import LinkAccess, Role
from chipova.services import api, lab, projects, revisions
from chipova.services.actors import agent
from tests.conftest import ALICE, BOB

FIXTURES = Path(__file__).parent / "fixtures"
PASSING = json.loads((FIXTURES / "openhtf_chip001_pass.json").read_text())
FAILING = json.loads((FIXTURES / "openhtf_chip002_fail.json").read_text())


def test_an_openhtf_record_is_read_as_openhtf_writes_it():
    p = lab.parse(PASSING)
    assert p["dut"] == "CHIP-001" and p["outcome"] == "PASS" and p["test"] == "heartbeat_bench" and not p["simulated"]
    period = next(m for m in p["measurements"] if m["name"] == "pulse_period_us")
    assert period["value"] == 2.561 and period["min"] == 2.5 and period["max"] == 2.62 and period["unit"] == "µs" and period["outcome"] == "PASS"
    with pytest.raises(ValueError):
        lab.parse({"dut_id": "x"})


async def test_real_chips_are_compared_with_the_spec_and_the_design():
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    rev = revisions.latest(p.id)
    lab.add(p.id, "", PASSING, ALICE)
    lab.add(p.id, rev.id[:15], FAILING, ALICE)
    simulated = json.loads(json.dumps(PASSING))
    simulated["metadata"]["simulated"] = True
    lab.add(p.id, "", simulated, ALICE)
    rows = {r["name"]: r for r in lab.compare(p.id)}
    period = rows["pulse_period_us"]
    assert period["pre_silicon"] == 2.56 and period["min"] == 2.5 and period["max"] == 2.62 and "rtl_sim" in period["source"]
    assert period["chips"] == 2 and period["passed"] == 1 and period["low"] == 2.561 and period["high"] == 2.71
    assert period["simulated"] == 1, "a simulated record never counts as a chip"
    assert all(r["revision_id"] == rev.id for r in lab.results(p.id))


async def test_only_people_who_may_edit_add_records():
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    with pytest.raises(projects.Denied):
        lab.add(p.id, "", PASSING, agent("claude-code", on_behalf_of=ALICE.user))
    projects.set_link_access(p.id, LinkAccess.NONE, ALICE)
    projects.set_member(p.id, BOB.user, Role.VIEWER, ALICE)
    with pytest.raises(projects.Denied):
        lab.add(p.id, "", PASSING, BOB)
    assert lab.results(p.id) == []


async def test_a_bench_sends_its_record_through_the_api():
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    routes = [Route(path, handler, methods=[method]) for path, method, handler in api.ROUTES]
    auth = {"Authorization": f"Bearer {api.make_token(ALICE)}"}
    with TestClient(Starlette(routes=routes)) as client:
        sent = client.post(f"/api/projects/{p.id}/lab", headers=auth, json={"snapshot": "", "record": PASSING})
        assert sent.status_code == 200 and sent.json()["dut"] == "CHIP-001", sent.text
        assert client.post(f"/api/projects/{p.id}/lab", headers=auth, json={"record": {"no": "phases"}}).status_code == 400
        got = client.get(f"/api/projects/{p.id}/lab", headers=auth).json()
    assert [r["dut"] for r in got["results"]] == ["CHIP-001"]
    assert {r["name"] for r in got["compare"]} == {"pulse_period_us", "pulse_width_ns"}
