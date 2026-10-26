"""The Tools & settings page (/settings): tool profiles, PDKs, run limits, connections."""

from __future__ import annotations

import reflex as rx

from chipova.components.common import BTN_OUTLINE, BTN_PRIMARY, LABEL, PANEL, logo
from chipova.components.together import identity
from chipova.states.admin_state import AdminState


def profile_card(p) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(p.title, class_name="text-base font-semibold text-slate-100"),
                rx.cond(
                    p.installed,
                    rx.el.span("installed", class_name="text-[11px] px-2 rounded border border-emerald-600/40 text-emerald-300 bg-emerald-500/10"),
                    rx.el.span("not installed", class_name="text-[11px] px-2 rounded border border-slate-600 text-slate-400"),
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.p(p.description, class_name="text-sm text-slate-400"),
            rx.el.div(
                rx.el.span("image ", rx.el.code(p.image, class_name="text-slate-300")),
                rx.el.span("base ", rx.el.code(p.base, class_name="text-slate-300 break-all")),
                rx.el.span(p.size),
                class_name="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500",
            ),
            rx.el.p("Runs: ", p.flows, class_name="text-xs text-slate-400"),
            class_name="flex flex-col gap-1.5",
        ),
        rx.cond(
            p.status == "installing",
            rx.el.div(rx.icon("loader", class_name="h-4 w-4 animate-spin text-sky-400"), rx.el.code(p.line, class_name="text-xs text-slate-300 truncate"), class_name="flex items-center gap-2"),
        ),
        rx.cond(p.status == "error", rx.el.p(p.line, class_name="text-xs text-rose-300 break-all")),
        rx.cond(
            p.installed,
            rx.el.div(
                rx.el.span("Tool versions, recorded with every run", class_name=LABEL),
                rx.el.div(
                    rx.foreach(p.versions, lambda v: rx.el.div(rx.el.code(v.tool, class_name="text-slate-400 w-32 shrink-0"), rx.el.code(v.version, class_name="text-slate-200 break-all"), class_name="flex gap-3 text-xs")),
                    class_name="flex flex-col gap-1",
                ),
                rx.el.span("image id ", rx.el.code(p.image_id), class_name="text-[11px] text-slate-500"),
                class_name="flex flex-col gap-2",
            ),
        ),
        rx.el.div(
            rx.cond(
                ~p.installed & (p.status != "installing"),
                rx.el.button(rx.icon("download", class_name="h-3.5 w-3.5"), "Install", on_click=AdminState.install(p.id), custom_attrs={"data-install": p.id}, class_name=BTN_PRIMARY),
            ),
            rx.cond(p.installed, rx.el.button("Read versions again", on_click=AdminState.probe(p.id), class_name=BTN_OUTLINE)),
            rx.cond(p.installed & (p.status != "installing"), rx.el.button("Rebuild", on_click=AdminState.install(p.id), class_name=BTN_OUTLINE)),
            class_name="flex gap-2",
        ),
        custom_attrs={"data-profile": p.id},
        class_name=f"{PANEL} p-5 flex flex-col gap-4",
    )


def admin_page() -> rx.Component:
    return rx.el.div(
        rx.el.header(
            rx.el.div(logo(), rx.el.span("Tools & settings", class_name="text-sm text-slate-400"), class_name="flex items-center gap-3"),
            identity(),
            class_name="flex justify-between items-center px-6 bg-slate-950 border-b border-slate-800 h-14",
        ),
        rx.el.main(
            rx.el.div(
                rx.el.h1("Tool profiles", class_name="text-2xl font-bold text-slate-100"),
                rx.el.p(
                    "Every EDA run is a container of one of these images, with no network, as an unprivileged user, with CPU, memory, process and time limits. Each image is built from a Dockerfile in infra/dockerfiles on a base pinned by digest; its tools' versions are recorded with every run.",
                    class_name="text-sm text-slate-400 max-w-3xl",
                ),
                class_name="flex flex-col gap-1",
            ),
            rx.cond(
                AdminState.docker_ok,
                rx.fragment(),
                rx.el.div(rx.icon("triangle-alert", class_name="h-4 w-4"), "Docker isn't reachable: ", AdminState.docker_error, class_name="flex items-center gap-2 p-3 rounded-lg border border-rose-700/50 bg-rose-950/30 text-sm text-rose-300"),
            ),
            rx.el.div(rx.foreach(AdminState.rows, profile_card), id="profiles", class_name="flex flex-col gap-4"),
            rx.el.div(
                rx.el.span("PDK registry", class_name=LABEL),
                rx.el.p("What Build ASIC and the layout checks can do for each PDK in the IIC-OSIC-TOOLS profile. None of these results is a foundry's signoff.", class_name="text-sm text-slate-400"),
                rx.el.table(
                    rx.el.thead(rx.el.tr(*[rx.el.th(h, class_name="px-2 py-1 text-left font-semibold") for h in ["PDK (chipova.toml)", "", "Build ASIC", "DRC", "LVS"]], class_name="text-[10px] uppercase tracking-wider text-slate-500")),
                    rx.el.tbody(
                        rx.foreach(
                            AdminState.pdks,
                            lambda p: rx.el.tr(
                                rx.el.td(rx.el.code(p.id, class_name="text-teal-300"), class_name="px-2 py-2 align-top"),
                                rx.el.td(rx.el.div(rx.el.span(p.title, class_name="text-slate-200"), rx.el.span(p.status, class_name="text-xs text-slate-500"), class_name="flex flex-col"), class_name="px-2 py-2 align-top"),
                                rx.el.td(rx.cond(p.flow, rx.el.span("yes", class_name="text-emerald-400"), rx.el.span("not yet", class_name="text-slate-500")), class_name="px-2 py-2 align-top"),
                                rx.el.td(rx.cond(p.drc != "", rx.el.span(p.drc, class_name="text-xs text-slate-300"), rx.el.span("not set up", class_name="text-slate-500")), class_name="px-2 py-2 align-top"),
                                rx.el.td(rx.cond(p.lvs != "", rx.el.span(p.lvs, class_name="text-xs text-slate-300"), rx.el.span("not set up", class_name="text-slate-500")), class_name="px-2 py-2 align-top"),
                                class_name="border-b border-slate-800/60 text-sm",
                            ),
                        ),
                    ),
                    id="pdks",
                    class_name="w-full",
                ),
                class_name=f"{PANEL} p-5 flex flex-col gap-2",
            ),
            rx.el.div(
                rx.el.span("Runs", class_name=LABEL),
                rx.el.p("At most ", AdminState.max_parallel, " runs at once (CHIPOVA_MAX_PARALLEL_RUNS); the others wait in the queue in order. Each person can have 20 runs waiting.", class_name="text-sm text-slate-400"),
                class_name=f"{PANEL} p-5 flex flex-col gap-2",
            ),
            rx.el.div(
                rx.el.span("AI agents", class_name=LABEL),
                rx.el.p("Chipova's tools are offered to the platform's AI Hub; agents connect to the hub at ", rx.el.code(AdminState.hub_address, class_name="text-teal-300"), ".", class_name="text-sm text-slate-400"),
                class_name=f"{PANEL} p-5 flex flex-col gap-2",
            ),
            class_name="max-w-5xl mx-auto px-6 py-8 flex flex-col gap-6",
        ),
        on_mount=AdminState.load,
        class_name="min-h-screen bg-slate-950 font-sans text-slate-200",
    )
