# Chipova UI flows

The pages, what each shows, its main action, its empty and failure states, and the element ids
the E2E suites use. Screens are numbered as in the blueprint (§4.3, UI-01 … UI-10); the
journeys are its §5.

## Page tree

```
/                         Projects (UI-01, UI-02)
  New project dialog        templates, name
  Delete dialog
/p/<project_id>           The project workspace: top bar + rail + one view
  Code       (UI-03)        explorer · editor tabs · bottom panel · right panel · status bar
    snapshot view             a snapshot's diff, runs, reviews, restore
    proposal view             an AI proposal's diff, accept / reject
  Verify     (UI-04)        lint and simulation runs, waveform, compare
  Implement  (UI-05)        synthesis, FPGA, SPICE, Build ASIC: flowgraph, numbers, artifacts
  Layout     (UI-06)        GDS viewer, layers, DRC markers, notes, shared views
  Signoff    (UI-07)        the checklist of a snapshot, waivers
  Release    (UI-09)        releases of a snapshot, the gate, decisions, packages
  Agents     (UI-08)        connecting an agent, proposals, tool calls and decisions, API token
  Settings                  name, chipova.toml form, link access, members, requests, AI rules, delete
  (gone)                    no access / deleted: Ask for access
/settings                 Tools & settings (UI-10): tool profiles, PDK registry, limits, AI Hub
```

## The top bar and the rail (every project view)

- **Left**: the project's name and your role (`#project-title`, `#my-role`), the latest snapshot
  (`#latest-snapshot`) with an orange dot when the editors differ from it (`#dirty-dot`).
- **Middle**: **Freeze** (`#freeze-button` → `#snapshot-message`, `#confirm-freeze`), **Run** menu
  (`#run-menu`, items `[data-flow=<flow id>]`; disabled for viewers), **AI** (`#ai-button`: opens the
  AI Hub's assistant on this project through the `ai.assist` intent; a badge counts proposals
  waiting, `#ai-pending`).
- **Right**: who is here (`#presence`, `#people-count`), **Call everyone** (`#call-everyone`), the
  link (`#share-link`), you (`#me-name`, Login).
- **Rail**: `[data-view=code|verify|implement|layout|signoff|release|agents|settings]`.

**Run with unfrozen edits**: the Run menu asks first: **Freeze and run** (`#freeze-and-run`) or
**Run <the latest snapshot>** (`#run-latest`). A run never uses the live editors. The new run's id is
shown in a toast and it becomes the selected run.

## UI-01 / UI-02: Projects (`/`)

| | |
|---|---|
| Main action | **New project** (`#new-project`) → name (`#new-title`), template (`[data-template=digital_heartbeat\|fpga_blinky\|ams_inverter\|blank_digital]`), **Create** (`#create-project`) → the new project's Code view |
| Shows | the projects you can open (`#project-list`, rows `[data-project=<id>]`): kind, last change, owner, latest snapshot, the latest run's status and summary; search (`#search`); four lines on what Chipova is |
| Empty | "No projects yet." with **Start with the Heartbeat** (`#empty-new`) |
| Failure | a project you lost access to isn't listed; opening its link shows the gone page |
| Also | **Tools & settings** (`#admin-link`); a row's ⋯ menu deletes it (owner; `#confirm-delete`) |

Signing in is the platform's (re-ddns): **Login** in the corner. Without it you are a guest
("Guest 1234"), kept by your browser.

## UI-03: Code (the collaborative IDE)

```
+----------------------------------------------------------------------------------------+
| Chipova  Heartbeat OWNER  [main 73c2765 •]   [Freeze] [Run v] [AI 1]   G3 A· 2 here ☎ ⧉ |
+---+-------------+------------------------------------------+---------------------------+
| C | FILES       | heartbeat.v ×  tb_heartbeat.v ×          | AI review | Comments |    |
| V | constraints |                                          | People | Activity          |
| I | rtl         |   Monaco + carets of the others          |  proposals: Review /      |
| L | tb          |   problems as markers, comment marks     |  Accept / Reject          |
| S | README.md   |                                          |                           |
| R | chipova.toml+------------------------------------------+                           |
| A | RESULTS     | Problems | Output | Waveform | Runs      |                           |
| S | SNAPSHOTS   |                                          |                           |
+---+-------------+------------------------------------------+---------------------------+
| ● Live: edits reach everyone   snapshot 73c2765 by …   · 2 problems · 1 comment   path  |
+----------------------------------------------------------------------------------------+
```

- **Explorer** (`#explorer`): files `[data-file=<path>]` (a dot when someone has it open), new file
  (`#new-file` → `#new-file-path`, `#create-file`), rename (`#rename-path`), delete
  (`#confirm-delete-file`); **Results**: the latest runs of the latest snapshot; **Snapshots**:
  `[data-snapshot]`, a click opens the snapshot view.
- **Editor** (`#editor-panel`, its `data-chip-*` attributes say which document, ticket, read-only,
  and when it is bound): one Yjs document per file; read-only until bound, and always for viewers.
