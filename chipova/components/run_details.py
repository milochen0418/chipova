"""A run in detail: its flowgraph (the steps, in order, with their states), its numbers, its
artifacts (with their SHA-256, a download and a check), its manifest, and its problems."""

from __future__ import annotations

import reflex as rx

from chipova.components.common import BTN, BTN_OUTLINE, INPUT, LABEL, PANEL, ago, empty, kv, status_badge
from chipova.components.links import backend_url
from chipova.services.boards import HELPER_PATH
from chipova.states.boards_state import BoardState
from chipova.states.ide import IdeState
from chipova.states.room import ProjectRoom
from chipova.states.runs_state import RunState
from chipova.states.snapshot_state import SnapshotState


def step_node(s) -> rx.Component:
    return rx.el.button(
        rx.el.div(
            rx.match(
                s.status,
                ("SUCCEEDED", rx.icon("circle-check", class_name="h-4 w-4 text-emerald-400")),
                ("FAILED", rx.icon("circle-x", class_name="h-4 w-4 text-rose-400")),
                ("RUNNING", rx.icon("loader", class_name="h-4 w-4 text-sky-400 animate-spin")),
                ("SKIPPED", rx.icon("circle-slash", class_name="h-4 w-4 text-slate-600")),
                ("CANCELED", rx.icon("circle-slash", class_name="h-4 w-4 text-slate-500")),
                rx.icon("circle-dashed", class_name="h-4 w-4 text-slate-500"),
            ),
            rx.el.span(s.title, class_name="text-xs font-semibold text-slate-100 whitespace-nowrap"),
            class_name="flex items-center gap-1.5",
        ),
        rx.el.span(rx.cond(s.seconds != "", s.seconds, s.status), class_name="text-[10px] text-slate-500"),
        rx.cond(s.metrics != "", rx.el.span(s.metrics, class_name="text-[10px] text-slate-400 max-w-[12rem] truncate")),
        on_click=[RunState.set_log_step(s.node), IdeState.set_bottom("output")],
        title=s.command,
        custom_attrs={"data-node": s.node, "data-node-status": s.status},
        class_name=rx.match(
            s.status,
            ("SUCCEEDED", "flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border border-emerald-700/50 bg-emerald-950/30"),
            ("FAILED", "flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border border-rose-700/60 bg-rose-950/30"),
            ("RUNNING", "flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border border-sky-600/60 bg-sky-950/30"),
            "flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border border-slate-700 bg-slate-900",
        ),
    )


def flowgraph() -> rx.Component:
    """The steps as a chain (flows here are linear; SiliconCompiler's too, node by node)."""
    return rx.el.div(
        rx.foreach(
            RunState.steps,
            lambda s, i: rx.el.div(
                rx.cond(i > 0, rx.icon("arrow-right", class_name="h-3.5 w-3.5 text-slate-600 shrink-0")),
                step_node(s),
                class_name="flex items-center gap-2",
            ),
        ),
        id="flowgraph",
        class_name="flex items-center gap-2 flex-wrap",
    )


def artifact_row(a) -> rx.Component:
    return rx.el.tr(
        rx.el.td(rx.el.code(a.name, class_name="text-slate-200"), class_name="px-2 py-1"),
        rx.el.td(a.kind, class_name="px-2 text-slate-400"),
        rx.el.td(a.size, class_name="px-2 text-slate-400 whitespace-nowrap"),
        rx.el.td(rx.el.code(a.sha, title=a.sha_full, class_name="text-slate-500"), class_name="px-2"),
        rx.el.td(
            rx.el.div(
                rx.el.a(rx.icon("download", class_name="h-3.5 w-3.5"), href=backend_url(a.href), custom_attrs={"data-download": a.name, "download": ""}, title="Download", class_name="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800"),
                rx.el.button(rx.icon("fingerprint", class_name="h-3.5 w-3.5"), on_click=RunState.verify(a.id), custom_attrs={"data-verify": a.name}, title="Check its SHA-256 again", class_name="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800"),
                class_name="flex items-center gap-1",
            ),
            class_name="px-2",
        ),
        class_name="border-b border-slate-800/60",
    )


