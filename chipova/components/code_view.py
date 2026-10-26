"""The Code section: the files (explorer, tabs, the co-edited editor), the AI's proposals with
their diffs, and the bottom panel (problems, a run's output, the waveform, the runs)."""

from __future__ import annotations

import reflex as rx
import reflex_monaco
from reflex_ddns_auth.intent import Intent

from chipova.components.common import BTN, BTN_AI, BTN_GHOST, BTN_OUTLINE, BTN_PRIMARY, LABEL, ago, empty, status_badge
from chipova.components.links import backend_base, backend_url
from chipova.components.together import face
from chipova.states.comments_state import CommentsState
from chipova.states.ide import IdeState
from chipova.states.review_state import ReviewState
from chipova.states.room import ProjectRoom
from chipova.states.runs_state import RunState
from chipova.states.snapshot_state import SnapshotState
from chipova.states.ui_state import UiState

# ------------------------------------------------------------ explorer


def file_icon(lang: rx.Var) -> rx.Component:
    return rx.match(
        lang,
        ("systemverilog", rx.icon("file-code-2", class_name="h-3.5 w-3.5 text-teal-400 shrink-0")),
        ("tcl", rx.icon("timer", class_name="h-3.5 w-3.5 text-amber-400 shrink-0")),
        ("ini", rx.icon("settings-2", class_name="h-3.5 w-3.5 text-slate-400 shrink-0")),
        ("markdown", rx.icon("file-text", class_name="h-3.5 w-3.5 text-sky-400 shrink-0")),
        rx.icon("file", class_name="h-3.5 w-3.5 text-slate-400 shrink-0"),
    )


def file_row(f) -> rx.Component:
    indent = {"paddingLeft": (f.depth * 12 + 8).to(str) + "px"}
    return rx.cond(
        f.kind == "folder",
        rx.el.div(
            rx.icon("folder", class_name="h-3.5 w-3.5 text-slate-500 shrink-0"),
            rx.el.span(f.name, class_name="truncate"),
            style=indent,
            class_name="flex items-center gap-1.5 h-7 pr-2 text-xs font-semibold text-slate-400 select-none",
        ),
        rx.el.div(
            rx.el.button(
                file_icon(f.lang),
                rx.el.span(f.name, class_name="truncate"),
                rx.cond(f.editing != "", rx.el.span(class_name="h-1.5 w-1.5 rounded-full bg-teal-400 shrink-0", title="Open by " + f.editing)),
                on_click=IdeState.open_file(f.id),
                style=indent,
                title=f.path,
                custom_attrs={"data-file": f.path},
                class_name=rx.cond(
                    IdeState.active_file == f.id,
                    "flex items-center gap-1.5 h-7 pr-2 flex-1 min-w-0 text-left text-[13px] text-white bg-teal-500/15",
                    "flex items-center gap-1.5 h-7 pr-2 flex-1 min-w-0 text-left text-[13px] text-slate-300 hover:bg-slate-800/70",
                ),
            ),
            rx.cond(
                IdeState.can_edit,
                rx.menu.root(
                    rx.menu.trigger(rx.el.button(rx.icon("ellipsis", class_name="h-3.5 w-3.5"), class_name="px-1.5 h-7 text-slate-500 hover:text-slate-200 opacity-0 group-hover:opacity-100", title="More")),
                    rx.menu.content(
                        rx.menu.item("Rename or move", on_select=IdeState.ask_rename(f.id, f.path)),
                        rx.menu.item("Delete", color="red", on_select=IdeState.ask_delete(f.id, f.path)),
                    ),
                ),
            ),
            class_name="group flex items-center",
        ),
    )


def latest_results() -> rx.Component:
    """The last run of each kind, newest first."""
    return rx.el.div(
        rx.foreach(
            ProjectRoom.runs[:6],
            lambda r: rx.el.button(
                status_badge(r.status, small=True),
                rx.el.span(r.title, class_name="truncate text-slate-300"),
                rx.el.span(r.summary, class_name="truncate text-slate-500 ml-auto"),
                on_click=[RunState.select(r.id), IdeState.set_bottom("output")],
                class_name="flex items-center gap-2 w-full h-7 px-2 rounded text-xs hover:bg-slate-800/70",
            ),
        ),
        class_name="flex flex-col",
    )


def snapshots_list() -> rx.Component:
    return rx.el.div(
        rx.foreach(
            ProjectRoom.snapshots[:8],
            lambda s: rx.el.button(
                rx.el.code(s.short, class_name="text-teal-300 text-[11px]"),
                rx.el.span(s.message, class_name="truncate text-slate-400"),
                on_click=SnapshotState.open(s.id),
                title=s.message + " · " + s.by,
                custom_attrs={"data-snapshot": s.short},
                class_name=rx.cond(
                    SnapshotState.open_id == s.id,
                    "flex items-center gap-2 h-6 px-2 text-xs w-full text-left bg-teal-500/10",
                    "flex items-center gap-2 h-6 px-2 text-xs w-full text-left hover:bg-slate-800/70",
                ),
            ),
        ),
        class_name="flex flex-col",
    )


