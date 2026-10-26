"""The project list (/)."""

from __future__ import annotations

import reflex as rx

from chipova.components.common import BTN_GHOST, BTN_PRIMARY, INPUT, ago, logo, status_badge
from chipova.components.together import face, identity
from chipova.states.home_state import HomeState


def header() -> rx.Component:
    return rx.el.header(
        logo(),
        rx.el.div(
            rx.el.a(rx.icon("settings", class_name="h-4 w-4"), rx.el.span("Tools & settings", class_name="hidden sm:inline"), href="/settings", class_name=BTN_GHOST, id="admin-link"),
            identity(),
            class_name="flex items-center gap-3",
        ),
        class_name="flex justify-between items-center px-4 sm:px-6 bg-slate-950/80 backdrop-blur border-b border-slate-800 h-14 gap-4 sticky top-0 z-20",
    )


def kind_icon(kind: rx.Var) -> rx.Component:
    return rx.match(
        kind,
        ("FPGA", rx.icon("grid-3x3", class_name="h-5 w-5 text-amber-300")),
        ("Analog / AMS", rx.icon("activity", class_name="h-5 w-5 text-pink-300")),
        rx.icon("cpu", class_name="h-5 w-5 text-teal-300"),
    )


def row(r) -> rx.Component:
    return rx.el.div(
        rx.el.a(
            rx.el.div(
                rx.el.div(kind_icon(r.kind), class_name="h-11 w-11 rounded-lg bg-slate-800/80 border border-slate-700 flex items-center justify-center shrink-0"),
                rx.el.div(
                    rx.el.div(
                        rx.el.span(r.title, class_name="text-[15px] font-semibold text-slate-100 truncate group-hover:text-teal-300"),
                        rx.cond(r.private, rx.el.span(rx.icon("lock", class_name="h-3 w-3"), "private", class_name="inline-flex items-center gap-1 text-[10px] text-slate-400 border border-slate-700 rounded px-1.5")),
                        class_name="flex items-center gap-2 min-w-0",
                    ),
                    rx.el.span(
                        r.kind, " · ", ago(r.updated, ""),
                        rx.cond(r.owner != "", rx.el.span(" · ", r.owner)),
                        rx.cond(r.snapshot != "", rx.el.span(" · snapshot ", rx.el.code(r.snapshot, class_name="text-slate-300"))),
                        class_name="text-xs text-slate-400 truncate",
                    ),
                    class_name="flex flex-col min-w-0 gap-0.5",
                ),
                class_name="flex items-center gap-3 min-w-0 flex-1",
            ),
            rx.el.div(
                rx.cond(
                    r.last_status != "",
                    rx.el.div(status_badge(r.last_status, small=True), rx.el.span(r.last_run, class_name="text-xs text-slate-400 truncate max-w-[14rem]"), class_name="hidden md:flex items-center gap-2"),
                ),
                rx.cond(
                    r.people.length() > 0,
                    rx.el.div(
                        rx.el.div(rx.foreach(r.people, lambda p: face(p.name, p.initials, p.avatar, p.color, size="h-6 w-6")), class_name="flex items-center -space-x-1.5"),
                        rx.el.span(r.people.length(), " here", class_name="text-xs font-medium text-teal-300"),
                        class_name="flex items-center gap-2 px-2 py-1 rounded-full bg-teal-950/50 border border-teal-900 shrink-0",
                    ),
                ),
                class_name="flex items-center gap-3 shrink-0",
            ),
            href="/p/" + r.id,
            class_name="group flex items-center justify-between gap-4 flex-1 min-w-0 px-3 py-2.5",
        ),
        rx.menu.root(
            rx.menu.trigger(rx.el.button(rx.icon("ellipsis", class_name="h-4 w-4"), type="button", title="More", class_name="p-2 mr-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-100")),
            rx.menu.content(
                rx.menu.item("Open", on_select=rx.redirect("/p/" + r.id)),
                rx.cond(r.may_delete, rx.menu.separator()),
                rx.cond(r.may_delete, rx.menu.item("Delete", color="red", on_select=HomeState.ask_delete(r.id, r.title))),
            ),
        ),
        class_name="flex items-center bg-slate-900/70 border border-slate-800 rounded-xl hover:border-teal-800 transition-colors",
        custom_attrs={"data-project": r.id},
    )


def template_card(t) -> rx.Component:
    selected = HomeState.new_template == t.id
    return rx.el.button(
        rx.el.div(kind_icon(t.kind), class_name="mt-0.5"),
        rx.el.div(
            rx.el.p(t.title, class_name="text-sm font-semibold text-slate-100"),
            rx.el.p(t.description, class_name="text-xs text-slate-400 leading-relaxed"),
            class_name="flex flex-col gap-1 text-left",
        ),
        on_click=HomeState.set_new_template(t.id),
        type="button",
        custom_attrs={"data-template": t.id},
        class_name=rx.cond(
            selected,
            "flex items-start gap-3 w-full p-3 rounded-xl border border-teal-500 bg-teal-950/40",
            "flex items-start gap-3 w-full p-3 rounded-xl border border-slate-700 hover:border-slate-500 bg-slate-900",
        ),
    )


