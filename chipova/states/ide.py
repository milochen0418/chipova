"""One tab's own part of a project: who it is there (its access), which view it shows, the files
it has open, and what it asks for (snapshots, runs). Nothing in here is shared with the other
tabs; what they all see is the project's room (:mod:`chipova.states.room`).
"""

from __future__ import annotations

import json

import reflex as rx

from chipova import ids
from chipova.domain import roles
from chipova.jobs import engine, flows
from chipova.services import audit, collab, presence, projects, revisions, templates
from chipova.states.room import EVERYTHING, ProjectRoom, note, publish, push_later
from chipova.states.ui_state import UiState

VIEWS = ("code", "verify", "implement", "layout", "signoff", "release", "agents", "settings")


class IdeState(rx.State):
    project_id: str = ""
    missing: bool = False
    denied: bool = False
    role: str = ""
    can_edit: bool = False
    can_snapshot: bool = False
    can_run: bool = False
    can_decide: bool = False
    can_review: bool = False
    can_manage: bool = False
    # Lets this tab's editor join the files' co-editing (assets/chipova/collab.js).
    ticket: str = ""
    view: str = "code"
    open_tabs: list[str] = []
    active_file: str = ""
    active_path: str = ""
    active_lang: str = "plaintext"
    bottom: str = "problems"
    bottom_open: bool = True
    right: str = "ai"
    right_open: bool = True
    # Dialogs.
    new_file_open: bool = False
    new_file_path: str = ""
    rename_id: str = ""
    rename_path: str = ""
    delete_id: str = ""
    delete_path: str = ""
    snapshot_open: bool = False
    snapshot_message: str = ""
    # A run asked for while the editors differ from the latest snapshot: {"flow", "title"}.
    run_ask: dict[str, str] = {}

    # -------------------------------------------------------- arriving

    @rx.event
    async def on_load_project(self):
        pid = str(self.router._page.params.get("project_id", "") or "")
        ui = await self.get_state(UiState)
        actor = await ui._identify()
        view = str(self.router._page.params.get("view", "") or "")
        project = projects.get(pid)
        room = await self.get_state(ProjectRoom)
        if project is None:
            self.missing, self.denied = True, False
            return await self._leave(room)
        access = projects.access_of(project, actor)
        if not access.can(roles.VIEW):
            audit.denied(roles.VIEW, actor, pid, pid, "opened a project without access")
            self.missing, self.denied = False, True
            return await self._leave(room)
        changed = self.project_id != pid
        self.missing = self.denied = False
        self.project_id = pid
        self.role = access.label
        self.can_edit = access.can(roles.EDIT)
        self.can_snapshot = access.can(roles.SNAPSHOT)
        self.can_run = access.can(roles.RUN)
        self.can_decide = access.can(roles.DECIDE_PROPOSAL)
        self.can_review = access.can(roles.REVIEW)
        self.can_manage = access.can(roles.MANAGE)
        self.ticket = collab.make_ticket(actor.user, actor.name, pid)
        if view in VIEWS:
            self.view = view
        if changed:
            self.open_tabs, self.active_file = [], ""
            self.view = view if view in VIEWS else "code"
            self.run_ask = {}
        # _link_to returns the room's state, linked into this tab's tree: change that one.
        linked = await room._link_to(pid)
        linked.project_id = pid
        linked.gone = False
        publish(linked, pid, EVERYTHING)
        if not self.active_file:
            self._open_default(pid)
        # What this event changes reaches only this tab: the others hear about it in the
        # follow-up events (Reflex passes a room's changes on from events that start linked).
        return [
            IdeState.join_room,
            rx.call_script(f"document.title = {json.dumps(project.title + ' · Chipova')}"),
        ]

    def _open_default(self, pid: str) -> None:
        s, _, _ = projects.settings(pid)
        files = projects.files(pid)
        pick = next((f for f in files if s.rtl and f.path == s.rtl[0]), None)
        pick = pick or next((f for f in files if f.path.endswith((".v", ".sv", ".spice"))), None)
        pick = pick or next((f for f in files if f.path == "README.md"), None)
        pick = pick or (files[0] if files else None)
        if pick is not None:
            self._open(pick.id, pick.path)

    async def _leave(self, room: ProjectRoom):
        left = presence.leave(self.router.session.client_token)
        if left:
            push_later(left, "people", "files")
        self.project_id = ""
        try:
            return await room._unlink()
        except Exception:  # noqa: BLE001 — not linked
            return None

    @rx.event
    async def leave_project(self):
        """Back on the project list: the others stop seeing this tab."""
        self.missing = self.denied = False
        return await self._leave(await self.get_state(ProjectRoom))

    async def _here(self) -> tuple[UiState, str]:
        ui = await self.get_state(UiState)
        room = await self.get_state(ProjectRoom)
        pid = self.project_id
        if not pid or self.missing or self.denied or room._linked_to != pid:
            return ui, ""
        return ui, pid

    @rx.event
    async def join_room(self):
        """Shows this tab among the people in the project, to everyone in it."""
        ui, pid = await self._here()
        if not pid:
            return
        me = ui.me
        left, color = presence.join(pid, ui.router.session.client_token, me["peer"], me["user"], me["name"], me.get("avatar", ""))
        ui._set_color(color)
        presence.prune(pid)
        room = await self.get_state(ProjectRoom)
        publish(room, pid, {"people", "files"})
        note(pid, me["name"], "opened the project", "people")
        if left:
            push_later(left, "people", "files")

    @rx.event
    async def ping(self):
        """Still here (every 5 s): keeps this tab among the people and drops the tabs gone."""
        ui, pid = await self._here()
        if not pid:
            return
        token = ui.router.session.client_token
        if not presence.touch(pid, token):
            await ui._identify()
            me = ui.me
            _, color = presence.join(pid, token, me["peer"], me["user"], me["name"], me.get("avatar", ""))
            ui._set_color(color)
        if presence.prune(pid):
            push_later(pid, "people", "files")
        room = await self.get_state(ProjectRoom)
        publish(room, pid, {"people"})

    # -------------------------------------------------------- views and tabs

    @rx.event
    def set_view(self, view: str):
        from chipova.states.runs_state import RunState  # noqa: PLC0415

        if view in VIEWS:
            self.view = view
            return RunState.select_for(view)
        return None

    @rx.event
    def set_bottom(self, tab: str):
        self.bottom = tab
        self.bottom_open = True

    @rx.event
    def toggle_bottom(self):
        self.bottom_open = not self.bottom_open

    @rx.event
    def set_right(self, tab: str):
        if self.right == tab and self.right_open:
            self.right_open = False
        else:
            self.right, self.right_open = tab, True

    def _open(self, file_id: str, path: str) -> None:
        if file_id not in self.open_tabs:
            self.open_tabs = [*self.open_tabs, file_id][-12:]
        self.active_file = file_id
        self.active_path = path
        self.active_lang = templates.language(path)

    @rx.event
    async def open_file(self, file_id: str):
        from chipova.states.review_state import ReviewState  # noqa: PLC0415
        from chipova.states.snapshot_state import SnapshotState  # noqa: PLC0415

        entry = projects.file_by_id(self.project_id, file_id)
        if entry is None:
            return rx.toast.error("That file is gone.", position="bottom-right")
        self._open(entry.id, entry.path)
        self.view = "code"
        (await self.get_state(SnapshotState)).open_id = ""
        (await self.get_state(ReviewState)).open_id = ""
        return None

    @rx.event
    def close_tab(self, file_id: str):
        tabs = [t for t in self.open_tabs if t != file_id]
        self.open_tabs = tabs
        if self.active_file == file_id:
            nxt = projects.file_by_id(self.project_id, tabs[-1]) if tabs else None
            if nxt is not None:
                self._open(nxt.id, nxt.path)
            else:
                self.active_file, self.active_path = "", ""

    @rx.event
    def jump(self, path: str, line: int, column: int = 1):
        """Opens a file at a line (a problem, a log line)."""
        if not path:
            return None
        entry = projects.file_by_path(self.project_id, path)
        if entry is None:
            return rx.toast.info(f"{path} isn't a file of the project.", position="bottom-right")
        self._open(entry.id, entry.path)
        self.view = "code"
        return rx.call_script(f"window.chipReveal && window.chipReveal({json.dumps(entry.id)}, {int(line or 1)}, {int(column or 1)})")

    # -------------------------------------------------------- files

    async def _actor(self):
        ui = await self.get_state(UiState)
        return ui.actor()

    @rx.event
    def open_new_file(self):
        self.new_file_open, self.new_file_path = True, "rtl/"

    @rx.event
    def set_new_file_open(self, value: bool):
        self.new_file_open = value

    @rx.event
    def set_new_file_path(self, value: str):
        self.new_file_path = value

    @rx.event
    async def create_file(self):
        actor = await self._actor()
        path = self.new_file_path.strip()
        try:
            entry = projects.add_file(self.project_id, path, _starter(path), actor)
        except (ValueError, projects.Conflict, projects.Denied) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.new_file_open = False
        self._open(entry.id, entry.path)
        note(self.project_id, actor.name, f"added {entry.path}")
        push_later(self.project_id, "files", "latest")

    @rx.event
    def ask_rename(self, file_id: str, path: str):
        self.rename_id, self.rename_path = file_id, path

    @rx.event
    def set_rename_path(self, value: str):
        self.rename_path = value

    @rx.event
    def cancel_rename(self):
        self.rename_id = ""

    @rx.event
    async def rename_file(self):
        actor = await self._actor()
        try:
            entry = projects.rename_file(self.project_id, self.rename_id, self.rename_path, actor)
        except (ValueError, projects.Conflict, projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right")
        if self.active_file == entry.id:
            self._open(entry.id, entry.path)
        self.rename_id = ""
        note(self.project_id, actor.name, f"renamed a file to {entry.path}")
        push_later(self.project_id, "files", "latest")

    @rx.event
    def ask_delete(self, file_id: str, path: str):
        self.delete_id, self.delete_path = file_id, path

    @rx.event
    def cancel_delete(self):
        self.delete_id = ""

    @rx.event
    async def delete_file(self):
        actor = await self._actor()
        file_id, self.delete_id = self.delete_id, ""
        try:
            projects.delete_file(self.project_id, file_id, actor)
        except (projects.Conflict, projects.Denied) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.open_tabs = [t for t in self.open_tabs if t != file_id]
        if self.active_file == file_id:
            self.active_file, self.active_path = "", ""
            self._open_default(self.project_id)
        note(self.project_id, actor.name, f"deleted {self.delete_path}")
        push_later(self.project_id, "files", "latest")

    # -------------------------------------------------------- snapshots

    @rx.event
    def open_snapshot(self):
        self.snapshot_open, self.snapshot_message = True, ""

    @rx.event
    def set_snapshot_open(self, value: bool):
        self.snapshot_open = value

    @rx.event
    def set_snapshot_message(self, value: str):
        self.snapshot_message = value

    @rx.event
    async def freeze(self):
        actor = await self._actor()
        try:
            rev = await revisions.freeze(self.project_id, self.snapshot_message or "Snapshot", actor)
        except (projects.Denied, RuntimeError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        self.snapshot_open = False
        note(self.project_id, actor.name, f"froze snapshot {ids.short_revision(rev.id)}", "snapshot")
        push_later(self.project_id, "latest")
        return rx.toast.success(f"Snapshot {ids.short_revision(rev.id)}: {rev.message}", position="bottom-right")

    # -------------------------------------------------------- runs

    @rx.event
    async def start_run(self, flow_id: str):
        """Runs a flow on the latest snapshot; when the editors changed since, asks first
        whether to freeze them (blueprint 4.2)."""
        flow = flows.get(flow_id)
        if flow is None:
            return None
        # Whether the editors differ from the latest snapshot, as they are now (the room's flag
        # follows saves, a moment behind the typing).
        latest = revisions.latest(self.project_id)
        if latest is None or revisions.differs_from_working(self.project_id, latest, projects.working_copy(self.project_id)):
            self.run_ask = {"flow": flow_id, "title": flow.definition.title}
            return None
        return await self._submit(flow_id, latest.id)

    @rx.event
    def cancel_run_ask(self):
        self.run_ask = {}

    @rx.event
    async def run_frozen(self):
        """Freezes the editors' text, then runs the flow on it."""
        flow_id = self.run_ask.get("flow", "")
        self.run_ask = {}
        actor = await self._actor()
        try:
            rev = await revisions.freeze(self.project_id, f"For {flows.get(flow_id).definition.title}", actor)  # type: ignore[union-attr]
        except (projects.Denied, RuntimeError, AttributeError) as e:
            return rx.toast.error(str(e), position="bottom-right")
        note(self.project_id, actor.name, f"froze snapshot {ids.short_revision(rev.id)}", "snapshot")
        push_later(self.project_id, "latest")
        return await self._submit(flow_id, rev.id)

    @rx.event
    async def run_latest(self):
        flow_id = self.run_ask.get("flow", "")
        self.run_ask = {}
        latest = revisions.latest(self.project_id)
        if latest is None:
            return rx.toast.error("The project has no snapshot yet.", position="bottom-right")
        return await self._submit(flow_id, latest.id)

    async def _submit(self, flow_id: str, revision_id: str, params: dict | None = None):
        from chipova.states.runs_state import RunState  # noqa: PLC0415

        actor = await self._actor()
        try:
            run = await engine.submit(self.project_id, flow_id, actor, revision=revision_id, params=params or {})
        except (flows.FlowError, projects.Denied, projects.NotFound) as e:
            return rx.toast.error(str(e), position="bottom-right", duration=8000)
        flow = flows.get(flow_id)
        note(self.project_id, actor.name, f"started {flow.definition.title if flow else flow_id} on {ids.short_revision(run.revision_id)}", "run")
        push_later(self.project_id, "runs")
        if self.view == "code":
            self.bottom, self.bottom_open = "output", True
        return [
            RunState.select(run.id),
            rx.toast.info(f"{flow.definition.title if flow else flow_id}: run {run.id} queued", position="bottom-right"),
        ]


def _starter(path: str) -> str:
    """What a new file starts with."""
    name = path.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    if name.endswith((".v", ".sv")) and ids.is_identifier(stem):
        if stem.startswith("tb_"):
            return f"`timescale 1ns / 1ps\nmodule {stem};\n    initial begin\n        $dumpfile(\"wave.vcd\");\n        $dumpvars(0, {stem});\n        #10;\n        $display(\"PASS {stem}\");\n        $finish;\n    end\nendmodule\n"
        return f"module {stem} (\n    input  wire clk,\n    input  wire nreset\n);\n\nendmodule\n"
    if name.endswith(".sdc"):
        return "create_clock -name clk -period 10 [get_ports {clk}]\n"
    return ""