def explorer() -> rx.Component:
    return rx.el.aside(
        rx.el.div(
            rx.el.span("Files", class_name=LABEL),
            rx.cond(IdeState.can_edit, rx.el.button(rx.icon("file-plus", class_name="h-3.5 w-3.5"), on_click=IdeState.open_new_file, id="new-file", title="New file", class_name="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800")),
            class_name="flex items-center justify-between px-3 h-9 shrink-0",
        ),
        rx.el.div(rx.foreach(ProjectRoom.files, file_row), id="explorer", class_name="flex flex-col pb-2"),
        rx.el.div(rx.el.span("Results", class_name=LABEL), class_name="px-3 pt-3 pb-1"),
        latest_results(),
        rx.el.div(rx.el.span("Snapshots", class_name=LABEL), class_name="px-3 pt-3 pb-1"),
        snapshots_list(),
        id="explorer-pane",
        style={"width": "var(--chip-explorer, 240px)"},
        class_name="shrink-0 bg-slate-950 border-r border-slate-800 overflow-y-auto",
    )


# ------------------------------------------------------------ editor


def tab(f) -> rx.Component:
    return rx.cond(
        IdeState.open_tabs.contains(f.id),
        rx.el.div(
            rx.el.button(
                file_icon(f.lang),
                rx.el.span(f.name),
                on_click=IdeState.open_file(f.id),
                title=f.path,
                class_name="flex items-center gap-1.5 pl-3 pr-1 h-full text-[13px]",
            ),
            rx.el.button(rx.icon("x", class_name="h-3 w-3"), on_click=IdeState.close_tab(f.id), title="Close", class_name="px-1.5 h-full text-slate-500 hover:text-white"),
            custom_attrs={"data-tab": f.path},
            class_name=rx.cond(
                IdeState.active_file == f.id,
                "flex items-center h-full bg-slate-900 text-white border-t-2 border-teal-400",
                "flex items-center h-full text-slate-400 hover:text-slate-200 border-t-2 border-transparent",
            ),
        ),
    )


def editor() -> rx.Component:
    me = UiState.me
    return rx.cond(
        IdeState.active_file != "",
        rx.el.div(
            reflex_monaco.monaco(
                id="monaco-editor",
                # Uncontrolled: the co-edited text fills it (assets/chipova/collab.js).
                default_value="",
                key=IdeState.active_file,
                language=IdeState.active_lang,
                theme="vs-dark",
                height="100%",
                width="100%",
            ),
            custom_attrs={
                "data-chip-doc": IdeState.project_id + "-" + IdeState.active_file,
                "data-chip-file": IdeState.active_file,
                "data-chip-path": IdeState.active_path,
                "data-chip-ticket": IdeState.ticket,
                "data-chip-readonly": rx.cond(IdeState.can_edit, "false", "true"),
                "data-chip-user-name": me["name"],
                "data-chip-user-color": me["color"],
                "data-chip-user-peer": me["peer"],
                "data-backend": backend_base(),
            },
            id="editor-panel",
            class_name="flex-1 min-h-0",
        ),
        empty("file-code-2", "No file open", "Pick a file on the left."),
    )


def diff_line(line) -> rx.Component:
    return rx.el.div(
        rx.el.span(line.old, class_name="w-10 shrink-0 text-right pr-2 text-slate-600 select-none"),
        rx.el.span(line.new, class_name="w-10 shrink-0 text-right pr-2 text-slate-600 select-none"),
        rx.el.span(
            rx.match(line.kind, ("add", "+"), ("del", "-"), " "),
            class_name="w-4 shrink-0 select-none",
        ),
        rx.el.span(line.text, class_name="whitespace-pre"),
        class_name=rx.match(
            line.kind,
            ("add", "flex bg-emerald-500/10 text-emerald-200"),
            ("del", "flex bg-rose-500/10 text-rose-200"),
            ("hunk", "flex bg-slate-800/60 text-sky-300 py-0.5"),
            "flex text-slate-300",
        ),
    )


def diff_file(f) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.span(rx.match(f.op, ("create", "new file"), ("delete", "deleted"), "changed"), class_name="text-[10px] uppercase tracking-wider text-slate-500"),
            rx.el.code(f.path, class_name="text-sm text-slate-100"),
            rx.el.span("+", f.added, class_name="text-xs text-emerald-400"),
            rx.el.span("−", f.removed, class_name="text-xs text-rose-400"),
            rx.cond(f.changed_since, rx.el.span(rx.icon("git-merge", class_name="h-3 w-3"), "edited since the AI read it: it will be merged", class_name="ml-auto inline-flex items-center gap-1 text-[11px] text-amber-300")),
            class_name="flex items-center gap-2 px-3 py-2 bg-slate-900 border-b border-slate-800 sticky top-0",
        ),
        rx.el.div(rx.foreach(f.lines, diff_line), class_name="font-mono text-[12px] leading-5 overflow-x-auto"),
        custom_attrs={"data-diff-file": f.path},
        class_name="rounded-lg border border-slate-800 overflow-hidden",
    )


