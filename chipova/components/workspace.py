"""A project's page (/p/<id>): the top bar, the navigation rail of the blueprint's sections, the
section on screen, and the dialogs they share."""

from __future__ import annotations

import reflex as rx
from reflex_ddns_auth.intent import Intent

from chipova.components.common import BTN_AI, BTN_GHOST, BTN_OUTLINE, BTN_PRIMARY, INPUT, logo
from chipova.components.together import call_button, identity, incoming_call, page_hooks, presence
from chipova.jobs import flows
from chipova.states.comments_state import CommentsState
from chipova.states.ide import IdeState
from chipova.states.review_state import ReviewState
from chipova.states.room import ProjectRoom

SECTIONS = [
    ("code", "code-xml", "Code", "The files, edited together"),
    ("verify", "flask-conical", "Verify", "Lint, simulation, waveforms, tests"),
    ("implement", "cpu", "Implement", "Synthesis, FPGA, RTL to GDSII, PPA"),
    ("layout", "layers", "Layout", "The GDS: layers, cells, measuring, notes"),
    ("signoff", "shield-check", "Signoff", "DRC, LVS, STA and the rest, with evidence"),
    ("release", "package", "Release", "Tape-out preparation packages and approvals"),
    ("agents", "bot", "Agents", "What AI agents proposed and did"),
    ("settings", "settings-2", "Settings", "Run settings, members, AI rules"),
]

CATEGORY_TITLES = {"verify": "Verify", "implement": "Implement", "signoff": "Signoff", "ams": "Analog"}


def ai_button() -> rx.Component:
    """Opens the AI Hub's assistant on this project (the ai.assist intent)."""
    return rx.el.button(
        rx.icon("sparkles", class_name="w-3.5 h-3.5"),
        rx.el.span("AI"),
        rx.cond(
            ProjectRoom.pending_proposals > 0,
            rx.el.span(ProjectRoom.pending_proposals, id="ai-pending", class_name="ml-0.5 min-w-[1.1rem] h-[1.1rem] px-1 rounded-full bg-white text-violet-700 text-[10px] font-bold flex items-center justify-center"),
        ),
        on_click=Intent.start(None, "ai.assist", keep_alive=True, single=True, label="AI assistant", in_app="chipova", room=IdeState.project_id),
        title="Ask the AI Hub's assistant to work on this project (it proposes; you decide)",
        id="ai-button",
        class_name=BTN_AI,
    )


def run_menu() -> rx.Component:
    groups = {}
    for d in flows.definitions():
        groups.setdefault(d.category, []).append(d)
    items: list[rx.Component] = []
    for cat, defs in groups.items():
        if items:
            items.append(rx.menu.separator())
        items.append(rx.el.div(CATEGORY_TITLES.get(cat, cat.title()), class_name="px-2 pt-1.5 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500"))
        for d in defs:
            items.append(rx.menu.item(d.title, on_select=IdeState.start_run(d.id), disabled=~IdeState.can_run, custom_attrs={"data-flow": d.id}))
    return rx.menu.root(
        rx.menu.trigger(
            rx.el.button(rx.icon("play", class_name="w-3.5 h-3.5"), rx.el.span("Run"), rx.icon("chevron-down", class_name="w-3 h-3 opacity-70"), id="run-menu", class_name=BTN_PRIMARY, disabled=~IdeState.can_run),
        ),
        rx.menu.content(*items),
    )


def snapshot_chip() -> rx.Component:
    return rx.el.button(
        rx.icon("git-commit-horizontal", class_name="w-3.5 h-3.5 text-teal-400"),
        rx.el.span("main", class_name="text-slate-400"),
        rx.el.code(rx.cond(ProjectRoom.latest_short != "", ProjectRoom.latest_short, "none"), id="latest-snapshot", class_name="text-slate-100"),
        rx.cond(ProjectRoom.dirty, rx.el.span(class_name="h-2 w-2 rounded-full bg-amber-400", title="The editors have changes that aren't in a snapshot", id="dirty-dot")),
        on_click=IdeState.set_view("code"),
        title=rx.cond(ProjectRoom.dirty, "The latest snapshot (the editors have changed since)", "The latest snapshot (the editors match it)"),
        class_name=f"{BTN_OUTLINE} font-mono",
    )


