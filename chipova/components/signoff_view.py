"""The Signoff and Release sections."""

from __future__ import annotations

import reflex as rx

from chipova.components.common import BTN, BTN_OUTLINE, BTN_PRIMARY, INPUT, LABEL, PANEL, ago, empty, section_title, status_badge
from chipova.components.links import backend_url
from chipova.states.ide import IdeState
from chipova.states.room import ProjectRoom
from chipova.states.runs_state import RunState
from chipova.states.signoff_state import SignoffState


def snapshot_picker() -> rx.Component:
    return rx.el.select(
        rx.foreach(ProjectRoom.snapshots, lambda s: rx.el.option(s.short + " · " + s.message, value=s.id)),
        value=SignoffState.revision,
        on_change=SignoffState.pick_revision,
        id="signoff-snapshot",
        class_name=f"{INPUT} max-w-md",
    )


def check_row(c) -> rx.Component:
    return rx.el.tr(
        rx.el.td(status_badge(c.status), class_name="px-3 py-2 align-top"),
        rx.el.td(
            rx.el.div(
                rx.el.span(c.title, class_name="text-sm font-semibold text-slate-100"),
                rx.cond(c.required, rx.el.span("required for release", class_name="text-[10px] text-slate-500 uppercase tracking-wider")),
                class_name="flex flex-col",
            ),
            class_name="px-2 py-2 align-top",
        ),
        rx.el.td(
            rx.el.div(
                rx.cond(c.summary != "", rx.el.span(c.summary, class_name="text-xs text-slate-300")),
                rx.cond((c.why != "") & (c.status != "PASS"), rx.el.span(c.why, class_name="text-xs text-slate-500")),
                rx.cond(c.deck != "", rx.el.span("deck: ", rx.el.code(c.deck), class_name="text-[11px] text-slate-500")),
                rx.cond(c.waiver != "", rx.el.span("waiver: ", c.waiver, class_name="text-[11px] text-amber-300")),
                class_name="flex flex-col gap-0.5",
            ),
            class_name="px-2 py-2 align-top",
        ),
        rx.el.td(
            rx.el.div(
                rx.cond(c.run != "", rx.el.button(rx.el.code(c.run), on_click=[RunState.select(c.run), IdeState.set_view(rx.cond(c.category == "sim", "verify", "implement"))], class_name="text-[11px] text-teal-300 hover:underline")),
                rx.cond(
                    (c.status != "PASS") & (c.status != "WAIVED"),
                    rx.el.button("Ask for a waiver", on_click=SignoffState.ask_waiver(c.category), custom_attrs={"data-waive": c.category}, class_name="text-[11px] text-slate-400 hover:text-amber-300"),
                ),
                class_name="flex flex-col items-start gap-1",
            ),
            class_name="px-2 py-2 align-top",
        ),
        custom_attrs={"data-check": c.category, "data-check-status": c.status},
        class_name="border-b border-slate-800/60",
    )


def waiver_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.el.span("Waive ", SignoffState.waiver_category, " on ", rx.el.code(SignoffState.revision_short))),
            rx.dialog.description("A waiver never turns a check into PASS: it shows as WAIVED, with your reason, the rule it covers and who approved it. Someone else with the reviewer role must approve it.", size="2"),
            rx.el.input(value=SignoffState.waiver_rule, on_change=SignoffState.set_waiver_rule, placeholder="Rule id (e.g. met1.2), or empty for the whole check", id="waiver-rule", class_name=f"{INPUT} w-full mt-3 font-mono"),
            rx.el.textarea(value=SignoffState.waiver_reason, on_change=SignoffState.set_waiver_reason, rows="3", placeholder="Why it is safe to waive (checked how, by whom)", id="waiver-reason", class_name="w-full mt-2 p-3 rounded-md bg-slate-950 border border-slate-700 text-sm text-slate-100 outline-none focus:border-teal-500"),
            rx.el.div(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=SignoffState.cancel_waiver),
                rx.button("Ask for the waiver", color_scheme="amber", on_click=SignoffState.request_waiver, id="confirm-waiver"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="520px",
        ),
        open=SignoffState.waiver_category != "",
    )