def proposal_view() -> rx.Component:
    """An AI proposal under review: why, how to check it, its diffs, and the decision."""
    deciding = (ReviewState.status == "PROPOSED") & IdeState.can_decide
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("sparkles", class_name="h-4 w-4 text-violet-400"),
                    rx.el.span("Proposal by ", ReviewState.agent, class_name="text-xs text-violet-300"),
                    status_badge(ReviewState.status, small=True),
                    rx.el.span("on snapshot ", rx.el.code(ReviewState.base), class_name="text-xs text-slate-500"),
                    class_name="flex items-center gap-2 flex-wrap",
                ),
                rx.el.h3(ReviewState.title, class_name="text-base font-semibold text-slate-100"),
                class_name="flex flex-col gap-1 min-w-0",
            ),
            rx.el.div(
                rx.cond(
                    deciding,
                    rx.fragment(
                        rx.el.button(rx.icon("x", class_name="h-3.5 w-3.5"), "Reject", on_click=ReviewState.ask_reject(ReviewState.open_id), id="reject-proposal", class_name=f"{BTN_OUTLINE} text-rose-300"),
                        rx.el.button(rx.icon("check", class_name="h-3.5 w-3.5"), "Accept for everyone", on_click=ReviewState.accept(ReviewState.open_id), disabled=ReviewState.busy, id="accept-proposal", class_name=BTN_PRIMARY),
                    ),
                ),
                rx.el.button(rx.icon("x", class_name="h-4 w-4"), on_click=ReviewState.close, title="Close", id="close-proposal", class_name=BTN_GHOST),
                class_name="flex items-center gap-2 shrink-0",
            ),
            class_name="flex items-start justify-between gap-4 px-4 py-3 border-b border-slate-800",
        ),
        rx.el.div(
            rx.cond(ReviewState.rationale != "", rx.el.div(rx.el.span("Why", class_name=LABEL), rx.el.p(ReviewState.rationale, class_name="text-sm text-slate-300 whitespace-pre-wrap"), class_name="flex flex-col gap-1")),
            rx.cond(ReviewState.plan != "", rx.el.div(rx.el.span("How to check it", class_name=LABEL), rx.el.p(ReviewState.plan, class_name="text-sm text-slate-300 whitespace-pre-wrap"), class_name="flex flex-col gap-1")),
            rx.cond(
                ReviewState.status == "APPROVED",
                rx.el.p("Accepted by ", ReviewState.decided_by, ": applied for everyone as snapshot ", rx.el.code(ReviewState.applied), class_name="text-sm text-emerald-300"),
            ),
            rx.cond(
                ReviewState.status == "REJECTED",
                rx.el.p("Rejected by ", ReviewState.decided_by, ": ", ReviewState.reason, class_name="text-sm text-rose-300"),
            ),
            rx.el.div(rx.foreach(ReviewState.files, diff_file), class_name="flex flex-col gap-3"),
            class_name="flex flex-col gap-4 p-4 overflow-y-auto flex-1 min-h-0",
        ),
        id="proposal-view",
        class_name="flex flex-col flex-1 min-h-0 bg-slate-950",
    )


