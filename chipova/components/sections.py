"""The sections beside Code: Verify, Implement, Agents and Settings."""

from __future__ import annotations

import reflex as rx

from chipova.components.code_view import wave_panel
from chipova.components.common import BTN_OUTLINE, BTN_PRIMARY, INPUT, LABEL, PANEL, ago, empty, section_title, status_badge
from chipova.components.links import backend_url
from chipova.components.run_details import flow_button, run_details, runs_list, two_columns
from chipova.jobs import flows
from chipova.states.agents_state import AgentsState
from chipova.states.comments_state import CommentsState
from chipova.states.ide import IdeState
from chipova.states.lab_state import LabState
from chipova.states.review_state import ReviewState
from chipova.states.room import ProjectRoom
from chipova.states.runs_state import RunState
from chipova.states.settings_state import SettingsState


def page(title: str, sub: str, actions: rx.Component, body: rx.Component, page_id: str) -> rx.Component:
    return rx.el.div(
        rx.el.div(section_title(title, sub), actions, class_name="flex flex-wrap items-end justify-between gap-3"),
        body,
        id=page_id,
        class_name="flex flex-col gap-4 p-3 md:p-5 md:h-full md:overflow-hidden",
    )


# ------------------------------------------------------------ Verify


def verify_view() -> rx.Component:
    problems = rx.cond(
        RunState.problems.length() > 0,
        rx.el.div(
            rx.el.span("Problems", class_name=LABEL),
            rx.el.div(
                rx.foreach(
                    RunState.problems,
                    lambda p: rx.el.button(
                        rx.el.span(p.severity, class_name=rx.cond(p.severity == "error", "text-rose-300 w-16 shrink-0", "text-amber-300 w-16 shrink-0")),
                        rx.el.span(p.message, class_name="text-slate-200 text-left"),
                        rx.el.span(p.where, class_name="ml-auto font-mono text-slate-500 whitespace-nowrap"),
                        on_click=IdeState.jump(p.file, p.line, p.column),
                        class_name="flex gap-2 w-full px-3 py-1 text-xs hover:bg-slate-800/60",
                    ),
                ),
                class_name=f"{PANEL} py-1 max-h-48 overflow-y-auto",
            ),
            class_name="flex flex-col gap-2",
        ),
    )
    wave = rx.cond(
        RunState.wave_url != "",
        rx.el.div(rx.el.span("Waveform", class_name=LABEL), rx.el.div(wave_panel(tall=True), class_name=f"{PANEL} h-[420px] overflow-hidden"), class_name="flex flex-col gap-2"),
    )
    return page(
        "Verify",
        "Lint and simulate snapshots; a testbench that prints FAIL or ERROR fails its run. Click a problem to jump to its line.",
        rx.el.div(flow_button("rtl_lint", "Lint", "scan-search"), flow_button("rtl_sim", "Simulate", "audio-waveform"), class_name="flex gap-2"),
        two_columns(
            rx.el.div(rx.el.span("Verification runs", class_name=f"{LABEL} px-2"), runs_list("verify"), class_name="flex flex-col gap-2"),
            run_details(rx.fragment(problems, wave)),
        ),
        "verify-view",
    )


# ------------------------------------------------------------ Implement


def chart(c) -> rx.Component:
    colors = ["#2dd4bf", "#f472b6", "#fbbf24"]
    return rx.el.div(
        rx.el.span(c.title, class_name="text-xs font-semibold text-slate-200"),
        rx.recharts.line_chart(
            *[
                # A table with fewer columns leaves the other lines empty: no legend entry for them.
                rx.recharts.line(data_key=f"y{i + 1}", name=c.names[i].to(str), legend_type=rx.cond(c.names.length() > i, "line", "none"),
                                 stroke=colors[i], dot=False, type_="monotone", is_animation_active=False)
                for i in range(3)
            ],
            rx.recharts.x_axis(data_key="x", tick={"fill": "#94a3b8", "fontSize": 10}, stroke="#334155"),
            rx.recharts.y_axis(tick={"fill": "#94a3b8", "fontSize": 10}, stroke="#334155", width=50),
            rx.recharts.cartesian_grid(stroke="#1e293b"),
            rx.recharts.graphing_tooltip(content_style={"backgroundColor": "#020617", "border": "1px solid #334155", "fontSize": 11}),
            rx.recharts.legend(wrapper_style={"fontSize": 11}),
            data=c.data,
            width="100%",
            height=260,
        ),
        rx.el.span("x: ", c.x_label, class_name="text-[10px] text-slate-500"),
        custom_attrs={"data-chart": c.title},
        class_name=f"{PANEL} p-3 flex flex-col gap-2",
    )