- **Bottom panel** (`#bottom-panel`, tabs `[data-bottom=problems|output|wave|runs]`):
  **Problems** (`#problems`, `[data-problem=<file>:<line>]`, a click goes to the line);
  **Output** (`#run-output`, the selected run's log by step, live); **Waveform** (`#wave-viewer`);
  **Runs** (`#runs`, `[data-run]` with `data-run-status`; **Approve** / **Reject** on runs an AI
  asked for, `[data-approve-run=<id>]`; cancel; rerun).
- **Right panel** (`#right-pane`, tabs `[data-right=ai|comments|people|activity]`):
  **AI review** (`#proposals`: `[data-proposal=<id>]` with `data-proposal-status`, **Review**
  `[data-open-proposal]`, **Accept**, **Reject** `[data-reject]` → `#reject-reason`,
  `#confirm-reject`); **Comments** (`#comments`; on the caret's line: `#comment-text`,
  `#comment-line`; resolve); **People** (who is here; an AI is marked AI); **Activity** (`#activity`).
- **Status bar**: the connection (`#chip-sync`), the snapshot
  (`#status-snapshot`), problems (`#chip-problems`, `data-run`, `data-problems`), comments
  (`#chip-comments`).

| State | What it shows |
|---|---|
| Live | `#chip-sync` "Live: edits reach everyone" |
| Connecting / offline | "Connecting…" / "Offline: your edits are kept and sent when back"; it catches up when the connection is back |
| Refused | "No access to this file" (the socket was closed with 4401/4403/4404): reload |
| Viewer | the editor doesn't take typing; Run and Freeze are disabled |
| Editors differ from the snapshot | the orange dot, "editors changed since" in the status bar |

**Proposal view** (`#proposal-view`): the title, the AI's name, its status, the snapshot it was
made on, **why** and **how to check it**, then each file's diff (`[data-diff-file=<path>]`, a
warning when the file changed since). **Accept for everyone** (`#accept-proposal`) applies it as
everyone's edit and freezes a snapshot; **Reject** (`#reject-proposal`) asks for the reason the AI
will read. Closing (`#close-proposal`) goes back to the files.

**Snapshot view** (`#snapshot-view`): its message, who, when; the diff from its parent or another
snapshot (`#snapshot-base`, `#snapshot-diff`); its runs; its reviews (`#review-comment`,
`#review-approve`, `#review-changes`, comment); **Put these files back** (`#restore-snapshot`,
`#confirm-restore`).

## UI-04: Verify

Main actions **Lint** and **Simulate** (`[data-start=rtl_lint]`, `[data-start=rtl_sim]`); the list of
verification runs; the selected run: status, snapshot, who, time, image, parameters, **Manifest**
(`#manifest-link`), **Run again**, its flow (steps with times), numbers (`#run-facts`), artifacts
(`#artifacts`, download and verify the SHA-256), **Compare with** another run (`#compare-run`,
`#compare-button` → `#run-compare`: what is the same and what differs).

| Empty / failure | |
|---|---|
| No runs | the bottom panel's Problems say "No run yet: Run Lint or Simulate from the Run menu." |
| No testbench in `chipova.toml` | Simulate refuses: "set the testbench's top module in Settings (chipova.toml [sim] testbench)"; the Signoff check is BLOCKED |
| Lint or simulation fails | FAILED with the error, problems and the failing step's log; the testbench's FAIL line is quoted |

## UI-05: Implement

**Synthesize**, **Build FPGA**, **SPICE**, **Build ASIC** (`[data-start=synth_yosys|fpga_ice40|ams_ngspice|asic_sc]`).
The selected run shows its **flowgraph** (`#flowgraph`, nodes `[data-node]` with
`data-node-status`; Build ASIC's 23 SiliconCompiler steps fill in live, each with its time, its
numbers and a link to its log), its numbers (cells, area, slack, Fmax, power estimate, DRVs; the
FPGA's resource use and Fmax per clock; SPICE's measurements) and charts (`[data-chart]`, from
`wrdata` tables), its artifacts (GDS, netlists, DEF, bitstream, reports, the RTL schematic).

| Empty / failure | |
|---|---|
| Image not installed | the run is refused: "needs a tool profile that isn't installed (…): install one on the Settings page" |
| Queued | "place in queue: N" |
| A node fails | the node is red, its log one click away, the run FAILED with the tool's error lines |

## UI-06: Layout

The layouts of the project's Build ASIC runs (the full GDS). **Open**: the viewer (`#layout-viewer`,
`data-drawn` when drawn) with the cell's size and cell count, **Fit**, **Measure** (`#layout-ruler`),
a note at a point (`#layout-note-text`, **Pin it**), **Share my view** (everyone in the project can
**Follow**, `#layout-follow`), the cursor's coordinates (`#layout-coords`), layers on and off; **DRC
markers** of the latest DRC run of that layout (`[data-marker]`, a click zooms there).