def snapshot_view() -> rx.Component:
    """A snapshot: what it changed (from its parent, or another snapshot), its runs, its
    reviews, and putting its files back."""
    review_box = rx.cond(
        IdeState.can_review | IdeState.can_edit,
        rx.el.div(
            rx.el.textarea(value=SnapshotState.review_comment, on_change=SnapshotState.set_review_comment, rows="2", placeholder="A review of this snapshot (it applies to this snapshot only)", id="review-comment", class_name="w-full p-2 rounded-md bg-slate-950 border border-slate-700 text-sm text-slate-100 outline-none focus:border-teal-500"),
            rx.el.div(
                rx.cond(
                    IdeState.can_review,
                    rx.fragment(
                        rx.el.button(rx.icon("check", class_name="h-3.5 w-3.5"), "Approve", on_click=SnapshotState.add_review("approved"), id="review-approve", class_name=BTN_PRIMARY),
                        rx.el.button("Ask for changes", on_click=SnapshotState.add_review("changes_requested"), id="review-changes", class_name=BTN_OUTLINE),
                    ),
                ),
                rx.el.button("Comment", on_click=SnapshotState.add_review("commented"), class_name=BTN_OUTLINE),
                class_name="flex gap-2",
            ),
            class_name="flex flex-col gap-2",
        ),
    )
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("git-commit-horizontal", class_name="h-4 w-4 text-teal-400"),
                    rx.el.span("Snapshot ", rx.el.code(SnapshotState.short, class_name="text-teal-300"), class_name="text-xs text-slate-400"),
                    rx.el.span("by ", SnapshotState.by, " · ", ago(SnapshotState.at), " · ", SnapshotState.files_count, " files", class_name="text-xs text-slate-500"),
                    class_name="flex items-center gap-2 flex-wrap",
                ),
                rx.el.h3(SnapshotState.message, class_name="text-base font-semibold text-slate-100"),
                class_name="flex flex-col gap-1 min-w-0",
            ),
            rx.el.div(
                rx.cond(IdeState.can_edit, rx.el.button(rx.icon("history", class_name="h-3.5 w-3.5"), "Put these files back", on_click=SnapshotState.ask_restore, id="restore-snapshot", class_name=BTN_OUTLINE)),
                rx.el.button(rx.icon("x", class_name="h-4 w-4"), on_click=SnapshotState.close, title="Close", id="close-snapshot", class_name=BTN_GHOST),
                class_name="flex items-center gap-2 shrink-0",
            ),
            class_name="flex items-start justify-between gap-4 px-4 py-3 border-b border-slate-800",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.span("Changes from", class_name=LABEL),
                rx.el.select(
                    rx.el.option("the snapshot before", value=""),
                    rx.foreach(ProjectRoom.snapshots, lambda s: rx.el.option(s.short + " · " + s.message, value=s.id)),
                    value=SnapshotState.base_id,
                    on_change=SnapshotState.compare_with,
                    id="snapshot-base",
                    class_name="h-8 px-2 rounded-md bg-slate-950 border border-slate-700 text-xs text-slate-200 max-w-md",
                ),
                rx.cond(SnapshotState.base_short != "", rx.el.code(SnapshotState.base_short, class_name="text-xs text-slate-500")),
                class_name="flex items-center gap-3",
            ),
            rx.cond(
                SnapshotState.files.length() > 0,
                rx.el.div(rx.foreach(SnapshotState.files, diff_file), id="snapshot-diff", class_name="flex flex-col gap-3"),
                rx.el.p("No file changed.", class_name="text-sm text-slate-500"),
            ),
            rx.el.div(
                rx.el.span("Runs of this snapshot", class_name=LABEL),
                rx.foreach(
                    SnapshotState.runs,
                    lambda r: rx.el.button(
                        status_badge(r.status, small=True), rx.el.span(r.title, class_name="text-xs text-slate-200"), rx.el.span(r.summary, class_name="text-xs text-slate-400"),
                        on_click=[RunState.select(r.id), IdeState.set_bottom("output")],
                        class_name="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-800/60",
                    ),
                ),
                class_name="flex flex-col gap-1",
            ),
            rx.el.div(
                rx.el.span("Reviews of this snapshot", class_name=LABEL),
                rx.foreach(
                    SnapshotState.reviews,
                    lambda v: rx.el.div(
                        rx.match(v.status, ("approved", rx.icon("circle-check", class_name="h-4 w-4 text-emerald-400")), ("changes_requested", rx.icon("circle-alert", class_name="h-4 w-4 text-amber-400")), rx.icon("message-square", class_name="h-4 w-4 text-slate-400")),
                        rx.el.span(v.reviewer, class_name="text-xs font-semibold text-slate-200"),
                        rx.el.span(v.comment, class_name="text-xs text-slate-400"),
                        rx.el.span(ago(v.at), class_name="text-[10px] text-slate-600"),
                        custom_attrs={"data-review": v.status},
                        class_name="flex items-center gap-2",
                    ),
                ),
                review_box,
                class_name="flex flex-col gap-2",
            ),
            class_name="flex flex-col gap-5 p-4 overflow-y-auto flex-1 min-h-0",
        ),
        rx.alert_dialog.root(
            rx.alert_dialog.content(
                rx.alert_dialog.title(rx.el.span("Put the files back to ", rx.el.code(SnapshotState.short), "?")),
                rx.alert_dialog.description("Everyone's editors change to this snapshot's files (a file it doesn't have is deleted), and that is frozen as a new snapshot. Nothing is lost: the snapshots before stay."),
                rx.el.div(
                    rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray", on_click=SnapshotState.cancel_restore)),
                    rx.alert_dialog.action(rx.button("Put them back", color_scheme="teal", on_click=SnapshotState.restore, id="confirm-restore")),
                    class_name="flex justify-end gap-2 mt-4",
                ),
                max_width="480px",
            ),
            open=SnapshotState.confirm_restore,
        ),
        id="snapshot-view",
        class_name="flex flex-col flex-1 min-h-0 bg-slate-950",
    )


def center() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(rx.foreach(ProjectRoom.files, tab), id="tabs", class_name="flex items-stretch h-full overflow-x-auto"),
            class_name="h-9 shrink-0 bg-slate-950 border-b border-slate-800",
        ),
        rx.cond(ReviewState.open_id != "", proposal_view(), rx.cond(SnapshotState.open_id != "", snapshot_view(), editor())),
        class_name="flex flex-col flex-1 min-h-0 bg-slate-900",
    )


# ------------------------------------------------------------ bottom panel


def problem_row(p) -> rx.Component:
    return rx.el.button(
        rx.match(
            p.severity,
            ("error", rx.icon("circle-x", class_name="h-3.5 w-3.5 text-rose-400 shrink-0 mt-0.5")),
            ("warning", rx.icon("triangle-alert", class_name="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5")),
            rx.icon("info", class_name="h-3.5 w-3.5 text-sky-400 shrink-0 mt-0.5"),
        ),
        rx.el.span(p.message, class_name="text-slate-200 text-left break-words"),
        rx.el.span(p.where, class_name="ml-auto text-slate-500 whitespace-nowrap font-mono"),
        rx.el.span(p.tool, class_name="text-slate-600 whitespace-nowrap"),
        on_click=IdeState.jump(p.file, p.line, p.column),
        custom_attrs={"data-problem": p.where},
        class_name="flex items-start gap-2 w-full px-3 py-1 text-xs hover:bg-slate-800/70",
    )