def implement_view() -> rx.Component:
    picture = rx.cond(
        RunState.picture != "",
        rx.el.div(
            rx.el.span(rx.match(RunState.flow, ("asic_sc", "Layout (KLayout)"), ("ams_xschem", "Schematic (Xschem)"), ("ams_cace", "Schematic (Xschem)"), "RTL schematic (Yosys)"), class_name=LABEL),
            rx.el.div(rx.image(src=backend_url(RunState.picture), alt="schematic", class_name="max-w-full bg-white rounded"), class_name=f"{PANEL} p-3 overflow-auto max-h-[480px]"),
            class_name="flex flex-col gap-2",
        ),
    )
    cells = rx.cond(
        RunState.cell_types.length() > 0,
        rx.el.div(
            rx.el.span("Cells by type", class_name=LABEL),
            rx.el.div(rx.foreach(RunState.cell_types, lambda c: rx.el.div(rx.el.code(c.label, class_name="text-slate-300"), rx.el.span(c.value, class_name="text-slate-100 font-semibold"), class_name="flex justify-between gap-3 px-3 py-1 text-xs border-b border-slate-800/60")), class_name=f"{PANEL} grid grid-cols-2 lg:grid-cols-3 max-h-56 overflow-y-auto"),
            class_name="flex flex-col gap-2",
        ),
    )
    # Build FPGA runs the flow of the family the project's settings name.
    fpga = rx.match(
        IdeState.fpga_family,
        ("ecp5", flow_button("fpga_ecp5", "Build FPGA", "grid-3x3")),
        ("gowin", flow_button("fpga_gowin", "Build FPGA", "grid-3x3")),
        flow_button("fpga_ice40", "Build FPGA", "grid-3x3"),
    )
    buttons = [flow_button("synth_yosys", "Synthesize", "binary"), fpga, flow_button("ams_ngspice", "SPICE", "activity"),
               flow_button("ams_xschem", "Xschem simulation", "zap"), flow_button("ams_cace", "Corners (CACE)", "thermometer")]
    if flows.get("asic_sc"):
        buttons.append(flow_button("asic_sc", "Build ASIC", "cpu"))
    return page(
        "Implement",
        "Synthesis, FPGA place and route, and RTL to GDSII. Every run is a sealed container on a frozen snapshot; its numbers come from the tools' own reports.",
        rx.el.div(*buttons, class_name="flex gap-2 flex-wrap"),
        two_columns(
            rx.el.div(rx.el.span("Implementation runs", class_name=f"{LABEL} px-2"), runs_list("implement"), rx.el.span("Analog runs", class_name=f"{LABEL} px-2 pt-3"), runs_list("ams"), class_name="flex flex-col gap-2"),
            run_details(rx.fragment(cells, picture, rx.cond(RunState.charts.length() > 0, rx.el.div(rx.el.span("Results", class_name=LABEL), rx.el.div(rx.foreach(RunState.charts, chart), class_name="grid lg:grid-cols-2 gap-3"), class_name="flex flex-col gap-2")))),
        ),
        "implement-view",
    )


# ------------------------------------------------------------ Lab