def artifacts_table() -> rx.Component:
    return rx.cond(
        RunState.artifacts.length() > 0,
        rx.el.table(
            rx.el.thead(rx.el.tr(*[rx.el.th(h, class_name="px-2 py-1 text-left font-semibold") for h in ["Artifact", "Kind", "Size", "SHA-256", ""]], class_name="text-[10px] uppercase tracking-wider text-slate-500")),
            rx.el.tbody(rx.foreach(RunState.artifacts, artifact_row)),
            id="artifacts",
            class_name="w-full text-xs",
        ),
        rx.el.p("No artifacts (yet).", class_name="text-xs text-slate-500"),
    )


def facts_grid() -> rx.Component:
    return rx.el.div(
        rx.foreach(RunState.facts, lambda f: rx.el.div(kv(f.label, f.value), class_name="px-3 py-2 rounded-lg bg-slate-900 border border-slate-800")),
        id="run-facts",
        class_name="grid grid-cols-2 lg:grid-cols-4 gap-2",
    )


def board_jobs() -> rx.Component:
    """The boards asked to be programmed with this run's bitstream, and how it went."""
    return rx.cond(
        RunState.board_jobs.length() > 0,
        rx.el.div(
            rx.el.span("Boards", class_name=LABEL),
            rx.foreach(
                RunState.board_jobs,
                lambda j: rx.el.details(
                    rx.el.summary(
                        status_badge(j.status, small=True),
                        rx.el.code(j.board, class_name="text-xs text-slate-200"),
                        rx.el.span("through ", j.helper, " · ", j.by, " · ", ago(j.at), class_name="text-xs text-slate-500"),
                        class_name="flex items-center gap-2 cursor-pointer",
                    ),
                    rx.cond(j.log != "", rx.el.pre(j.log, class_name="mt-1 p-2 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-300 whitespace-pre-wrap max-h-48 overflow-y-auto")),
                    custom_attrs={"data-board-job": j.id, "data-board-status": j.status},
                ),
            ),
            class_name="flex flex-col gap-1",
        ),
    )


def program_dialog() -> rx.Component:
    helper_cmd = rx.el.code(
        "python3 board_helper.py --url ", backend_url("/"), " --token <your API token> --name \"My bench\"",
        class_name="block p-2 rounded bg-slate-950 border border-slate-800 text-[11px] text-teal-200 break-all",
    )
    no_helper = rx.el.div(
        rx.el.p("No board helper of yours is running. Start it on the computer the board is plugged into:", class_name="text-sm text-slate-300"),
        rx.el.ol(
            rx.el.li("Install openFPGALoader (macOS: brew install openfpgaloader; Debian/Ubuntu: sudo apt install openfpgaloader)."),
            rx.el.li("Make an API token (Agents page), and ", rx.el.a("download the helper", href=backend_url(HELPER_PATH), custom_attrs={"download": "board_helper.py"}, class_name="text-teal-300 underline"), "."),
            rx.el.li("Run it:", helper_cmd),
            class_name="list-decimal pl-5 text-xs text-slate-400 flex flex-col gap-1",
        ),
        rx.el.button("Look again", on_click=BoardState.look_again, id="look-again", class_name=BTN_OUTLINE),
        class_name="flex flex-col gap-2 mt-3",
    )
    choose = rx.el.div(
        rx.el.label(
            rx.el.span("Board helper", class_name=LABEL),
            rx.el.select(
                rx.foreach(BoardState.helpers, lambda h: rx.cond(h.online, rx.el.option(h.name, value=h.id))),
                value=BoardState.helper_id, on_change=BoardState.set_helper, id="board-helper", class_name=f"{INPUT} w-full",
            ),
            class_name="flex flex-col gap-1",
        ),
        rx.foreach(BoardState.helpers, lambda h: rx.cond(h.online & (h.id == BoardState.helper_id) & (h.boards != ""), rx.el.p("On its USB: ", h.boards, class_name="text-[11px] text-slate-500 break-all"))),
        rx.el.label(
            rx.el.span("Board (openFPGALoader's name for it)", class_name=LABEL),
            rx.el.input(value=BoardState.board, on_change=BoardState.set_board, list="board-names", id="board-name", class_name=f"{INPUT} w-full font-mono"),
            rx.el.datalist(rx.foreach(BoardState.suggestions, lambda b: rx.el.option(value=b)), id="board-names"),
            class_name="flex flex-col gap-1",
        ),
        class_name="flex flex-col gap-3 mt-3",
    )
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Program a board"),
            rx.dialog.description(
                "Your board helper writes this run's bitstream to the board plugged into its computer, after checking it against the SHA-256 Chipova recorded. Only your own helpers take your work.",
                size="2",
            ),
            rx.cond(BoardState.helper_id != "", choose, no_helper),
            rx.el.div(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=BoardState.close),
                rx.button("Program", color_scheme="teal", on_click=BoardState.program, disabled=BoardState.helper_id == "", id="program-board"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="560px",
        ),
        open=BoardState.open,
    )