def problems_panel() -> rx.Component:
    return rx.cond(
        RunState.selected != "",
        rx.cond(
            RunState.problems.length() > 0,
            rx.el.div(rx.foreach(RunState.problems, problem_row), id="problems", class_name="flex flex-col py-1"),
            empty("circle-check", "No problems reported by this run's tools.", rx.el.span(RunState.title, " · ", RunState.status)),
        ),
        empty("list-checks", "No run yet", "Run Lint or Simulate from the Run menu."),
    )


def step_chip(s) -> rx.Component:
    return rx.el.button(
        rx.match(
            s.status,
            ("SUCCEEDED", rx.icon("circle-check", class_name="h-3 w-3 text-emerald-400")),
            ("FAILED", rx.icon("circle-x", class_name="h-3 w-3 text-rose-400")),
            ("RUNNING", rx.icon("loader", class_name="h-3 w-3 text-sky-400 animate-spin")),
            rx.icon("circle-dashed", class_name="h-3 w-3 text-slate-500"),
        ),
        s.title,
        rx.cond(s.seconds != "", rx.el.span(s.seconds, class_name="text-slate-500")),
        on_click=RunState.set_log_step(s.node),
        title=s.command,
        custom_attrs={"data-step": s.node, "data-step-status": s.status},
        class_name=rx.cond(
            RunState.log_step == s.node,
            "inline-flex items-center gap-1.5 h-6 px-2 rounded bg-slate-700 text-[11px] text-white",
            "inline-flex items-center gap-1.5 h-6 px-2 rounded bg-slate-800/70 text-[11px] text-slate-300 hover:bg-slate-700",
        ),
    )


def output_panel() -> rx.Component:
    return rx.cond(
        RunState.selected != "",
        rx.el.div(
            rx.el.div(
                status_badge(RunState.status, small=True),
                rx.el.span(RunState.title, class_name="text-xs font-semibold text-slate-200"),
                rx.el.code(RunState.selected, class_name="text-[11px] text-slate-500"),
                rx.el.span("snapshot ", rx.el.code(RunState.snapshot, class_name="text-teal-300"), class_name="text-[11px] text-slate-500"),
                rx.el.div(rx.foreach(RunState.steps, step_chip), class_name="flex items-center gap-1 flex-wrap"),
                rx.cond(RunState.error != "", rx.el.span(RunState.error, class_name="text-[11px] text-rose-300 truncate")),
                class_name="flex items-center gap-2 px-3 py-1.5 border-b border-slate-800 flex-wrap",
            ),
            rx.el.pre(
                rx.foreach(RunState.log, lambda line: rx.el.div(line)),
                id="run-output",
                custom_attrs={"data-autoscroll": "1"},
                class_name="flex-1 min-h-0 overflow-auto px-3 py-2 font-mono text-[11.5px] leading-[1.45] text-slate-300 whitespace-pre",
            ),
            class_name="flex flex-col h-full",
        ),
        empty("terminal", "No run selected", "Pick a run in Runs, or start one from the Run menu."),
    )


def wave_panel(tall: bool = False) -> rx.Component:
    return rx.cond(
        RunState.wave_url != "",
        rx.el.div(
            id="wave-viewer" if not tall else "wave-viewer-big",
            custom_attrs={"data-wave-url": RunState.wave_url, "data-backend": backend_base(), "data-run": RunState.selected},
            class_name="chip-wave h-full w-full",
        ),
        empty("audio-waveform", "No waveform", "Select a simulation run: its testbench's $dumpfile is shown here."),
    )


def run_row(r) -> rx.Component:
    waiting = r.status == "WAITING"
    return rx.el.tr(
        rx.el.td(status_badge(r.status, small=True), class_name="px-3 py-1.5"),
        rx.el.td(rx.el.span(r.title, class_name="text-slate-200"), class_name="px-2"),
        rx.el.td(rx.el.code(r.snapshot, class_name="text-teal-300"), class_name="px-2"),
        rx.el.td(rx.el.span(rx.cond(r.via == "ai", "🤖 ", ""), r.by), class_name="px-2 text-slate-400 whitespace-nowrap"),
        rx.el.td(r.summary, class_name="px-2 text-slate-300"),
        rx.el.td(
            rx.cond(r.errors > 0, rx.el.span(r.errors, " errors", class_name="text-rose-300 mr-2")),
            rx.cond(r.warnings > 0, rx.el.span(r.warnings, " warnings", class_name="text-amber-300")),
            class_name="px-2 whitespace-nowrap",
        ),
        rx.el.td(ago(r.created), class_name="px-2 text-slate-500"),
        rx.el.td(
            rx.cond(
                waiting & IdeState.can_decide,
                rx.el.div(
                    rx.el.button("Approve", on_click=RunState.approve(r.id), custom_attrs={"data-approve-run": r.id}, class_name=f"{BTN} h-6 bg-teal-700 hover:bg-teal-600 text-white"),
                    rx.el.button("Reject", on_click=RunState.reject(r.id), custom_attrs={"data-reject-run": r.id}, class_name=f"{BTN} h-6 bg-slate-800 hover:bg-rose-900 text-slate-200"),
                    class_name="flex gap-1",
                ),
                rx.cond(
                    r.active & IdeState.can_run,
                    rx.el.button("Stop", on_click=RunState.cancel(r.id), custom_attrs={"data-stop-run": r.id}, class_name=f"{BTN} h-6 bg-slate-800 hover:bg-rose-900 text-slate-200"),
                ),
            ),
            class_name="px-2",
        ),
        on_click=[RunState.select(r.id)],
        custom_attrs={"data-run": r.id, "data-run-status": r.status},
        class_name=rx.cond(RunState.selected == r.id, "bg-teal-500/10 cursor-pointer", "hover:bg-slate-800/60 cursor-pointer"),
    )


