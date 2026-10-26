"""Projects from templates, files through their co-edited documents, snapshots in git."""

from __future__ import annotations

import io
import tarfile

import pytest

from chipova import ids, paths
from chipova.domain.models import LinkAccess, ProjectSettings, Role
from chipova.services import collab, projects, revisions
from tests.conftest import ALICE, BOB


async def test_create_from_template_freezes_the_first_snapshot():
    p = await projects.create("Beat", "digital_heartbeat", ALICE)
    assert ids.is_project(p.id) and p.owner == ALICE.user
    paths_ = [f.path for f in projects.files(p.id)]
    assert "rtl/heartbeat.v" in paths_ and "chipova.toml" in paths_
    rev = revisions.latest(p.id)
    assert rev is not None and ids.is_revision(rev.id)
    assert {e["path"] for e in rev.files} == set(paths_)
    settings, error, _ = projects.settings(p.id)
    assert error == "" and settings.top == "heartbeat" and settings.testbench == "tb_heartbeat"


async def test_same_files_give_the_same_revision_and_edits_a_new_one():
    p = await projects.create("", "digital_heartbeat", ALICE)
    first = revisions.latest(p.id)
    again = await revisions.freeze(p.id, "nothing changed", ALICE)
    assert again.id == first.id
    f = projects.file_by_path(p.id, "rtl/heartbeat.v")
    projects.write(p.id, f.id, projects.read(p.id, f.id).replace("N = 8", "N = 6"), ALICE)
    second = await revisions.freeze(p.id, "smaller counter", ALICE)
    assert second.id != first.id and second.parent == first.id
    diff = revisions.diff(p.id, first, second)
    assert "-    parameter N = 8" in diff and "+    parameter N = 6" in diff
    tar = tarfile.open(fileobj=io.BytesIO(revisions.archive(p.id, second)))
    member = tar.extractfile("src/rtl/heartbeat.v")
    assert b"N = 6" in member.read()
    assert revisions.find(p.id, second.source_sha[:8]).id == second.id


async def test_a_crash_loses_no_typing():
    """Changes are logged as they happen: a server that stops before saving reads them back."""
    p = await projects.create("", "blank_digital", ALICE)
    f = projects.file_by_path(p.id, "rtl/top.v")
    room = collab.room(ids.doc_id(p.id, f.id))
    room.text.insert(0, "// typed just before the crash\n")
    # The crash: the room is gone from memory, nothing was compacted or saved.
    room.close_files()
    collab._rooms.clear()
    collab._timers.clear()
    assert collab.text(p.id, f.id).startswith("// typed just before the crash\n")


async def test_settings_save_refuses_a_stale_form():
    p = await projects.create("", "digital_heartbeat", ALICE)
    s, _, sha = projects.settings(p.id)
    new_sha = projects.save_settings(p.id, s.model_copy(update={"top": "beat2"}), sha, ALICE)
    assert projects.settings(p.id)[0].top == "beat2"
    with pytest.raises(projects.Conflict):
        projects.save_settings(p.id, ProjectSettings(top="other"), sha, ALICE)
    projects.save_settings(p.id, ProjectSettings(top="other"), new_sha, ALICE)


async def test_access_link_and_members():
    p = await projects.create("", "digital_heartbeat", ALICE)
    assert projects.access(p.id, BOB.user).can("edit")  # anyone with the link edits
    projects.set_link_access(p.id, LinkAccess.NONE, ALICE)
    assert not projects.access(p.id, BOB.user).can("view")
    projects.set_member(p.id, BOB.user, Role.REVIEWER, ALICE)
    a = projects.access(p.id, BOB.user)
    assert a.can("approve_release") and not a.can("edit")
    with pytest.raises(projects.Denied):
        projects.set_link_access(p.id, LinkAccess.EDITOR, BOB)
    assert p.id not in {x.id for x in projects.visible_to("someone@else.com")}


async def test_paths_cannot_leave_the_project():
    p = await projects.create("", "blank_digital", ALICE)
    for bad in ["../x.v", "/etc/passwd", "a/../../b", ".hidden", "a\\..\\b", ""]:
        with pytest.raises(ValueError):
            projects.add_file(p.id, bad, "", ALICE)
    projects.add_file(p.id, "rtl/sub/alu.v", "module alu; endmodule\n", ALICE)
    assert (paths.work_dir(p.id) / "rtl/sub/alu.v").read_text() == "module alu; endmodule\n"
