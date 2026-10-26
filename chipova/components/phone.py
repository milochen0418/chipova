"""The workspace on a phone (blueprint §4.4): the AI's proposals to decide on, runs to follow and
approve, comments, the files to read (a line picked for a comment), who is here and what happened.
Editing code needs a wider screen; the other views stack their columns. A bar at the bottom takes
the rail's place."""

from __future__ import annotations

import reflex as rx

from chipova.components.code_view import activity_panel, ai_panel, comment_row, output_panel, people_panel, proposal_view
from chipova.components.common import BTN, BTN_OUTLINE, LABEL, ago, empty, status_badge
from chipova.components.together import identity
from chipova.states.comments_state import CommentsState
from chipova.states.ide import IdeState
from chipova.states.phone_state import PhoneState
from chipova.states.review_state import ReviewState
from chipova.states.room import ProjectRoom
from chipova.states.runs_state import RunState

TABS = [("ai", "sparkles", "AI"), ("runs", "list-checks", "Runs"), ("comments", "message-square", "Comments"), ("files", "files", "Files"), ("people", "users", "People")]


def top_bar(ai_button: rx.Component) -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.icon("cpu", class_name="h-5 w-5 text-teal-400 shrink-0"),
            rx.el.div(
                rx.el.span(ProjectRoom.title, id="project-title", class_name="text-sm font-semibold text-slate-100 truncate"),
                rx.el.span(IdeState.role, id="my-role", class_name="text-[10px] text-slate-500 uppercase tracking-wider"),
                class_name="flex flex-col leading-tight min-w-0",
            ),
            class_name="flex items-center gap-2 min-w-0",
        ),
        rx.el.div(
            ai_button,
            rx.el.span(ProjectRoom.people_count, " here", id="people-count", class_name="text-xs text-slate-400 whitespace-nowrap"),
            identity(),
            class_name="flex items-center gap-2 shrink-0",
        ),
        class_name="flex justify-between items-center px-3 h-12 gap-2 bg-slate-950 border-b border-slate-800 shrink-0",
    )


def nav(items: list[tuple[str, str, str, str]]) -> rx.Component:
    return rx.el.nav(
        *[
            rx.el.button(
                rx.icon(icon, class_name="h-5 w-5"),
                rx.el.span(title, class_name="text-[9px]"),
                on_click=IdeState.set_view(view),
                custom_attrs={"data-view": view},
                class_name=rx.cond(
                    IdeState.view == view,
                    "flex-1 flex flex-col items-center justify-center gap-0.5 text-teal-300 bg-teal-500/10",
                    "flex-1 flex flex-col items-center justify-center gap-0.5 text-slate-500",
                ),
            )
            for view, icon, title, _ in items
        ],
        class_name="fixed bottom-0 inset-x-0 h-14 flex bg-slate-950 border-t border-slate-800 z-40",
    )


def tabs() -> rx.Component:
    return rx.el.div(
        *[
            rx.el.button(
                rx.icon(icon, class_name="h-3.5 w-3.5"), label,
                on_click=IdeState.set_phone_tab(key),
                custom_attrs={"data-phone-tab": key},
                class_name=rx.cond(
                    IdeState.phone_tab == key,
                    "inline-flex items-center gap-1 h-9 px-3 shrink-0 text-xs font-semibold text-white border-b-2 border-violet-400",
                    "inline-flex items-center gap-1 h-9 px-3 shrink-0 text-xs text-slate-400 border-b-2 border-transparent",
                ),
            )
            for key, icon, label in TABS
        ],
        class_name="flex overflow-x-auto border-b border-slate-800 shrink-0",
    )


def run_card(r) -> rx.Component:  # noqa: ANN001
    return rx.el.div(
        rx.el.div(
            status_badge(r.status, small=True),
            rx.el.span(r.title, class_name="text-sm text-slate-100 truncate"),
            class_name="flex items-center gap-2 min-w-0",
        ),
        rx.el.div(
            rx.el.code(r.snapshot, class_name="text-teal-300"),
            rx.el.span(r.by),
            ago(r.created),
            class_name="flex items-center gap-2 text-[11px] text-slate-500",
        ),
        rx.cond(r.summary != "", rx.el.span(r.summary, class_name="text-xs text-slate-300")),
        rx.cond(
            (r.status == "WAITING") & IdeState.can_decide,
            rx.el.div(
                rx.el.button("Approve", on_click=RunState.approve(r.id), custom_attrs={"data-approve-run": r.id}, class_name=f"{BTN} h-8 px-4 bg-teal-700 text-white"),
                rx.el.button("Reject", on_click=RunState.reject(r.id), custom_attrs={"data-reject-run": r.id}, class_name=f"{BTN} h-8 px-4 bg-slate-800 text-slate-200"),
                class_name="flex gap-2 mt-1",
            ),
            rx.cond(r.active & IdeState.can_run, rx.el.button("Stop", on_click=RunState.cancel(r.id), custom_attrs={"data-stop-run": r.id}, class_name=f"{BTN} h-8 px-4 mt-1 bg-slate-800 text-slate-200 self-start")),
        ),
        on_click=RunState.select(r.id),
        custom_attrs={"data-run": r.id, "data-run-status": r.status},
        class_name=rx.cond(
            RunState.selected == r.id,
            "flex flex-col gap-1 p-3 rounded-lg border border-teal-600/50 bg-teal-500/10",
            "flex flex-col gap-1 p-3 rounded-lg border border-slate-800 bg-slate-900/50",
        ),
    )