def runs_table() -> rx.Component:
    return rx.cond(
        ProjectRoom.runs.length() > 0,
        rx.el.table(
            rx.el.thead(rx.el.tr(*[rx.el.th(h, class_name="px-2 py-1.5 text-left font-semibold") for h in ["Status", "Flow", "Snapshot", "By", "Result", "Problems", "When", ""]], class_name="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800")),
            rx.el.tbody(rx.foreach(ProjectRoom.runs, run_row)),
            id="runs",
            class_name="w-full text-xs",
        ),
        empty("list", "No runs yet", "Start one from the Run menu."),
    )


def bottom_tab(key: str, label: str, badge: rx.Component | None = None) -> rx.Component:
    return rx.el.button(
        label,
        badge or rx.fragment(),
        on_click=IdeState.set_bottom(key),
        custom_attrs={"data-bottom": key},
        class_name=rx.cond(
            IdeState.bottom == key,
            "inline-flex items-center gap-1.5 h-8 px-3 text-xs font-semibold text-white border-b-2 border-teal-400",
            "inline-flex items-center gap-1.5 h-8 px-3 text-xs text-slate-400 hover:text-slate-200 border-b-2 border-transparent",
        ),
    )


def bottom_panel() -> rx.Component:
    counts = rx.fragment(
        rx.cond(RunState.errors > 0, rx.el.span(RunState.errors, class_name="px-1.5 rounded-full bg-rose-500/20 text-rose-300 text-[10px]")),
        rx.cond(RunState.warnings > 0, rx.el.span(RunState.warnings, class_name="px-1.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px]")),
    )
    active = rx.cond(ProjectRoom.active_runs > 0, rx.el.span(ProjectRoom.active_runs, class_name="px-1.5 rounded-full bg-sky-500/20 text-sky-300 text-[10px]"))
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                bottom_tab("problems", "Problems", counts),
                bottom_tab("output", "Output"),
                bottom_tab("wave", "Waveform"),
                bottom_tab("runs", "Runs", active),
                class_name="flex items-center",
            ),
            rx.el.button(rx.icon(rx.cond(IdeState.bottom_open, "chevron-down", "chevron-up"), class_name="h-4 w-4"), on_click=IdeState.toggle_bottom, title="Hide or show", class_name="p-1.5 text-slate-500 hover:text-white"),
            class_name="flex items-center justify-between px-2 border-b border-slate-800 shrink-0",
        ),
        rx.cond(
            IdeState.bottom_open,
            rx.el.div(
                rx.match(
                    IdeState.bottom,
                    ("problems", problems_panel()),
                    ("output", output_panel()),
                    ("wave", wave_panel()),
                    runs_table(),
                ),
                style={"height": "var(--chip-bottom, 260px)"},
                class_name="overflow-auto",
            ),
        ),
        id="bottom-panel",
        class_name="flex flex-col shrink-0 bg-slate-950 border-t border-slate-800",
    )


# ------------------------------------------------------------ right panel


def proposal_card(p) -> rx.Component:
    pending = p.status == "PROPOSED"
    return rx.el.div(
        rx.el.div(
            rx.icon("sparkles", class_name="h-3.5 w-3.5 text-violet-400 shrink-0"),
            rx.el.span(p.title, class_name="text-sm font-semibold text-slate-100 truncate"),
            class_name="flex items-center gap-1.5 min-w-0",
        ),
        rx.el.div(status_badge(p.status, small=True), rx.el.span(p.agent, " · ", ago(p.created), class_name="text-[11px] text-slate-500 truncate"), class_name="flex items-center gap-2"),
        rx.el.code(p.files, class_name="text-[11px] text-slate-400 truncate"),
        rx.cond(p.rationale != "", rx.el.p(p.rationale, class_name="text-xs text-slate-400 line-clamp-3")),
        rx.cond(p.status == "REJECTED", rx.el.p("Rejected by ", p.decided_by, ": ", p.reason, class_name="text-xs text-rose-300")),
        rx.cond(p.status == "APPROVED", rx.el.p("Accepted by ", p.decided_by, " → ", rx.el.code(p.applied), class_name="text-xs text-emerald-300")),
        rx.el.div(
            rx.el.button(rx.icon("git-compare", class_name="h-3.5 w-3.5"), "Review", on_click=ReviewState.open(p.id), custom_attrs={"data-open-proposal": p.id}, class_name=f"{BTN} h-7 bg-slate-800 hover:bg-slate-700 text-slate-200"),
            rx.cond(
                pending & IdeState.can_decide,
                rx.fragment(
                    rx.el.button("Accept", on_click=ReviewState.accept(p.id), custom_attrs={"data-accept": p.id}, class_name=f"{BTN} h-7 bg-teal-700 hover:bg-teal-600 text-white"),
                    rx.el.button("Reject", on_click=ReviewState.ask_reject(p.id), custom_attrs={"data-reject": p.id}, class_name=f"{BTN} h-7 bg-slate-800 hover:bg-rose-900 text-slate-200"),
                ),
            ),
            class_name="flex items-center gap-1.5 pt-1",
        ),
        custom_attrs={"data-proposal": p.id, "data-proposal-status": p.status},
        class_name=rx.cond(pending, "flex flex-col gap-1.5 p-3 rounded-lg border border-violet-800/60 bg-violet-950/20", "flex flex-col gap-1.5 p-3 rounded-lg border border-slate-800 bg-slate-900/50"),
    )