def top_bar() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            logo(),
            rx.el.div(class_name="w-px h-6 bg-slate-800"),
            rx.el.div(
                rx.el.span(ProjectRoom.title, id="project-title", class_name="text-sm font-semibold text-slate-100 truncate max-w-[16rem]"),
                rx.el.span(IdeState.role, id="my-role", class_name="text-[10px] text-slate-500 uppercase tracking-wider"),
                class_name="flex flex-col leading-tight min-w-0",
            ),
            snapshot_chip(),
            class_name="flex items-center gap-3 min-w-0",
        ),
        rx.el.div(
            rx.el.button(rx.icon("snowflake", class_name="w-3.5 h-3.5"), rx.el.span("Freeze", class_name="hidden lg:inline"), on_click=IdeState.open_snapshot, disabled=~IdeState.can_snapshot, id="freeze-button", title="Freeze the editors' text as a snapshot (what runs take)", class_name=BTN_OUTLINE),
            run_menu(),
            ai_button(),
            class_name="flex items-center gap-2",
        ),
        rx.el.div(
            presence(),
            call_button(),
            rx.el.button(
                rx.icon("link", class_name="w-3.5 h-3.5"),
                on_click=[
                    rx.call_script("navigator.clipboard && navigator.clipboard.writeText(window.location.href)"),
                    rx.toast.success("Link copied: whoever opens it works on this project with you (as its access allows).", position="bottom-right"),
                ],
                id="share-link",
                title="Copy this project's link",
                class_name=BTN_GHOST,
            ),
            rx.el.div(class_name="w-px h-6 bg-slate-800"),
            identity(),
            class_name="flex items-center gap-2.5",
        ),
        class_name="flex justify-between items-center px-3 bg-slate-950 border-b border-slate-800 h-12 gap-3 shrink-0",
    )


def rail_button(view: str, icon: str, title: str, hint: str) -> rx.Component:
    badge = rx.fragment()
    if view == "agents":
        badge = rx.cond(ProjectRoom.pending_proposals + ProjectRoom.waiting_runs > 0, rx.el.span(class_name="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-violet-400"))
    return rx.el.button(
        rx.icon(icon, class_name="h-5 w-5"),
        rx.el.span(title, class_name="text-[9px] font-medium"),
        badge,
        on_click=IdeState.set_view(view),
        title=f"{title}: {hint}",
        custom_attrs={"data-view": view},
        class_name=rx.cond(
            IdeState.view == view,
            "relative flex flex-col items-center gap-0.5 w-14 py-2 rounded-lg bg-teal-500/15 text-teal-300",
            "relative flex flex-col items-center gap-0.5 w-14 py-2 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800/60",
        ),
    )


def rail() -> rx.Component:
    return rx.el.nav(
        *[rail_button(*s) for s in SECTIONS],
        class_name="flex flex-col items-center gap-1 py-2 px-1 bg-slate-950 border-r border-slate-800 shrink-0",
    )


# ------------------------------------------------------------ dialogs


def new_file_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("New file"),
            rx.dialog.description("A path in the project, e.g. rtl/alu.v, tb/tb_alu.v or constraints/top.sdc.", size="2"),
            rx.el.input(value=IdeState.new_file_path, on_change=IdeState.set_new_file_path, id="new-file-path", auto_focus=True, class_name=f"{INPUT} w-full mt-3 font-mono"),
            rx.el.div(
                rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.button("Create", on_click=IdeState.create_file, color_scheme="teal", id="create-file"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="460px",
        ),
        open=IdeState.new_file_open,
        on_open_change=IdeState.set_new_file_open,
    )


def rename_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Rename or move"),
            rx.el.input(value=IdeState.rename_path, on_change=IdeState.set_rename_path, id="rename-path", class_name=f"{INPUT} w-full mt-3 font-mono"),
            rx.el.div(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=IdeState.cancel_rename),
                rx.button("Rename", on_click=IdeState.rename_file, color_scheme="teal", id="rename-file"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="460px",
        ),
        open=IdeState.rename_id != "",
    )


def delete_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete this file?"),
            rx.alert_dialog.description(rx.el.span(rx.el.code(IdeState.delete_path), " goes for everyone. Snapshots that have it keep it.")),
            rx.el.div(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray", on_click=IdeState.cancel_delete)),
                rx.alert_dialog.action(rx.button("Delete", color_scheme="red", on_click=IdeState.delete_file, id="confirm-delete-file")),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="440px",
        ),
        open=IdeState.delete_id != "",
    )