def lab_record(r) -> rx.Component:  # noqa: ANN001
    return rx.el.div(
        rx.el.div(
            status_badge(r.outcome, small=True),
            rx.el.code(r.dut, class_name="text-sm text-slate-100"),
            rx.cond(r.simulated, rx.el.span("simulated: measured nothing", class_name="text-[10px] px-1.5 rounded border border-amber-700/50 text-amber-300")),
            rx.el.span(r.test, " · ", r.station, " · snapshot ", rx.el.code(r.snapshot, class_name="text-teal-300"), " · ", r.by, " · ", ago(r.at), class_name="text-[11px] text-slate-500"),
            class_name="flex flex-wrap items-center gap-2",
        ),
        rx.el.div(
            rx.foreach(r.measures, lambda m: rx.el.span(
                rx.el.code(m.name, class_name="text-slate-400"), " = ", rx.el.span(m.value, " ", m.unit, class_name="text-slate-100"),
                rx.cond(m.limits != "", rx.el.span(" (", m.limits, ")", class_name="text-slate-500")),
                class_name=rx.cond(m.outcome == "PASS", "text-xs", "text-xs text-rose-300"),
            )),
            class_name="flex flex-wrap gap-x-4 gap-y-1",
        ),
        custom_attrs={"data-lab-record": r.dut, "data-lab-outcome": r.outcome},
        class_name=f"{PANEL} p-3 flex flex-col gap-2",
    )


def lab_view() -> rx.Component:
    bond = rx.cond(
        (RunState.flow == "package_check") & (RunState.picture != ""),
        rx.el.div(
            rx.el.span("Bond diagram (from the plan; not an assembly drawing)", class_name=LABEL),
            rx.el.div(rx.image(src=backend_url(RunState.picture), alt="bond diagram", class_name="w-full max-w-[560px] rounded", id="bond-diagram"), class_name=f"{PANEL} p-3 overflow-auto"),
            class_name="flex flex-col gap-2",
        ),
    )
    upload = rx.upload(
        rx.el.div(rx.icon("file-up", class_name="h-3.5 w-3.5"), "Add OpenHTF records (.json)", class_name="flex items-center gap-1.5 text-xs text-slate-200"),
        id="lab-upload",
        accept={"application/json": [".json"]},
        multiple=True,
        max_files=5,
        on_drop=LabState.handle_upload(rx.upload_files(upload_id="lab-upload")),
        # rx.upload's own box is a big dashed area (its defaults): this one is button-sized.
        border="1px dashed #475569",
        padding="0 0.75rem",
        class_name="cursor-pointer h-9 flex items-center rounded-md hover:bg-slate-800/60",
    )
    head = ["Measurement", "Spec", "Design, before silicon", "Real chips (in spec / measured)", "Low / mean / high", ""]
    compare = rx.cond(
        LabState.compare.length() > 0,
        rx.el.div(
            rx.el.table(
                rx.el.thead(rx.el.tr(*[rx.el.th(h, class_name="px-2 py-1.5 text-left font-semibold") for h in head], class_name="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800")),
                rx.el.tbody(rx.foreach(LabState.compare, lambda c: rx.el.tr(
                    rx.el.td(rx.el.code(c.name, class_name="text-slate-100"), rx.el.span(" ", c.unit, class_name="text-slate-500"), class_name="px-2 py-2"),
                    rx.el.td(c.spec, class_name="px-2 text-slate-300"),
                    rx.el.td(rx.el.span(c.pre, class_name="text-slate-100"), rx.cond(c.source != "", rx.el.div(c.source, class_name="text-[10px] text-slate-500")), class_name="px-2"),
                    rx.el.td(c.passed, " / ", c.chips, rx.cond(c.simulated > 0, rx.el.div("+", c.simulated, " simulated, left out", class_name="text-[10px] text-amber-300")), class_name="px-2 text-slate-300"),
                    rx.el.td(c.spread, class_name="px-2 text-slate-300 font-mono"),
                    rx.el.td(rx.match(
                        c.verdict,
                        ("in spec", rx.el.span("in spec", class_name="text-emerald-300")),
                        ("out of spec", rx.el.span("out of spec", class_name="text-rose-300")),
                        rx.el.span("not measured", class_name="text-slate-500"),
                    ), class_name="px-2"),
                    custom_attrs={"data-measure": c.name, "data-verdict": c.verdict},
                    class_name="border-b border-slate-800/60 text-xs",
                ))),
                id="lab-compare",
                class_name="w-full",
            ),
            class_name=f"{PANEL} overflow-x-auto",
        ),
        empty("gauge", "No spec yet", "lab/spec.csv says what to measure and what the design predicts."),
    )
    return rx.el.div(
        rx.el.div(
            section_title("Lab", "The package plan, and measurements of real chips beside what the design said before silicon, never mixed."),
            rx.el.div(
                flow_button("package_check", "Check the package plan", "package-check"),
                upload,
                rx.el.button(rx.icon("refresh-cw", class_name="h-3.5 w-3.5"), "Refresh", on_click=LabState.load, class_name=BTN_OUTLINE),
                class_name="flex flex-wrap gap-2",
            ),
            class_name="flex flex-wrap items-end justify-between gap-3",
        ),
        rx.el.div(
            two_columns(
                rx.el.div(rx.el.span("Package plan checks", class_name=f"{LABEL} px-2"), runs_list("lab"), class_name="flex flex-col gap-2"),
                run_details(bond),
            ),
            class_name="flex flex-col md:h-[600px] shrink-0",
        ),
        rx.el.div(
            rx.el.span("Real chips against the design", class_name=LABEL),
            compare,
            rx.el.p(
                "Records come from OpenHTF tests on a bench: drop their JSON here, or let the bench computer send them (lab/bench_test.py in the Heartbeat template, with an API token). A record marked simulated measured nothing and is left out of the comparison.",
                class_name="text-xs text-slate-500",
            ),
            rx.el.span("Test records", class_name=LABEL),
            rx.cond(
                LabState.results.length() > 0,
                rx.el.div(rx.foreach(LabState.results, lab_record), id="lab-records", class_name="flex flex-col gap-2"),
                empty("microscope", "No test records yet", "They come from tests of real chips."),
            ),
            class_name="flex flex-col gap-3",
        ),
        on_mount=LabState.load,
        id="lab-view",
        class_name="flex flex-col gap-4 p-3 md:p-5 h-full overflow-y-auto",
    )