def new_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("New project"),
            rx.dialog.description("Start from a template: it comes with sources, a testbench and settings, and its first snapshot.", size="2"),
            rx.el.input(
                value=HomeState.new_title,
                on_change=HomeState.set_new_title,
                placeholder="Name (optional)",
                id="new-title",
                class_name=f"{INPUT} w-full mt-3",
            ),
            rx.el.div(rx.foreach(HomeState.template_rows, template_card), class_name="grid sm:grid-cols-2 gap-2 mt-3"),
            rx.el.div(
                rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.button("Create", on_click=HomeState.create, loading=HomeState.busy, id="create-project", color_scheme="teal"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="680px",
        ),
        open=HomeState.new_open,
        on_open_change=HomeState.set_new_open,
    )


def delete_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete this project?"),
            rx.alert_dialog.description(rx.el.span(rx.el.b(HomeState.confirm_title), " with its files, snapshots and runs will be gone for everyone. The audit log keeps its history.")),
            rx.el.div(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray", on_click=HomeState.cancel_delete)),
                rx.alert_dialog.action(rx.button("Delete", color_scheme="red", on_click=HomeState.delete, id="confirm-delete")),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="460px",
        ),
        open=HomeState.confirm_id != "",
    )


_REFRESH_JS = """
if (window.__chipHome) clearInterval(window.__chipHome);
window.__chipHome = setInterval(function () {
    var el = document.getElementById('chip-home-refresh');
    if (!el) { clearInterval(window.__chipHome); window.__chipHome = null; return; }
    if (!document.hidden) el.click();
}, 8000);
"""


def pillar(icon: str, title: str, text: str) -> rx.Component:
    return rx.el.div(
        rx.icon(icon, class_name="h-4 w-4 text-teal-400 shrink-0 mt-0.5"),
        rx.el.div(rx.el.p(title, class_name="text-sm font-semibold text-slate-200"), rx.el.p(text, class_name="text-xs text-slate-400"), class_name="flex flex-col gap-0.5"),
        class_name="flex gap-2.5",
    )


def home_page() -> rx.Component:
    return rx.el.div(
        header(),
        rx.el.main(
            rx.el.section(
                rx.el.div(
                    rx.el.h1("Chip projects", class_name="text-2xl font-bold tracking-tight text-slate-100"),
                    rx.el.p(
                        "Design chips together with your team and AI agents: co-edit the RTL live, run lint, simulation, synthesis, FPGA and RTL-to-GDSII flows in sealed containers, and keep every result traceable to its snapshot.",
                        class_name="mt-1 text-sm text-slate-400 max-w-2xl",
                    ),
                ),
                rx.el.button(rx.icon("plus", class_name="h-4 w-4"), "New project", on_click=HomeState.open_new, type="button", id="new-project", class_name=f"{BTN_PRIMARY} h-9 px-4"),
                class_name="flex flex-wrap items-end justify-between gap-4",
            ),
            rx.el.div(
                pillar("users", "Together", "Everyone edits the same files live, with their own cursor."),
                pillar("box", "Sealed runs", "Every run is a container with no network, on a frozen snapshot."),
                pillar("sparkles", "AI proposes, people decide", "Agents send patches; nothing changes until someone accepts."),
                pillar("shield-check", "Honest signoff", "A check that didn't run never shows as passed."),
                class_name="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6 p-4 rounded-xl bg-slate-900/40 border border-slate-800",
            ),
            rx.el.div(
                rx.icon("search", class_name="h-4 w-4 text-slate-500"),
                rx.el.input(value=HomeState.query, on_change=HomeState.set_query, placeholder="Search projects", id="search", class_name="flex-1 bg-transparent outline-none text-sm text-slate-200 placeholder:text-slate-500"),
                class_name="mt-6 flex items-center gap-2 h-10 px-3 rounded-lg border border-slate-800 bg-slate-900 focus-within:border-teal-700",
            ),
            rx.cond(
                HomeState.shown.length() > 0,
                rx.el.div(rx.foreach(HomeState.shown, row), id="project-list", class_name="mt-4 flex flex-col gap-2"),
                rx.cond(
                    HomeState.loaded,
                    rx.el.div(
                        rx.icon("cpu", class_name="h-12 w-12 text-slate-700"),
                        rx.el.p(rx.cond(HomeState.query != "", "No project matches.", "No projects yet."), class_name="text-slate-400 font-medium"),
                        rx.cond(HomeState.query == "", rx.button("Start with the Heartbeat", on_click=HomeState.open_new, color_scheme="teal", id="empty-new")),
                        class_name="mt-16 flex flex-col items-center gap-4",
                    ),
                ),
            ),
            class_name="max-w-5xl mx-auto px-4 sm:px-6 py-8",
        ),
        new_dialog(),
        delete_dialog(),
        rx.el.button(id="chip-home-refresh", on_click=HomeState.refresh, on_mount=rx.call_script(_REFRESH_JS), tab_index=-1, aria_hidden="true", class_name="sr-only"),
        class_name="min-h-screen bg-slate-950 font-sans text-slate-200",
    )