def runs() -> rx.Component:
    return rx.el.div(
        rx.cond(
            ProjectRoom.runs.length() > 0,
            rx.el.div(rx.foreach(ProjectRoom.runs, run_card), id="runs", class_name="flex flex-col gap-2 p-3"),
            empty("list", "No runs yet", "Start one from a wider screen, or let the AI."),
        ),
        rx.cond(RunState.selected != "", rx.el.div(output_panel(), class_name="border-t border-slate-800 h-[45dvh] flex flex-col")),
    )


def comment_box(where: rx.Component) -> rx.Component:
    return rx.el.div(
        rx.el.textarea(value=CommentsState.text, on_change=CommentsState.set_text, rows="2", placeholder="A comment", id="comment-text",
                       class_name="w-full p-2 rounded-md bg-slate-950 border border-slate-700 text-sm text-slate-100 outline-none focus:border-teal-500"),
        rx.el.button(
            rx.icon("message-square-plus", class_name="h-3.5 w-3.5"), "Comment on ", where,
            on_click=CommentsState.on_line(rx.cond(PhoneState.line > 0, PhoneState.line, 1)),
            id="comment-line",
            class_name=f"{BTN_OUTLINE} w-full justify-center",
        ),
        class_name="flex flex-col gap-2 p-3 border-b border-slate-800",
    )


def comments() -> rx.Component:
    return rx.el.div(
        rx.cond(
            IdeState.active_path != "",
            comment_box(rx.el.span(IdeState.active_path, ":", rx.cond(PhoneState.line > 0, PhoneState.line, 1))),
            rx.el.p("Open a file under Files and tap a line to comment on it.", class_name="p-3 text-xs text-slate-500 border-b border-slate-800"),
        ),
        rx.cond(
            ProjectRoom.comments.length() > 0,
            rx.el.div(rx.foreach(ProjectRoom.comments, comment_row), id="comments", class_name="flex flex-col gap-2 p-3"),
            empty("message-square", "No comments yet", "They sit on a line of a file, for everyone."),
        ),
    )


def files() -> rx.Component:
    reader = rx.el.div(
        rx.el.div(
            rx.el.button(rx.icon("arrow-left", class_name="h-4 w-4"), on_click=PhoneState.close, id="phone-file-back", class_name=BTN_OUTLINE),
            rx.el.code(PhoneState.path, class_name="text-xs text-slate-200 truncate"),
            class_name="flex items-center gap-2 p-2 border-b border-slate-800 sticky top-0 bg-slate-950",
        ),
        rx.cond(PhoneState.line > 0, comment_box(rx.el.span("line ", PhoneState.line))),
        rx.el.div(
            rx.foreach(
                PhoneState.lines,
                lambda text, i: rx.el.div(
                    rx.el.span(i + 1, class_name="w-9 shrink-0 text-right pr-2 text-slate-600 select-none"),
                    rx.el.span(text, class_name="whitespace-pre text-slate-200"),
                    on_click=PhoneState.pick_line(i + 1),
                    custom_attrs={"data-phone-line": i + 1},
                    class_name=rx.cond(PhoneState.line == i + 1, "flex bg-teal-500/15", "flex"),
                ),
            ),
            id="phone-file",
            class_name="font-mono text-[11px] leading-5 overflow-x-auto py-1",
        ),
    )
    listing = rx.el.div(
        rx.el.span("Files (to read; editing needs a wider screen)", class_name=f"{LABEL} px-1"),
        rx.foreach(
            ProjectRoom.files,
            lambda f: rx.cond(
                f.kind == "file",
                rx.el.button(
                    rx.icon("file", class_name="h-3.5 w-3.5 text-slate-500"), rx.el.span(f.path, class_name="truncate"),
                    on_click=PhoneState.read(f.id),
                    custom_attrs={"data-phone-file": f.path},
                    class_name="flex items-center gap-2 w-full px-2 py-2 rounded text-sm text-slate-200 hover:bg-slate-800/60",
                ),
            ),
        ),
        class_name="flex flex-col gap-0.5 p-2",
    )
    return rx.cond(PhoneState.file_id != "", reader, listing)


def code() -> rx.Component:
    """The phone's Code view: an open proposal fills it; otherwise its tabs."""
    return rx.cond(
        ReviewState.open_id != "",
        rx.el.div(proposal_view(), class_name="flex flex-col"),
        rx.el.div(
            tabs(),
            rx.match(
                IdeState.phone_tab,
                ("runs", runs()),
                ("comments", comments()),
                ("files", files()),
                ("people", rx.el.div(people_panel(), activity_panel())),
                ai_panel(),
            ),
            class_name="flex flex-col",
        ),
    )


def phone_workspace(views: dict[str, rx.Component], nav_items: list, ai_button: rx.Component) -> rx.Component:
    return rx.el.div(
        top_bar(ai_button),
        rx.el.main(
            rx.match(IdeState.view, *[(k, v) for k, v in views.items() if k != "code"], code()),
            class_name="flex-1 min-h-0 overflow-y-auto pb-16",
        ),
        nav(nav_items),
        class_name="h-[100dvh] flex flex-col bg-slate-950 text-slate-200 font-sans overflow-hidden",
    )