| Empty | |
|---|---|
| No GDS yet | "No layout yet": "A layout appears here once a Build ASIC run has made a GDS (Implement → Build ASIC)." |
| DRC ran clean | "The DRC of this layout found nothing." (the markers list shows only once a DRC run of that layout exists) |
| Always | "Preview drawn by KLayout: not a DRC or LVS result." |

## UI-07: Signoff

A snapshot (`#signoff-snapshot`, the latest by default), **Run checks** (`#run-checks`: starts the
checks that can run and haven't on it), and the checklist (`#signoff-checks`, rows
`[data-check=<category>]` with `data-check-status`): status, check, "required for release",
evidence (the deck, the numbers, the run), and **Ask for a waiver** (`[data-waive=<category>]` →
a rule id or the whole check `#waiver-rule`, the reason `#waiver-reason`, `#confirm-waiver`); a
reviewer or owner other than the asker approves or rejects it (`[data-approve-waiver]`).

| Status | Means |
|---|---|
| PASS | a run of this snapshot passed it (with its evidence) |
| FAIL | a run of this snapshot failed it (the count, the first errors) |
| RUNNING | its run is queued or running |
| NOT RUN | it can run here but hasn't on this snapshot |
| BLOCKED | it can't run here; says why (no deck for this PDK, no testbench, no CACE flow, no layout yet) |
| NOT CONFIGURED | no flow for it is set up in Chipova (PEX, power/IR, antenna, full chip) |
| WAIVED | a person approved a waiver; never counted as PASS |

The footer: results on an open PDK are for learning, prototypes and test chips.

## UI-09: Release

A snapshot and **New release** (`#new-release` → `#release-title`, `#create-release`). Each release
(`[data-release]` with `data-release-status`) shows its snapshot, who asked, and **what is missing
before it can be approved** (each required check not PASS/WAIVED; the approval). **Ask for review**
(`[data-review]`), **Approve** / **Reject** (`[data-approve-release]` → `#decision-text`,
`#confirm-decision`; not for whoever asked; Approve refuses while something is missing),
**Back to draft**, **Build package** (`[data-package]` → `[data-download-package]`), and for an
approved release the owner's **Mark foundry ready…** (their written statement of who checked the
foundry's own requirements, and how).

## UI-08: Agents

How to connect an agent (the AI Hub's MCP address; what an agent can never do here); the
project's **proposals** with their status, agent, files, decider; **Tool calls and decisions**
(`#agent-calls`: every call of an AI on this project and every decision on one, allowed or
refused, from the audit log); **Make an API token for scripts** (`#make-token` → `#api-token`, shown
once).

## Settings (in a project)

Name (`#project-name`), the `chipova.toml` form (`#save-settings`; someone else saved first:
`#settings-conflict`), **link access** (`#link-access`: anyone with the link can edit / view, or
members only), **members** (`#members`, `#new-member` + role, `#add-member`), **access requests**
(`#access-requests`: let in as Viewer or Editor, or Dismiss), **AI agents may run without
approval** (`[data-ai-flow=<flow id>]`), **Delete project** (`#delete-project`,
`#confirm-delete-project`). Only the owner changes these; others see them.

**Gone** (`#gone`): the project is private to you, or deleted. **Ask for access** (`#ask-access` →
`#access-asked`) tells the owner, who sees it under Settings.

## UI-10: Tools & settings (`/settings`)

The tool profiles (`#profiles`, `[data-profile=<id>]`): title, installed or not, what it runs, the
image and its pinned base, size, the tools' versions as recorded, the image id; **Install**
(`[data-install=<id>]`, with the build's progress line), **Read versions again**, **Rebuild**. The
**PDK registry** (`#pdks`): for each PDK whether Build ASIC, DRC and LVS are set up. Run limits; the
AI Hub's address. **Docker isn't reachable** when the app has no Docker socket.

## The journeys (blueprint §5)

**FLOW-DIGITAL (RTL → GDSII)**: New project → Heartbeat → (invite: link or members with roles) →
edit RTL / testbench / SDC together, comments → the AI proposes, a person accepts → Lint →
Simulate → Waveform → Freeze → Build ASIC (SKY130 or IHP SG13G2) → Layout → Signoff: Run checks
(DRC, LVS; STA from the build) → Release: new release, ask for review, another person approves →
Build package. Every result names its snapshot, image and tool versions (Manifest). FOUNDRY_READY
only by the owner's statement.

**FLOW-FPGA (RTL → bitstream)**: Blinky → Simulate → Build FPGA (device, package, pin file, target
clock in `chipova.toml`) → resource use and Fmax per clock → download the `.bin`. Programming a
board is not part of Chipova (no hardware worker).

**FLOW-AMS**: CMOS inverter → SPICE: measurements and charts. Not built: Xschem schematics in the
browser, CACE corners (the check is BLOCKED), the IHP AMS chip template, analog layout, padframe
and full-chip checks.

**FLOW-POSTSILICON**: not built (no package planning, no OpenHTF).

## Phones

Chipova is designed for wide screens: the workspace's three panes need a laptop or larger. The
projects page works on a phone; the workspace has no phone layout yet (the blueprint's §4.4: watch
runs, comment, approve on a phone, is not done).