def signoff_view() -> rx.Component:
    waivers = rx.cond(
        SignoffState.waivers.length() > 0,
        rx.el.div(
            rx.el.span("Waivers of this snapshot", class_name=LABEL),
            rx.foreach(
                SignoffState.waivers,
                lambda w: rx.el.div(
                    status_badge(w.status, small=True),
                    rx.el.code(w.category + " · " + w.rule, class_name="text-xs text-slate-300"),
                    rx.el.span(w.reason, class_name="text-xs text-slate-400 flex-1"),
                    rx.el.span("by ", w.by, rx.cond(w.approved_by != "", rx.el.span(" · decided by ", w.approved_by)), class_name="text-[11px] text-slate-500"),
                    rx.cond(
                        (w.status == "PROPOSED") & IdeState.can_review & ~w.mine,
                        rx.el.div(
                            rx.el.button("Approve", on_click=SignoffState.decide_waiver(w.id, True), custom_attrs={"data-approve-waiver": w.id}, class_name=f"{BTN} h-6 bg-amber-700 hover:bg-amber-600 text-white"),
                            rx.el.button("Reject", on_click=SignoffState.decide_waiver(w.id, False), class_name=f"{BTN} h-6 bg-slate-800 text-slate-200"),
                            class_name="flex gap-1",
                        ),
                    ),
                    class_name="flex items-center gap-3 py-1.5 border-b border-slate-800/60",
                ),
            ),
            class_name=f"{PANEL} p-4 flex flex-col gap-1",
        ),
    )
    return rx.el.div(
        rx.el.div(
            section_title("Signoff", "Each check of a snapshot, from that snapshot's own runs. A check that didn't run is not passed; one that can't run here says why."),
            rx.el.div(
                snapshot_picker(),
                rx.el.button(rx.icon("play", class_name="h-3.5 w-3.5"), "Run checks", on_click=SignoffState.run_checks, disabled=~IdeState.can_run, id="run-checks", class_name=BTN_PRIMARY),
                rx.el.button(rx.icon("refresh-cw", class_name="h-3.5 w-3.5"), on_click=SignoffState.load(SignoffState.revision), title="Refresh", class_name=BTN_OUTLINE),
                class_name="flex items-center gap-2",
            ),
            class_name="flex flex-wrap items-end justify-between gap-3",
        ),
        rx.el.div(
            rx.el.table(
                rx.el.thead(rx.el.tr(*[rx.el.th(h, class_name="px-2 py-2 text-left font-semibold") for h in ["Status", "Check", "Evidence", ""]], class_name="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800")),
                rx.el.tbody(rx.foreach(SignoffState.checks, check_row)),
                id="signoff-checks",
                class_name="w-full",
            ),
            class_name=f"{PANEL} p-2",
        ),
        waivers,
        rx.el.p(
            "Results on an open PDK are for learning, prototypes and test chips; SkyWater calls SKY130 an experimental preview. A foundry's acceptance needs its own rules and people with its authority.",
            class_name="text-xs text-slate-500 max-w-3xl",
        ),
        waiver_dialog(),
        on_mount=SignoffState.load(""),
        id="signoff-view",
        class_name="flex flex-col gap-4 h-full p-5 overflow-y-auto",
    )


# ------------------------------------------------------------ releases


def release_card(r) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(status_badge(r.status), rx.el.span(r.title, class_name="text-sm font-semibold text-slate-100"), class_name="flex items-center gap-2"),
            rx.el.span("snapshot ", rx.el.code(r.snapshot, class_name="text-teal-300"), " · by ", r.by, " · ", ago(r.at), class_name="text-xs text-slate-400"),
            class_name="flex flex-col gap-1",
        ),
        rx.cond(
            r.gate_ok,
            rx.el.p(rx.icon("circle-check", class_name="h-3.5 w-3.5 inline mr-1"), "Gate passed", class_name="text-xs text-emerald-300"),
            rx.el.div(
                rx.el.span("Missing before it can be approved:", class_name="text-xs text-rose-300"),
                rx.foreach(r.missing, lambda m: rx.el.span("• ", m, class_name="text-xs text-slate-400")),
                class_name="flex flex-col gap-0.5",
                custom_attrs={"data-gate": "blocked"},
            ),
        ),
        rx.cond(r.approvals != "", rx.el.p(r.approvals, class_name="text-xs text-slate-400")),
        rx.el.div(
            rx.cond((r.status == "DRAFT") & IdeState.can_run, rx.el.button("Ask for review", on_click=SignoffState.request_review(r.id), custom_attrs={"data-review": r.id}, class_name=BTN_OUTLINE)),
            rx.cond(
                (r.status == "IN_REVIEW") & IdeState.can_review & ~r.mine,
                rx.fragment(
                    rx.el.button("Approve", on_click=SignoffState.ask_decision(r.id, "approve"), custom_attrs={"data-approve-release": r.id}, class_name=BTN_PRIMARY),
                    rx.el.button("Reject", on_click=SignoffState.ask_decision(r.id, "reject"), class_name=BTN_OUTLINE),
                ),
            ),
            rx.cond((r.status == "APPROVED") & IdeState.can_manage, rx.el.button("Mark foundry ready…", on_click=SignoffState.ask_decision(r.id, "foundry_ready"), class_name=BTN_OUTLINE)),
            rx.cond(((r.status == "REJECTED") | (r.status == "IN_REVIEW") | (r.status == "APPROVED")) & IdeState.can_run, rx.el.button("Back to draft", on_click=SignoffState.reopen(r.id), class_name=BTN_OUTLINE)),
            rx.el.button(rx.icon("package", class_name="h-3.5 w-3.5"), "Build package", on_click=SignoffState.build_package(r.id), custom_attrs={"data-package": r.id}, class_name=BTN_OUTLINE),
            rx.cond(r.href != "", rx.el.a(rx.icon("download", class_name="h-3.5 w-3.5"), "Download", href=backend_url(r.href), custom_attrs={"data-download-package": r.id, "download": ""}, class_name=BTN_OUTLINE)),
            rx.cond(r.package != "", rx.el.code("sha256 ", r.package, "…", class_name="text-[11px] text-slate-500")),
            class_name="flex items-center gap-2 flex-wrap",
        ),
        custom_attrs={"data-release": r.id, "data-release-status": r.status},
        class_name=f"{PANEL} p-4 flex flex-col gap-3",
    )