# ------------------------------------------------------------ Agents


def agents_view() -> rx.Component:
    proposals = rx.fragment(
        rx.foreach(
            ProjectRoom.proposals,
            lambda p: rx.el.tr(
                rx.el.td(status_badge(p.status, small=True), class_name="px-2 py-1.5"),
                rx.el.td(p.title, class_name="px-2 text-slate-200"),
                rx.el.td(p.agent, class_name="px-2 text-violet-300"),
                rx.el.td(rx.el.code(p.files), class_name="px-2 text-slate-400"),
                rx.el.td(rx.cond(p.decided_by != "", p.decided_by, "—"), class_name="px-2 text-slate-400"),
                rx.el.td(ago(p.created), class_name="px-2 text-slate-500"),
                rx.el.td(rx.el.button("Review", on_click=ReviewState.open(p.id), class_name="text-xs text-teal-300 hover:underline"), class_name="px-2"),
                class_name="border-b border-slate-800/60 text-xs",
            ),
        ),
    )
    calls = rx.el.div(
        rx.foreach(
            AgentsState.calls,
            lambda c: rx.el.div(
                rx.el.span(ago(c.at), class_name="w-20 shrink-0 text-slate-500"),
                rx.el.span(c.agent, class_name="w-32 shrink-0 text-violet-300 truncate"),
                rx.el.code(c.action, class_name="w-44 shrink-0 text-slate-300 truncate"),
                rx.el.span(c.decision, class_name=rx.cond(c.decision == "ok", "w-16 shrink-0 text-emerald-400", "w-16 shrink-0 text-rose-400")),
                rx.el.span(c.detail, class_name="text-slate-400 truncate"),
                class_name="flex gap-2 px-3 py-1 text-xs border-b border-slate-800/50",
            ),
        ),
        id="agent-calls",
    )
    connect = rx.el.div(
        rx.el.span("Connect an agent", class_name=LABEL),
        rx.el.p(
            "Chipova offers its tools to the AI Hub (the platform's one door for AI). Agents such as Claude Code connect to the hub's MCP address with a token made on the hub's page, and then see Chipova's tools (chipova.read_file, chipova.propose_patch, chipova.run, …). The AI button opens the hub's assistant on this project.",
            class_name="text-sm text-slate-400",
        ),
        rx.el.code(AgentsState.hub_address, class_name="text-sm text-teal-300"),
        rx.el.p(
            "What an agent can never do here: edit files directly, accept its own proposals, approve runs, waive checks or release. Which flows it may run without a person approving first is set in Settings.",
            class_name="text-sm text-slate-400",
        ),
        rx.el.div(
            rx.el.button(rx.icon("key-round", class_name="h-3.5 w-3.5"), "Make an API token for scripts", on_click=AgentsState.make_token, id="make-token", class_name=BTN_OUTLINE),
            rx.el.span("REST API: /api/projects, /api/runs/{id}/events, … with Authorization: Bearer <token> (30 days, your own access and audit trail).", class_name="text-[11px] text-slate-500"),
            class_name="flex items-center gap-3 flex-wrap",
        ),
        rx.cond(AgentsState.token != "", rx.el.code(AgentsState.token, id="api-token", class_name="text-xs break-all text-amber-200 p-2 rounded bg-slate-950 border border-amber-800/50")),
        class_name=f"{PANEL} p-4 flex flex-col gap-2",
    )
    return page(
        "Agents",
        "Everything AI agents proposed and every tool call they made here, allowed or refused (from the audit log).",
        rx.el.button(rx.icon("refresh-cw", class_name="h-3.5 w-3.5"), "Refresh", on_click=AgentsState.load, class_name=BTN_OUTLINE),
        rx.el.div(
            connect,
            rx.el.div(rx.el.span("Proposals", class_name=LABEL), rx.el.table(rx.el.tbody(proposals), class_name="w-full"), class_name=f"{PANEL} p-3 flex flex-col gap-2"),
            rx.el.div(rx.el.span("Tool calls and decisions", class_name=LABEL), calls, class_name=f"{PANEL} p-3 flex flex-col gap-2"),
            class_name="flex flex-col gap-4 overflow-y-auto pb-6",
            on_mount=AgentsState.load,
        ),
        "agents-view",
    )