def run_header() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            status_badge(RunState.status),
            rx.el.span(RunState.title, class_name="text-base font-semibold text-slate-100"),
            rx.el.code(RunState.selected, class_name="text-xs text-slate-500"),
            class_name="flex items-center gap-2 flex-wrap",
        ),
        rx.el.div(
            rx.el.span("snapshot ", rx.el.code(RunState.snapshot, class_name="text-teal-300", title=RunState.snapshot_full)),
            rx.el.span("by ", RunState.by, rx.cond(RunState.via == "ai", " (AI)", "")),
            rx.cond(RunState.duration != "", rx.el.span("took ", RunState.duration)),
            rx.cond(RunState.queue_position > 0, rx.el.span("place in queue: ", RunState.queue_position)),
            rx.cond(RunState.profile != "", rx.el.span("tools ", rx.el.code(RunState.profile))),
            rx.cond(RunState.params != "", rx.el.span(RunState.params, class_name="font-mono")),
            class_name="flex items-center gap-3 flex-wrap text-xs text-slate-400",
        ),
        rx.cond(RunState.error != "", rx.el.p(RunState.error, class_name="text-sm text-rose-300")),
        rx.el.div(
            rx.cond(RunState.manifest != "", rx.el.a(rx.icon("file-json", class_name="h-3.5 w-3.5"), "Manifest", href=backend_url(RunState.manifest), id="manifest-link", custom_attrs={"download": ""}, class_name=BTN_OUTLINE)),
            rx.el.button(rx.icon("rotate-ccw", class_name="h-3.5 w-3.5"), "Run again", on_click=RunState.rerun, disabled=~IdeState.can_run, title="The same flow, parameters and snapshot", class_name=BTN_OUTLINE),
            rx.el.button(rx.icon("terminal", class_name="h-3.5 w-3.5"), "Output", on_click=[IdeState.set_view("code"), IdeState.set_bottom("output")], class_name=BTN_OUTLINE),
            rx.cond(
                RunState.flow.startswith("fpga_") & (RunState.status == "SUCCEEDED"),
                rx.el.button(rx.icon("usb", class_name="h-3.5 w-3.5"), "Program a board…", on_click=BoardState.ask, disabled=~IdeState.can_run, id="program-board-open", class_name=BTN_OUTLINE),
            ),
            class_name="flex items-center gap-2 flex-wrap",
        ),
        board_jobs(),
        program_dialog(),
        class_name="flex flex-col gap-2",
    )