def decision_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.match(SignoffState.decision_kind, ("approve", "Approve the release"), ("reject", "Reject the release"), "Mark it foundry ready")),
            rx.dialog.description(
                rx.match(
                    SignoffState.decision_kind,
                    ("approve", "You confirm that you reviewed the snapshot and its checks. The gate must pass: every required check PASS or WAIVED."),
                    ("reject", "Say why: it stays with the release."),
                    "Your own statement that the foundry's own requirements were checked, by whom and how. Chipova can't check that for you.",
                ),
                size="2",
            ),
            rx.el.textarea(value=SignoffState.decision_text, on_change=SignoffState.set_decision_text, rows="3", id="decision-text", class_name="w-full mt-3 p-3 rounded-md bg-slate-950 border border-slate-700 text-sm text-slate-100 outline-none focus:border-teal-500"),
            rx.el.div(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=SignoffState.cancel_decision),
                rx.button("Confirm", color_scheme="teal", on_click=SignoffState.decide, id="confirm-decision"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="520px",
        ),
        open=SignoffState.decision_id != "",
    )


def new_release_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.el.span("New release of ", rx.el.code(SignoffState.revision_short))),
            rx.dialog.description("A tape-out preparation package of this snapshot: its sources, runs, reports, checklist and approvals. Not a foundry submission.", size="2"),
            rx.el.input(value=SignoffState.new_release_title, on_change=SignoffState.set_new_release_title, placeholder="Title (e.g. MPW shuttle candidate 1)", id="release-title", class_name=f"{INPUT} w-full mt-3"),
            rx.el.div(
                rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.button("Create", color_scheme="teal", on_click=SignoffState.create_release, id="create-release"),
                class_name="flex justify-end gap-2 mt-4",
            ),
            max_width="520px",
        ),
        open=SignoffState.new_release_open,
        on_open_change=SignoffState.set_new_release_open,
    )


def release_view() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            section_title("Release", "Tape-out preparation: a snapshot, its evidence and its approvals in one package. It can't be approved while a required check isn't PASS or WAIVED, nor by whoever asked for it."),
            rx.el.div(
                snapshot_picker(),
                rx.el.button(rx.icon("plus", class_name="h-3.5 w-3.5"), "New release", on_click=SignoffState.open_new_release, disabled=~IdeState.can_run, id="new-release", class_name=BTN_PRIMARY),
                class_name="flex items-center gap-2",
            ),
            class_name="flex flex-wrap items-end justify-between gap-3",
        ),
        rx.cond(
            SignoffState.releases.length() > 0,
            rx.el.div(rx.foreach(SignoffState.releases, release_card), id="releases", class_name="flex flex-col gap-3"),
            empty("package", "No releases yet", "Pick a snapshot and start one; the gate shows what it still needs."),
        ),
        new_release_dialog(),
        decision_dialog(),
        on_mount=SignoffState.load(""),
        id="release-view",
        class_name="flex flex-col gap-4 h-full p-5 overflow-y-auto",
    )
