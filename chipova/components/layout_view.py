"""The Layout section: a GDS of a run, drawn at any zoom by KLayout (assets/chipova/layout.js
asks the backend for the window it shows), with its layers, cells, a ruler, notes everyone sees,
and jumping to where someone else looks."""

from __future__ import annotations

import reflex as rx

from chipova.components.common import BTN_OUTLINE, INPUT, LABEL, PANEL, ago, empty, section_title
from chipova.components.links import backend_base
from chipova.states.ide import IdeState
from chipova.states.layout_state import LayoutState
from chipova.states.room import ProjectRoom


def _xy_spec(e: rx.Var) -> tuple[rx.Var[float], rx.Var[float]]:
    # The viewer puts the clicked point (µm) on the button before clicking it.
    return (
        rx.Var(f"parseFloat({e}.currentTarget.dataset.x)").to(float),
        rx.Var(f"parseFloat({e}.currentTarget.dataset.y)").to(float),
    )


def _box_spec(e: rx.Var) -> tuple[rx.Var[float], rx.Var[float], rx.Var[float], rx.Var[float]]:
    return tuple(rx.Var(f"parseFloat({e}.currentTarget.dataset.{k})").to(float) for k in ("x0", "y0", "x1", "y1"))  # type: ignore[return-value]


class XYButton(rx.el.Button):
    on_click: rx.EventHandler[_xy_spec]


class BoxButton(rx.el.Button):
    on_click: rx.EventHandler[_box_spec]


def gds_list() -> rx.Component:
    return rx.el.div(
        rx.foreach(
            LayoutState.gds,
            lambda g: rx.el.button(
                rx.el.code(g.name.split("/")[-1], class_name="text-xs text-slate-200 truncate"),
                rx.el.span(g.flow, " · ", rx.el.code(g.snapshot, class_name="text-teal-300"), " · ", g.size, class_name="text-[11px] text-slate-500"),
                on_click=LayoutState.open(g.id),
                custom_attrs={"data-gds": g.id},
                class_name=rx.cond(
                    LayoutState.selected == g.id,
                    "flex flex-col items-start gap-0.5 w-full px-3 py-2 rounded-lg bg-teal-500/10 border border-teal-700/50",
                    "flex flex-col items-start gap-0.5 w-full px-3 py-2 rounded-lg hover:bg-slate-800/60 border border-transparent",
                ),
            ),
        ),
        class_name="flex flex-col gap-1",
    )


def layer_list() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.span("Layers", class_name=LABEL),
            rx.el.div(
                rx.el.button("all", on_click=LayoutState.all_layers(True), class_name="text-[11px] text-slate-400 hover:text-white"),
                rx.el.button("none", on_click=LayoutState.all_layers(False), class_name="text-[11px] text-slate-400 hover:text-white"),
                class_name="flex gap-2",
            ),
            class_name="flex items-center justify-between",
        ),
        rx.el.div(
            rx.foreach(
                LayoutState.layers,
                lambda layer: rx.el.label(
                    rx.el.input(type="checkbox", checked=~layer.hidden, on_change=LayoutState.toggle_layer(layer.key), custom_attrs={"data-layer": layer.key}),
                    rx.el.span(class_name="h-3 w-3 rounded-sm shrink-0", style={"backgroundColor": layer.color}),
                    rx.el.code(layer.key, class_name="text-[11px] text-slate-300"),
                    rx.el.span(layer.name, class_name="text-[11px] text-slate-500 truncate"),
                    class_name="flex items-center gap-2 cursor-pointer",
                ),
            ),
            class_name="flex flex-col gap-1 max-h-72 overflow-y-auto",
        ),
        class_name="flex flex-col gap-2",
    )


def markers_list() -> rx.Component:
    return rx.cond(
        LayoutState.drc_run != "",
        rx.el.div(
            rx.el.span("DRC markers", class_name=LABEL),
            rx.cond(
                LayoutState.markers.length() > 0,
                rx.foreach(
                    LayoutState.markers,
                    lambda m: rx.el.button(
                        rx.el.code(m.rule, class_name="text-xs text-rose-300"),
                        rx.el.span("(", m.x0.to(str), ", ", m.y0.to(str), ") µm", class_name="text-[10px] text-slate-500"),
                        on_click=rx.call_script("window.chipLayoutGotoBox && window.chipLayoutGotoBox(" + m.box + ", true)"),
                        custom_attrs={"data-marker": m.rule},
                        class_name="flex items-center justify-between gap-2 w-full px-2 py-1 rounded hover:bg-slate-800/60",
                    ),
                ),
                rx.el.p("The DRC of this layout found nothing.", class_name="text-xs text-emerald-300"),
            ),
            rx.el.span("from ", rx.el.code(LayoutState.drc_run), class_name="text-[10px] text-slate-500"),
            class_name="flex flex-col gap-1",
        ),
    )


def notes_list() -> rx.Component:
    return rx.el.div(
        rx.el.span("Notes", class_name=LABEL),
        rx.foreach(
            ProjectRoom.layout_notes,
            lambda n: rx.cond(
                n.artifact == LayoutState.selected,
                rx.el.button(
                    rx.el.span(n.text, class_name="text-xs text-slate-200 text-left"),
                    rx.el.span(n.who, " · ", ago(n.at), " · (", n.x.to(str), ", ", n.y.to(str), ") µm", class_name="text-[10px] text-slate-500"),
                    on_click=rx.call_script("window.chipLayoutGoto && window.chipLayoutGoto(" + n.x.to(str) + ", " + n.y.to(str) + ")"),
                    class_name="flex flex-col items-start gap-0.5 w-full px-2 py-1.5 rounded hover:bg-slate-800/60",
                ),
            ),
        ),
        class_name="flex flex-col gap-1",
    )