def compare_block() -> rx.Component:
    """This run beside another of the same flow: what went in and what came out (AC-06)."""
    rows = rx.el.table(
        rx.el.thead(rx.el.tr(*[rx.el.th(h, class_name="px-2 py-1 text-left font-semibold") for h in ["", "This run", "The other", ""]], class_name="text-[10px] uppercase tracking-wider text-slate-500")),
        rx.el.tbody(
            rx.foreach(
                SnapshotState.compare,
                lambda c: rx.el.tr(
                    rx.el.td(c.what, class_name="px-2 py-1 text-slate-300 whitespace-nowrap"),
                    rx.el.td(rx.el.code(c.a, class_name="break-all"), class_name="px-2 text-slate-400"),
                    rx.el.td(rx.el.code(c.b, class_name="break-all"), class_name="px-2 text-slate-400"),
                    rx.el.td(rx.cond(c.same, rx.el.span("same", class_name="text-emerald-400"), rx.el.span("differs", class_name="text-amber-300")), class_name="px-2 whitespace-nowrap"),
                    class_name="border-b border-slate-800/60 align-top",
                ),
            ),
        ),
        id="run-compare",
        class_name="w-full text-xs",
    )
    return rx.el.div(
        rx.el.div(
            rx.el.span("Compare with", class_name=LABEL),
            rx.el.select(
                rx.el.option("another run of this flow…", value=""),
                rx.foreach(
                    ProjectRoom.runs,
                    lambda r: rx.cond((r.flow == RunState.flow) & (r.id != RunState.selected), rx.el.option(r.id + " · " + r.snapshot + " · " + r.status, value=r.id)),
                ),
                value=SnapshotState.compare_b,
                on_change=SnapshotState.set_compare_b,
                id="compare-run",
                class_name="h-8 px-2 rounded-md bg-slate-950 border border-slate-700 text-xs text-slate-200",
            ),
            rx.el.button("Compare", on_click=SnapshotState.compare_runs(RunState.selected), id="compare-button", class_name=BTN_OUTLINE),
            class_name="flex items-center gap-3",
        ),
        rx.cond((SnapshotState.compare_a == RunState.selected) & (SnapshotState.compare.length() > 0), rows),
        class_name="flex flex-col gap-2",
    )


def run_details(extra: rx.Component | None = None) -> rx.Component:
    return rx.cond(
        RunState.selected != "",
        rx.el.div(
            run_header(),
            rx.el.div(rx.el.span("Flow", class_name=LABEL), flowgraph(), class_name="flex flex-col gap-2"),
            rx.cond(RunState.facts.length() > 0, rx.el.div(rx.el.span("Numbers", class_name=LABEL), facts_grid(), class_name="flex flex-col gap-2")),
            extra or rx.fragment(),
            rx.el.div(rx.el.span("Artifacts", class_name=LABEL), artifacts_table(), class_name="flex flex-col gap-2"),
            compare_block(),
            class_name="flex flex-col gap-5",
        ),
        empty("mouse-pointer-click", "Pick a run", "Its steps, numbers and artifacts show here."),
    )


def runs_list(category: str) -> rx.Component:
    """The project's runs of one category, newest first; a click selects one."""
    return rx.el.div(
        rx.foreach(
            ProjectRoom.runs,
            lambda r: rx.cond(
                r.category == category,
                rx.el.button(
                    rx.el.div(status_badge(r.status, small=True), rx.el.span(r.title, class_name="text-xs font-semibold text-slate-200 truncate"), class_name="flex items-center gap-2 min-w-0"),
                    rx.el.div(
                        rx.el.code(r.snapshot, class_name="text-teal-300"),
                        rx.el.span(r.summary, class_name="truncate"),
                        class_name="flex items-center gap-2 text-[11px] text-slate-400 min-w-0",
                    ),
                    on_click=RunState.select(r.id),
                    custom_attrs={"data-run": r.id},
                    class_name=rx.cond(
                        RunState.selected == r.id,
                        "flex flex-col gap-1 w-full text-left px-3 py-2 rounded-lg bg-teal-500/10 border border-teal-700/50",
                        "flex flex-col gap-1 w-full text-left px-3 py-2 rounded-lg hover:bg-slate-800/60 border border-transparent",
                    ),
                ),
            ),
        ),
        class_name="flex flex-col gap-1",
    )


def flow_button(flow_id: str, title: str, icon: str) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, class_name="h-3.5 w-3.5"), title,
        on_click=IdeState.start_run(flow_id),
        disabled=~IdeState.can_run,
        custom_attrs={"data-start": flow_id},
        class_name=f"{BTN} h-9 px-3 bg-teal-700 hover:bg-teal-600 text-white",
    )


def two_columns(left: rx.Component, right: rx.Component) -> rx.Component:
    return rx.el.div(
        # Side by side; stacked on a phone.
        rx.el.div(left, class_name=f"{PANEL} p-2 w-full md:w-72 max-h-64 md:max-h-none shrink-0 overflow-y-auto"),
        rx.el.div(right, class_name="flex-1 min-w-0 md:overflow-y-auto"),
        class_name="flex flex-col md:flex-row gap-4 md:flex-1 md:min-h-0",
    )