def ai_panel() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.p("AI agents propose; people decide. Nothing changes until someone with edit access accepts, and every accepted change becomes a snapshot.", class_name="text-xs text-slate-400"),
            rx.el.button(
                rx.icon("sparkles", class_name="h-3.5 w-3.5"), "Ask the AI",
                on_click=Intent.start(None, "ai.assist", keep_alive=True, single=True, label="AI assistant", in_app="chipova", room=IdeState.project_id),
                class_name=f"{BTN_AI} w-full justify-center",
            ),
            class_name="flex flex-col gap-2 p-3 border-b border-slate-800",
        ),
        rx.cond(
            ProjectRoom.proposals.length() > 0,
            rx.el.div(rx.foreach(ProjectRoom.proposals, proposal_card), id="proposals", class_name="flex flex-col gap-2 p-3"),
            empty("sparkles", "No proposals yet", "An AI working on this project (through the AI Hub) sends its changes here."),
        ),
    )


def people_panel() -> rx.Component:
    return rx.el.div(
        rx.foreach(
            ProjectRoom.people,
            lambda p: rx.el.div(
                face(p["name"], p["initials"], p["avatar"], p["color"], size="h-7 w-7"),
                rx.el.span(p["name"], class_name="text-sm text-slate-200 truncate"),
                rx.cond(p["user"].to(str).startswith("agent:"), rx.el.span("AI", class_name="text-[10px] px-1.5 rounded bg-violet-500/20 text-violet-300")),
                class_name="flex items-center gap-2",
            ),
        ),
        class_name="flex flex-col gap-2 p-3",
    )


def _line_spec(e: rx.Var) -> tuple[rx.Var[int]]:
    # The editor's line where the caret is, when the button is clicked (assets/chipova/collab.js).
    return (rx.Var("(window.chipCursorLine ? window.chipCursorLine() : 1)").to(int),)


class LineButton(rx.el.Button):
    on_click: rx.EventHandler[_line_spec]


def comment_row(c) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.cond(
                c.path != "",
                rx.el.button(rx.el.code(c.where), on_click=IdeState.jump(c.path, c.line, 1), class_name="text-[11px] text-teal-300 hover:underline"),
                rx.el.code(c.where, class_name="text-[11px] text-slate-400"),
            ),
            rx.el.span(c.who, " · ", ago(c.at), class_name="text-[10px] text-slate-500"),
            rx.el.button(
                rx.cond(c.resolved, "Reopen", "Resolve"),
                on_click=CommentsState.resolve(c.id, ~c.resolved),
                custom_attrs={"data-resolve": c.id},
                class_name="ml-auto text-[10px] text-slate-500 hover:text-slate-200",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.p(c.text, class_name=rx.cond(c.resolved, "text-xs text-slate-500 line-through", "text-xs text-slate-200 whitespace-pre-wrap")),
        custom_attrs={"data-comment": c.where},
        class_name="flex flex-col gap-1 p-2 rounded-lg border border-slate-800 bg-slate-900/50",
    )


def comments_panel() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.textarea(value=CommentsState.text, on_change=CommentsState.set_text, rows="2", placeholder="A comment on the line your caret is on", id="comment-text", class_name="w-full p-2 rounded-md bg-slate-950 border border-slate-700 text-sm text-slate-100 outline-none focus:border-teal-500"),
            LineButton.create(
                rx.icon("message-square-plus", class_name="h-3.5 w-3.5"),
                rx.el.span("Comment on ", rx.cond(IdeState.active_path != "", IdeState.active_path, "the file"), " at the caret"),
                on_click=CommentsState.on_line,
                id="comment-line",
                class_name=f"{BTN_OUTLINE} w-full justify-center",
            ),
            class_name="flex flex-col gap-2 p-3 border-b border-slate-800",
        ),
        rx.cond(
            ProjectRoom.comments.length() > 0,
            rx.el.div(rx.foreach(ProjectRoom.comments, comment_row), id="comments", class_name="flex flex-col gap-2 p-3"),
            empty("message-square", "No comments yet", "They sit on a line of a file, for everyone."),
        ),
    )