# ------------------------------------------------------------ Settings


def field(name: str, label: str, hint: str = "", mono: bool = True) -> rx.Component:
    return rx.el.label(
        rx.el.span(label, class_name="text-xs font-semibold text-slate-300"),
        rx.el.input(
            value=SettingsState.form[name],
            on_change=lambda v: SettingsState.set_field(name, v),
            disabled=~IdeState.can_edit,
            custom_attrs={"data-setting": name},
            class_name=f"{INPUT} w-full" + (" font-mono" if mono else ""),
        ),
        rx.el.span(hint, class_name="text-[11px] text-slate-500") if hint else rx.fragment(),
        class_name="flex flex-col gap-1",
    )


def settings_view() -> rx.Component:
    run_settings = rx.el.div(
        rx.el.span("Run settings (chipova.toml)", class_name=LABEL),
        rx.cond(SettingsState.error != "", rx.el.p(SettingsState.error, class_name="text-sm text-rose-300")),
        rx.cond(
            SettingsState.conflict != "",
            rx.el.div(
                rx.el.p(SettingsState.conflict, class_name="text-sm text-amber-300"),
                rx.el.button("Load theirs", on_click=SettingsState.load, class_name=BTN_OUTLINE),
                class_name="flex items-center gap-3 p-3 rounded-lg border border-amber-700/50 bg-amber-950/30",
                id="settings-conflict",
            ),
        ),
        rx.el.div(
            field("top", "Top module", "The design's top"),
            field("testbench", "Testbench top", "The module the simulation starts from"),
            field("rtl", "RTL files", "Comma separated; empty = every .v/.sv outside tb/"),
            field("sim", "Testbench files", "Comma separated"),
            field("sdc", "Timing constraints (.sdc)"),
            field("clock_port", "Clock port"),
            field("clock_period_ns", "Clock period (ns)"),
            field("pdk", "PDK", "skywater130, gf180, ihp130 (Build ASIC, Xschem, CACE)"),
            field("fpga_family", "FPGA family", "ice40, ecp5 or gowin (which Build FPGA)"),
            field("fpga_device", "FPGA device", "e.g. up5k (iCE40), 85k (ECP5), GW1NR-LV9QN88PC6/I5"),
            field("fpga_package", "FPGA package", "e.g. sg48 (iCE40), CABGA381 (ECP5)"),
            field("fpga_pins", "FPGA pin file", ".pcf (iCE40), .lpf (ECP5) or .cst (Gowin)"),
            field("spice", "SPICE deck"),
            field("schematic_tb", "Xschem testbench (.sch)", "What Xschem simulation netlists and simulates"),
            field("cace", "CACE datasheet (.yaml)", "The specs Corners (CACE) checks at every corner"),
            class_name="grid sm:grid-cols-2 gap-3",
        ),
        rx.el.div(rx.el.button("Save settings", on_click=SettingsState.save, disabled=~IdeState.can_edit, id="save-settings", class_name=BTN_PRIMARY), class_name="flex"),
        class_name=f"{PANEL} p-4 flex flex-col gap-3",
    )
    members = rx.el.div(
        rx.el.span("Who may do what", class_name=LABEL),
        rx.el.label(
            rx.el.span("Anyone with the link", class_name="text-sm text-slate-300"),
            rx.el.select(
                rx.el.option("can edit", value="editor"),
                rx.el.option("can view", value="viewer"),
                rx.el.option("has no access (members only)", value="none"),
                value=SettingsState.link_access,
                on_change=SettingsState.set_link_access,
                disabled=~IdeState.can_manage,
                id="link-access",
                class_name=f"{INPUT}",
            ),
            class_name="flex items-center gap-3",
        ),
        rx.el.div(
            rx.foreach(
                SettingsState.members,
                lambda m: rx.el.div(
                    rx.el.span(m.name, class_name="text-sm text-slate-200 flex-1 truncate"),
                    rx.cond(
                        m.owner,
                        rx.el.span("owner", class_name="text-xs text-teal-300"),
                        rx.el.select(
                            rx.el.option("editor", value="editor"),
                            rx.el.option("reviewer", value="reviewer"),
                            rx.el.option("viewer", value="viewer"),
                            rx.el.option("remove", value="remove"),
                            value=m.role,
                            on_change=lambda v: SettingsState.change_role(m.user, v),
                            disabled=~IdeState.can_manage,
                            class_name=f"{INPUT} h-8",
                        ),
                    ),
                    class_name="flex items-center gap-3 py-1 border-b border-slate-800/60",
                ),
            ),
            id="members",
        ),
        rx.el.div(
            rx.el.input(value=SettingsState.new_member, on_change=SettingsState.set_new_member, placeholder="e-mail (or agent:<name> for an AI)", id="new-member", disabled=~IdeState.can_manage, class_name=f"{INPUT} flex-1"),
            rx.el.select(
                rx.el.option("editor", value="editor"), rx.el.option("reviewer", value="reviewer"), rx.el.option("viewer", value="viewer"),
                value=SettingsState.new_role, on_change=SettingsState.set_new_role, disabled=~IdeState.can_manage, class_name=INPUT,
            ),
            rx.el.button("Add", on_click=SettingsState.add_member, disabled=~IdeState.can_manage, id="add-member", class_name=BTN_OUTLINE),
            class_name="flex gap-2",
        ),
        rx.el.p("Editors edit, freeze, run and decide on AI proposals; reviewers approve reviews, waivers and releases; the owner manages the project.", class_name="text-[11px] text-slate-500"),
        rx.cond(
            CommentsState.requests.length() > 0,
            rx.el.div(
                rx.el.span("Asked for access", class_name=LABEL),
                rx.foreach(
                    CommentsState.requests,
                    lambda q: rx.el.div(
                        rx.el.span(q.name, class_name="text-sm text-slate-200 flex-1"),
                        rx.el.span(ago(q.at), class_name="text-[11px] text-slate-500"),
                        rx.cond(
                            IdeState.can_manage,
                            rx.fragment(
                                rx.el.button("Viewer", on_click=CommentsState.grant(q.user, "viewer"), class_name=BTN_OUTLINE),
                                rx.el.button("Editor", on_click=CommentsState.grant(q.user, "editor"), custom_attrs={"data-grant": q.user}, class_name=BTN_OUTLINE),
                                rx.el.button("Dismiss", on_click=CommentsState.grant(q.user, "dismiss"), class_name="text-xs text-slate-500 hover:text-slate-200"),
                            ),
                        ),
                        class_name="flex items-center gap-2",
                    ),
                ),
                id="access-requests",
                class_name="flex flex-col gap-2 p-3 rounded-lg border border-amber-800/50 bg-amber-950/20",
            ),
        ),
        on_mount=CommentsState.load_requests,
        class_name=f"{PANEL} p-4 flex flex-col gap-3",
    )
    ai = rx.el.div(
        rx.el.span("What an AI may run without asking", class_name=LABEL),
        rx.el.p("Flows ticked here start at once when an AI asks; the others wait until an editor approves them in Runs.", class_name="text-[11px] text-slate-500"),
        rx.el.div(
            rx.foreach(
                SettingsState.ai_flows,
                lambda f: rx.el.label(
                    rx.el.input(type="checkbox", checked=f.allowed, on_change=SettingsState.toggle_ai_flow(f.id), disabled=~IdeState.can_manage, custom_attrs={"data-ai-flow": f.id}),
                    rx.el.span(f.title, class_name="text-sm text-slate-300"),
                    class_name="flex items-center gap-2",
                ),
            ),
            class_name="grid sm:grid-cols-2 gap-2",
        ),
        class_name=f"{PANEL} p-4 flex flex-col gap-3",
    )
    project = rx.el.div(
        rx.el.span("Project", class_name=LABEL),
        rx.el.div(
            rx.el.input(value=SettingsState.title, on_change=SettingsState.set_title, disabled=~IdeState.can_edit, id="project-name", class_name=f"{INPUT} flex-1"),
            rx.el.button("Rename", on_click=SettingsState.rename, disabled=~IdeState.can_edit, class_name=BTN_OUTLINE),
            class_name="flex gap-2",
        ),
        rx.cond(
            IdeState.can_manage,
            rx.el.button(rx.icon("trash-2", class_name="h-3.5 w-3.5"), "Delete the project", on_click=SettingsState.ask_delete, id="delete-project", class_name=f"{BTN_OUTLINE} text-rose-300 w-fit"),
        ),
        rx.alert_dialog.root(
            rx.alert_dialog.content(
                rx.alert_dialog.title("Delete this project?"),
                rx.alert_dialog.description("Its files, snapshots and runs go for everyone; the audit log keeps its history."),
                rx.el.div(
                    rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray", on_click=SettingsState.cancel_delete)),
                    rx.alert_dialog.action(rx.button("Delete", color_scheme="red", on_click=SettingsState.delete_project, id="confirm-delete-project")),
                    class_name="flex justify-end gap-2 mt-4",
                ),
            ),
            open=SettingsState.confirm_delete,
        ),
        class_name=f"{PANEL} p-4 flex flex-col gap-3",
    )
    return page(
        "Settings",
        "The project's run settings live in chipova.toml with its files, so every snapshot keeps the settings its runs used.",
        rx.fragment(),
        rx.el.div(run_settings, members, ai, project, on_mount=SettingsState.load, class_name="flex flex-col gap-4 overflow-y-auto pb-8 max-w-4xl"),
        "settings-view",
    )