def snapshot_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Freeze a snapshot"),
            rx.dialog.description("Freezes every file as it is in the editors now. Runs take snapshots, never the text being typed, so a result always says exactly what it ran.", size="2"),
            rx.el.input(value=IdeState.snapshot_message, on_change=IdeState.set_snapshot_message, placeholder="What it is (e.g. counter width 6)", id="snapshot-message", auto_focus=True, class_name=f"{INPUT} w-full mt-3"),
            rx.el.div(
                rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.button("Freeze", on_click=IdeState.freeze, color_scheme="teal", id="confirm-freeze"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="480px",
        ),
        open=IdeState.snapshot_open,
        on_open_change=IdeState.set_snapshot_open,
    )


def run_ask_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(rx.el.span(IdeState.run_ask["title"], ": which files?")),
            rx.alert_dialog.description(
                rx.cond(
                    ProjectRoom.latest_id != "",
                    "The editors have changes that aren't in a snapshot yet. A run takes a snapshot: freeze the editors' text first, or run the latest snapshot as it is.",
                    "The project has no snapshot yet. Freeze the editors' text to run it.",
                ),
            ),
            rx.el.div(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray", on_click=IdeState.cancel_run_ask)),
                rx.cond(
                    ProjectRoom.latest_id != "",
                    rx.alert_dialog.action(rx.button(rx.el.span("Run ", rx.el.code(ProjectRoom.latest_short)), variant="soft", on_click=IdeState.run_latest, id="run-latest")),
                ),
                rx.alert_dialog.action(rx.button("Freeze and run", color_scheme="teal", on_click=IdeState.run_frozen, id="freeze-and-run")),
                class_name="flex justify-end gap-2 mt-4 flex-wrap",
            ),
            max_width="520px",
        ),
        open=IdeState.run_ask.contains("flow"),
    )


def reject_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Reject the AI's proposal"),
            rx.dialog.description("Say why: the AI reads your reason, and it stays with the proposal.", size="2"),
            rx.el.textarea(value=ReviewState.reject_reason, on_change=ReviewState.set_reject_reason, id="reject-reason", rows="3", placeholder="e.g. N must stay 8: the demo board needs that rate", class_name="w-full mt-3 p-3 rounded-md bg-slate-950 border border-slate-700 text-sm text-slate-100 outline-none focus:border-teal-500"),
            rx.el.div(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=ReviewState.cancel_reject),
                rx.button("Reject", color_scheme="red", on_click=ReviewState.reject, id="confirm-reject"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="480px",
        ),
        open=ReviewState.reject_id != "",
    )


def gone_page() -> rx.Component:
    return rx.el.div(
        rx.el.header(logo(), identity(), class_name="flex justify-between items-center px-6 bg-slate-950 border-b border-slate-800 h-14"),
        rx.el.div(
            rx.icon(rx.cond(IdeState.denied, "lock", "cpu"), class_name="h-12 w-12 text-slate-600"),
            rx.el.p(
                rx.cond(
                    IdeState.denied,
                    "This project is private: ask its owner to add you.",
                    rx.cond(ProjectRoom.gone & ~IdeState.missing, "This project was deleted.", "There is no such project."),
                ),
                id="gone",
                class_name="text-slate-300 font-medium",
            ),
            rx.cond(
                IdeState.denied,
                rx.cond(
                    CommentsState.requested,
                    rx.el.p("Asked: the project's owner sees your request.", id="access-asked", class_name="text-sm text-teal-300"),
                    rx.el.button(rx.icon("hand", class_name="h-4 w-4"), "Ask for access", on_click=CommentsState.ask_access, id="ask-access", class_name=f"{BTN_OUTLINE} h-9 px-4"),
                ),
            ),
            rx.el.a("All projects", href="/", class_name=f"{BTN_PRIMARY} h-9 px-4"),
            class_name="flex flex-col items-center gap-4 pt-32",
        ),
        class_name="h-screen bg-slate-950 font-sans",
    )


def workspace(sections: dict[str, rx.Component]) -> rx.Component:
    """The page: ``sections`` maps each view to its content."""
    return rx.cond(
        IdeState.missing | IdeState.denied | ProjectRoom.gone,
        gone_page(),
        rx.el.div(
            top_bar(),
            rx.el.div(
                rail(),
                rx.el.main(
                    rx.match(IdeState.view, *[(k, v) for k, v in sections.items()], sections["code"]),
                    class_name="flex-1 min-w-0 min-h-0 overflow-hidden",
                ),
                class_name="flex flex-1 min-h-0",
            ),
            page_hooks(),
            incoming_call(),
            new_file_dialog(),
            rename_dialog(),
            delete_dialog(),
            snapshot_dialog(),
            run_ask_dialog(),
            reject_dialog(),
            class_name="h-screen flex flex-col bg-slate-950 text-slate-200 font-sans overflow-hidden",
        ),
    )