def activity_panel() -> rx.Component:
    return rx.cond(
        ProjectRoom.activity.length() > 0,
        rx.el.div(
            rx.foreach(
                ProjectRoom.activity,
                lambda a: rx.el.div(
                    rx.el.span(a.who, class_name="font-semibold text-slate-300"),
                    rx.el.span(" ", a.what, class_name="text-slate-400"),
                    rx.el.div(ago(a.at), class_name="text-[10px] text-slate-600"),
                    class_name="text-xs leading-snug",
                ),
            ),
            id="activity",
            class_name="flex flex-col gap-2.5 p-3",
        ),
        empty("history", "Nothing yet"),
    )


def right_tab(key: str, icon: str, label: str, badge: rx.Component | None = None) -> rx.Component:
    return rx.el.button(
        rx.icon(icon, class_name="h-3.5 w-3.5"),
        label,
        badge or rx.fragment(),
        on_click=IdeState.set_right(key),
        custom_attrs={"data-right": key},
        class_name=rx.cond(
            (IdeState.right == key) & IdeState.right_open,
            "inline-flex items-center gap-1 h-9 px-2 shrink-0 whitespace-nowrap text-xs font-semibold text-white border-b-2 border-violet-400",
            "inline-flex items-center gap-1 h-9 px-2 shrink-0 whitespace-nowrap text-xs text-slate-400 hover:text-slate-200 border-b-2 border-transparent",
        ),
    )


def right_panel() -> rx.Component:
    pending = rx.cond(ProjectRoom.pending_proposals > 0, rx.el.span(ProjectRoom.pending_proposals, class_name="px-1.5 rounded-full bg-violet-500/30 text-violet-200 text-[10px]"))
    return rx.el.aside(
        rx.el.div(
            right_tab("ai", "sparkles", "AI review", pending),
            right_tab("comments", "message-square", "Comments", rx.cond(ProjectRoom.open_comments > 0, rx.el.span(ProjectRoom.open_comments, class_name="px-1.5 rounded-full bg-slate-700 text-slate-200 text-[10px]"))),
            right_tab("people", "users", "People"),
            right_tab("activity", "history", "Activity"),
            # A narrow panel scrolls its tabs rather than wrapping them.
            class_name="flex items-center border-b border-slate-800 shrink-0 px-1 overflow-x-auto",
        ),
        rx.cond(
            IdeState.right_open,
            rx.el.div(
                rx.match(IdeState.right, ("people", people_panel()), ("activity", activity_panel()), ("comments", comments_panel()), ai_panel()),
                class_name="flex-1 overflow-y-auto",
            ),
        ),
        id="right-pane",
        style={"width": rx.cond(IdeState.right_open, "var(--chip-right, 330px)", "auto")},
        class_name="shrink-0 flex flex-col bg-slate-950 border-l border-slate-800 min-h-0",
    )


# ------------------------------------------------------------ status bar


def status_bar() -> rx.Component:
    return rx.el.footer(
        rx.el.div(
            rx.el.span(id="chip-sync", class_name="inline-flex items-center gap-1.5", custom_attrs={"data-state": "idle"}),
            rx.el.span(
                "snapshot ", rx.el.code(ProjectRoom.latest_short, class_name="text-teal-300"),
                rx.cond(ProjectRoom.latest_by != "", rx.el.span(" by ", ProjectRoom.latest_by)),
                " · ", ago(ProjectRoom.latest_at),
                rx.cond(ProjectRoom.dirty, rx.el.span(" · editors changed since", class_name="text-amber-300")),
                id="status-snapshot",
            ),
            class_name="flex items-center gap-4 min-w-0",
        ),
        rx.el.div(
            rx.cond(ProjectRoom.settings_error != "", rx.el.span(ProjectRoom.settings_error, class_name="text-rose-300 truncate max-w-[30rem]")),
            rx.el.span(IdeState.active_path, class_name="font-mono"),
            rx.el.span(IdeState.role),
            class_name="flex items-center gap-4 min-w-0",
        ),
        rx.el.div(
            id="chip-problems",
            custom_attrs={"data-problems": RunState.problems_json, "data-run": RunState.selected},
            class_name="hidden",
        ),
        rx.el.div(id="chip-comments", custom_attrs={"data-lines": ProjectRoom.comment_lines}, class_name="hidden"),
        class_name="flex items-center justify-between gap-4 px-3 h-6 shrink-0 bg-slate-950 border-t border-slate-800 text-[11px] text-slate-400",
    )


def splitter(kind: str, var: str) -> rx.Component:
    """A handle that resizes a panel (assets/chipova/ide.js), kept per browser."""
    horizontal = kind == "row"
    return rx.el.div(
        custom_attrs={"data-splitter": var, "data-axis": "y" if horizontal else "x"},
        class_name="shrink-0 bg-slate-800/40 hover:bg-teal-600/50 transition-colors " + ("h-1 cursor-row-resize" if horizontal else "w-1 cursor-col-resize"),
    )


def code_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            explorer(),
            splitter("col", "--chip-explorer"),
            rx.el.div(
                center(),
                splitter("row", "--chip-bottom"),
                bottom_panel(),
                class_name="flex flex-col flex-1 min-w-0 min-h-0",
            ),
            rx.cond(IdeState.right_open, splitter("col", "--chip-right")),
            right_panel(),
            class_name="flex flex-1 min-h-0",
        ),
        status_bar(),
        id="code-view",
        class_name="flex flex-col h-full",
    )