def viewer() -> rx.Component:
    shared = ProjectRoom.shared_view
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.code(LayoutState.top, class_name="text-sm text-slate-100"),
                rx.el.span(LayoutState.size_text, class_name="text-xs text-slate-400"),
                rx.el.span(LayoutState.cell_count, " cells", class_name="text-xs text-slate-500"),
                class_name="flex items-center gap-3",
            ),
            rx.el.div(
                rx.el.button(rx.icon("maximize", class_name="h-3.5 w-3.5"), "Fit", on_click=rx.call_script("window.chipLayoutFit && window.chipLayoutFit()"), class_name=BTN_OUTLINE),
                rx.el.button(rx.icon("ruler", class_name="h-3.5 w-3.5"), "Measure", on_click=rx.call_script("window.chipLayoutRuler && window.chipLayoutRuler()"), id="layout-ruler", title="Drag to measure (or hold Shift and drag)", class_name=BTN_OUTLINE),
                rx.el.input(value=LayoutState.note_text, on_change=LayoutState.set_note_text, placeholder="A note…", id="layout-note-text", class_name=f"{INPUT} h-8 w-48"),
                rx.el.button(
                    rx.icon("map-pin", class_name="h-3.5 w-3.5"),
                    rx.cond(LayoutState.adding_note, "Click on the layout", "Pin it"),
                    on_click=LayoutState.toggle_adding_note,
                    id="layout-pin",
                    class_name=rx.cond(LayoutState.adding_note, f"{BTN_OUTLINE} border-amber-500 text-amber-300", BTN_OUTLINE),
                ),
                rx.el.button(rx.icon("share-2", class_name="h-3.5 w-3.5"), "Share my view", on_click=rx.call_script("window.chipLayoutShare && window.chipLayoutShare()"), class_name=BTN_OUTLINE),
                rx.cond(
                    shared.contains("who") & (shared["artifact"] == LayoutState.selected),
                    rx.el.button(
                        rx.icon("eye", class_name="h-3.5 w-3.5"), "Go to ", shared["who"], "'s view",
                        on_click=rx.call_script("window.chipLayoutGotoBox && window.chipLayoutGotoBox(" + shared["box"].to(str) + ")"),
                        id="layout-follow",
                        class_name=f"{BTN_OUTLINE} text-teal-300",
                    ),
                ),
                class_name="flex items-center gap-2 flex-wrap",
            ),
            class_name="flex items-center justify-between gap-3 flex-wrap",
        ),
        rx.el.div(
            rx.el.div(
                id="layout-viewer",
                custom_attrs={
                    "data-url": LayoutState.url,
                    "data-backend": backend_base(),
                    "data-bbox": LayoutState.bbox.to_string(),
                    "data-hidden": LayoutState.hidden_keys,
                    "data-notes": ProjectRoom.layout_notes.to_string(),
                    "data-artifact": LayoutState.selected,
                    "data-adding": rx.cond(LayoutState.adding_note, "1", "0"),
                    "data-markers": LayoutState.markers_json,
                },
                class_name="absolute inset-0",
            ),
            rx.el.div(
                rx.el.span(id="layout-coords", class_name="font-mono"),
                rx.el.span("Preview drawn by KLayout: not a DRC or LVS result.", class_name="text-slate-500"),
                class_name="absolute bottom-2 left-3 right-3 flex justify-between text-[11px] text-slate-300 pointer-events-none",
            ),
            class_name="relative flex-1 min-h-[420px] rounded-xl overflow-hidden border border-slate-800 bg-slate-950",
        ),
        XYButton.create(id="layout-note-at", on_click=LayoutState.add_note, class_name="hidden"),
        BoxButton.create(id="layout-share-at", on_click=LayoutState.share_view, class_name="hidden"),
        class_name="flex flex-col gap-3 flex-1 min-w-0 min-h-0",
    )


def layout_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            section_title("Layout", "The GDS files of Build ASIC runs (and any layout a run kept), drawn by KLayout at any zoom. Notes and shared views reach everyone in the project."),
            rx.el.button(rx.icon("refresh-cw", class_name="h-3.5 w-3.5"), "Refresh", on_click=LayoutState.load, class_name=BTN_OUTLINE),
            class_name="flex items-end justify-between gap-3",
        ),
        rx.cond(
            LayoutState.gds.length() > 0,
            rx.el.div(
                rx.el.div(
                    rx.el.span("Layouts", class_name=LABEL), gds_list(),
                    markers_list(),
                    rx.cond(LayoutState.layers.length() > 0, layer_list()),
                    notes_list(),
                    class_name=f"{PANEL} p-3 w-full md:w-72 max-h-64 md:max-h-none shrink-0 overflow-y-auto flex flex-col gap-4",
                ),
                rx.cond(LayoutState.error != "", empty("triangle-alert", "Can't draw this layout", LayoutState.error), viewer()),
                class_name="flex flex-col md:flex-row gap-4 md:flex-1 md:min-h-0",
            ),
            empty("layers", "No layout yet", rx.el.span("A layout appears here once a Build ASIC run has made a GDS (Implement → Build ASIC).")),
        ),
        on_mount=LayoutState.load,
        id="layout-view",
        class_name="flex flex-col gap-4 p-3 md:p-5 md:h-full md:overflow-hidden",
    )
