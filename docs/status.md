# Status: the blueprint, item by item

As of **2026-10-26**. The blueprint ([product-spec.md](product-spec.md))
asks for each item to be marked **Implemented / Verified / Blocked / Experimental**; here:

| Mark | Means |
|---|---|
| ✅ **Verified** | built, and an automated test or a recorded live check shows it working (named) |
| 🟡 **Partial** | built in part; what is missing is said |
| 🧪 **Experimental** | works, with caveats a user must know |
| ⛔ **Blocked** | can't be done here as asked; why |
| ⬜ **Not started** | |

Tests are named as `unit:`, `docker:` (pytest in real containers) and `e2e:` (Playwright suites);
"live" means checked on `https://chipova.reflex-ddns.com` on 2026-10-26.

## The ten rules (§0)

| # | Rule | Status | Evidence / gap |
|---|---|---|---|
| 1 | Reflex is the product shell | ✅ | The whole app; installed from the App Store catalog as `chipova`, live |
| 2 | Character sync with CRDT (Monaco + Yjs + y-monaco + an authorised socket); SharedState only for rooms | ✅ | e2e:`collab_live`, e2e:`permissions` (socket refused with 4403), e2e:`perf_baseline`. The relay is Chipova's own (pycrdt), not Hocuspocus ([ADR 2](adr/0001-core-decisions.md)) |
| 3 | SiliconCompiler's current `Design` / `ASIC` API, never `Chip()` | ✅ | docker:`test_heartbeat_to_gds_then_drc_and_lvs` (SC 0.38.10, `jobs/container/asic/sc_flow.py`) |
| 4 | EDA jobs in isolated containers, never in the web process | ✅ | Every run: no network, user 1000, capabilities dropped, limits (manifest `isolation`); docker:`test_unknown_flows_…`, unit:`test_runs_are_only_allowed_flows_…` |
| 5 | Runs use immutable snapshots: revision id, source SHA, tool and PDK versions, image digest, parameters, seed | ✅ | All in each run's `manifest.json`: the PDK data's versions (open_pdks `1689ac3f2dc7`, IHP `a49358cc0b20`, SiliconCompiler's lambdapdk 0.2.22 and IHP data) are read from the image with its tools'. Seeds: nextpnr's `--seed 1` is in the recorded command; OpenROAD runs with SiliconCompiler's defaults |
| 6 | People's and AIs' actions traceable; AI proposes a diff, people review, approve, revert | ✅ | e2e:`ai_review`, unit:`test_proposals.py`; the audit log (every tool call, e2e:`ai_review`); reverting = **Put these files back** on a snapshot (checked by hand, no suite) |
| 7 | The UI shows real job states, no fake success | ✅ | States from the engine's state machine; e2e:`lint_sim` (FAILED shown with why), unit:`test_checks_come_only_from_runs_on_that_snapshot` |
| 8 | Signoff ≠ manufacturable; each check on its own with its deck | ✅ | The Signoff page; unit:`test_timing_parasitics_power_and_antenna_…` (no deck or corners → BLOCKED; each check from its own part of the run) |
| 9 | Don't assume PDK or licence | ✅ | The PDK registry says what each PDK has; SKY130 marked experimental preview; [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md) |
| 10 | Every UI action has a story, states, data, API and tests | 🟡 | The main journeys have suites (14); not every action does: comments, file rename/delete, restoring a snapshot, layout notes and shared views, Call everyone are checked by hand only |

## Success definitions (§1.3)

| Goal | Status | Evidence |
|---|---|---|
| **MVP**: two people and an AI in one Verilog project; carets; the AI proposes without overwriting; a fixed snapshot passes lint and sim in containers; downloadable log, VCD, source SHA; a rerun traceable to the same inputs | ✅ | e2e:`collab_live`, `ai_review`, `lint_sim`, `fpga_build` (rerun compared); live walkthrough (README pictures) |
| **Digital Alpha**: RTL → GDSII on an open PDK with flowgraph, metrics, layout and separate DRC/LVS reports; an exportable reproducible manifest | ✅ | docker:`test_heartbeat_to_gds_then_drc_and_lvs`; live: Build ASIC 30.6 s, DRC clean, LVS match, STA met (SKY130) |

## Acceptance criteria (§12)

Details and test names: [e2e-test-plan.md](e2e-test-plan.md).

| AC | Status | Note |
|---|---|---|
| AC-01 co-editing, carets, reconnecting | ✅ | Two editors; a third watcher isn't a separate test |
| AC-02 rejected AI diff | ✅ | |
| AC-03 accepted AI patch → snapshot | ✅ | |
| AC-04 syntax error → FAILED, log, jump | ✅ | |
| AC-05 VCD shown, hash checkable | ✅ | |
| AC-06 rerun compared | ✅ | FPGA: identical; Compare also lines up the runs' numbers (PPA) |
| AC-07 no deck → BLOCKED | ✅ | |
| AC-08 artifacts tied to flowgraph nodes | ✅ | |
| AC-09 private artifact refused on API and socket, audited | ✅ | |
| AC-10 an AI's command refused, no container | ✅ | |
| AC-11 release without LVS or approval held | ✅ | |
| AC-12 failing analog build: log kept, not "ready" | ✅ | ngspice and CACE runs (docker) |

## Phases (§11)

| Phase | Item | Status | Note |
|---|---|---|---|
| 0 | Reflex scaffold, one-command start | ✅ | `reflex_rerun.sh`, App Store install |
| 0 | App Store / SSO adapter | ✅ | catalog entry `chipova` (re_ddns), the platform's sign-in cookie, guests |
| 0 | Data model | ✅ | `domain/models.py` (Pydantic), `db.py` |
| 0 | Container image management | ✅ | Tools & settings: install, rebuild, versions (two profiles, pinned bases) |
| 0 | Git / object storage | 🟡 | Git per project; outputs on disk, no object store ([ADR 7](adr/0001-core-decisions.md)) |
| 0 | CI | ✅ | `.github/workflows/ci.yml` runs `scripts/ci.sh`: unit tests, the base image, Docker tests, 11 E2E suites (green locally; not seen on GitHub yet: the workflow isn't pushed) |
| 0 | Reference RTL template, ADR | ✅ | 8 templates; [ADR 0001](adr/0001-core-decisions.md) |
| 1 | Monaco + Yjs, carets, permissions, files, snapshots | ✅ | |
| 1 | Agent patch + review | ✅ | |
| 1 | SiliconCompiler lint/sim adapter | 🟡 | Lint and simulation call Verilator and Icarus directly, not through SiliconCompiler ([ADR 6](adr/0001-core-decisions.md)) |
| 1 | Log / VCD, run dashboard | ✅ | |
| 1 | Exit: no lost characters, AI change approved into a snapshot, real artifacts downloadable, errors jump to lines | ✅ | |
| 2 | SiliconCompiler ASIC target in a container | ✅ | SKY130, IHP SG13G2 and GF180MCU (docker tests) |
| 2 | OpenROAD / KLayout metrics, flowgraph | ✅ | 23 nodes with metrics and logs |
| 2 | Layout preview | ✅ | KLayout tiles at any zoom, layers, DRC markers |
| 2 | FPGA nextpnr adapter | ✅ | iCE40, ECP5, Gowin GW1N (docker:`test_ecp5_and_gowin_boards_…`, e2e:`fpga_build`) |
| 2 | Comparing runs' PPA | ✅ | Compare: inputs, tool versions, numbers, outputs' hashes (unit:`test_compare_lines_up_two_builds_numbers`) |
| 2 | Exit: public examples reproduce RTL → GDSII and RTL → bitstream; hashes and versions kept | ✅ | |
| 3 | KLayout, Magic, Netgen checks | ✅ | SKY130, IHP SG13G2, GF180 with each PDK's open decks (docker: one test per PDK) |
| 3 | STA | ✅ | OpenSTA at every corner with each RC corner's extracted parasitics (3 corners; IHP one RC corner) |
| 3 | PEX | ✅ | OpenRCX with the PDK's rules, one SPEF per RC corner, every routed net checked to be in it |
| 3 | Waivers, review approval, release manifest, artifact integrity | ✅ | |
| 3 | Exit: FAIL / BLOCKED / NOT RUN never shown as PASS; the gate blocks | ✅ | |
| 4 | IIC-OSIC-TOOLS container | ✅ | Installed and used for ASIC, the layout checks, Xschem, CACE and the desktops |
| 4 | Xschem, CACE | ✅ | Xschem in the browser (a desktop through noVNC, e2e:`xschem_desktop`), Xschem simulation and CACE corners (docker:`test_ams_docker.py`, e2e:`ams_corners`) |
| 4 | IHP AMS template adapter, macro integration, padframe | 🟡 | the template baked into the image, the project's sources put over it, built from scratch (macros, padframe, seal ring); top-level LVS and fill not available (Signoff: Full chip) |
| 4 | Bond plan | ✅ | the package plan and its bond diagram (e2e:`lab_package`) |
| 5 | OpenHTF, measurement import | ✅ | OpenHTF JSON records against the spec (unit:`test_lab.py`, e2e:`lab_package`) |
| 5 | FPGA flashing worker | 🧪 | the board helper (e2e:`board_helper` with `--dry-run`; openFPGALoader run up to its hardware access, no real board here) |
| 5 | Instruments, plugin marketplace | ⬜ | Chipova reads the bench's records; it doesn't drive instruments |
| 5 | Relack / LiveKit intent | 🟡 | **Call everyone** rings the project through the platform's call app (DDNS Intent `call.join`); not tested here |

## First issues (§16)

| Issue | Status | Note |
|---|---|---|
| IC-001 Reflex skeleton (routes, CI) | ✅ | routes, CI (`scripts/ci.sh`) |
| IC-002 RBAC / SSO adapter | ✅ | roles, link access, members, requests; sign-in cookie |
| IC-003 Project + git snapshot | ✅ | |
| IC-004 Monaco Yjs collaboration | ✅ | |
| IC-005 Artifact store (SHA-256, ACL, signed downloads) | ✅ | |
| IC-006 EDA job engine (queue, container, state, events) | ✅ | events: the room for pages, SSE for the API |
| IC-007 Lint + simulation (pinned runner, log, VCD) | ✅ | |
| IC-008 AI patch review | ✅ | |
| IC-009 Verification UI (problems, tests, waveform) | ✅ | |
| IC-010 SiliconCompiler ASIC: Heartbeat to GDSII | ✅ | |
| IC-011 Flowgraph + metrics | ✅ | |
| IC-012 Layout preview | ✅ | |
| IC-013 Signoff dashboard | ✅ | |
| IC-014 Release gate | ✅ | |
| IC-015 AMS template adapter | 🟡 | the corner templates (Xschem + CACE) ✅; the IHP AMS chip template: built and checked, its top-level LVS and fill not available |

## Screens (§4.3)

| Screen | Status | Gap |
|---|---|---|
| UI-01 App Store start, sign-in, Request Access | ✅ | |
| UI-02 Projects, New Project, empty → Heartbeat | ✅ | |
| UI-03 Collaborative IDE, Reconnecting state | ✅ | |
| UI-04 Verification, Run Simulation | 🟡 | no testbench: the run says to set one; no guided "add a testbench" |
| UI-05 Implementation flowgraph | 🟡 | a failed run is rerun whole (**Run again**), not from its failed node |
| UI-06 Layout | 🟡 | no cell hierarchy browser (the top cell and its cell count) |
| UI-07 Signoff, Run Checks, BLOCKED without a deck | ✅ | |
| UI-08 Agent Center | 🟡 | proposals, tool calls, AI run rules ✅; asking for a proposal is in the AI Hub's assistant (the **AI** button), not on this page |
| UI-09 Release, Request Review | ✅ | |
| UI-10 Tools & settings | 🟡 | the two built-in profiles only (no registering other images); no licence hints per tool |
| Phones (§4.4) | ✅ | one column with tabs: proposals, runs, comments, files (read, comment), people (e2e:`phone_view`); typing needs a wider screen |

## Signoff checks (§10.1)

| Check | Status | Note |
|---|---|---|
| DRC | ✅ | SKY130 KLayout `sky130A_mr` + Magic; IHP KLayout main rules + Magic; GF180 open_pdks deck (variant C); density shown, not counted |
| LVS | ✅ | SKY130 and GF180 Magic + Netgen; IHP's KLayout deck |
| STA | ✅ | OpenSTA, every corner, extracted parasitics |
| PEX | ✅ | OpenRCX per RC corner |
| Power / IR | ✅ | report_power + PDNSim static IR (vectorless; 5 % of VDD) at every corner |
| Antenna | ✅ (DFM ⬜) | OpenROAD `check_antennas` with the PDK's LEF rules; other DFM rules not checked |
| AMS PVT corners | ✅ | CACE: every spec at every corner (pass and fail tested) |
| Package & pinout | ✅ | `package_check` |
| Full chip | 🟡 BLOCKED | the IHP chip template built and checked from scratch (padframe, seal ring, 7 macros, chip Magic DRC, gate-level LVS, cocotb; docker:`test_the_ihp_chip_is_built_and_checked_but_never_passes`); never PASS: top-level LVS isn't finished upstream, fill and the filled chip's DRC need more memory than a run gets |
| Waivers never PASS; FOUNDRY_READY only by a person | ✅ | unit:`test_waivers_need_a_reason_and_another_approver_and_never_pass`, `test_a_release_is_gated_…` |

## Security (§13)

| Item | Status | Note |
|---|---|---|
| Project isolation; RBAC on page, API, socket, downloads | ✅ | e2e:`permissions`, unit:`test_api_links.py`. No attribute-based rules (ABAC) |
| Agents: least privilege, approval, tool-call audit, no unauthorised projects | ✅ | agents never edit, decide or approve; every call audited |
| Prompt-injection defence | 🟡 | an injected instruction can't make an agent edit, approve or run commands here (the rules above), but tool results carry project text as it is |
| Containers: unprivileged user, limits, read-only sources, no network, no secrets inside | ✅ | the Docker daemon itself runs as root (the app has its socket: [ADR 4](adr/0001-core-decisions.md)) |
| Disk quota per run | 🟡 | the outputs copied back are capped (`CHIPOVA_MAX_OUTPUT_MB`); no quota inside the container |
| Licences: notices and versions | ✅ | [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md), [sbom/](sbom/) |
| Signed, per-person downloads; no guessable paths | ✅ | |
| Release safety (no AI signoff, people approve) | ✅ | |
| Per-run SBOM | 🟡 | each manifest: image id, tools' versions, commands, artifacts' hashes; no SPDX/CycloneDX per run |

## Deliverables (§14, §15)

| Item | Status |
|---|---|
| README (with limits), AGENTS.md, LICENSE (MIT), THIRD_PARTY_NOTICES, SBOM of the app | ✅ |
| docs: product-spec, architecture, ADR 0001, ui-flows, e2e-test-plan, this status | ✅ |
| Templates `digital_heartbeat`, `fpga_blinky`, `fpga_ulx3s`, `fpga_tangnano9k`, `ams_inverter`, `ams_corners_sky130`, `ams_corners_ihp`, `ams_chip_ihp` (+ `blank_digital`) | ✅ |
| `infra/dockerfiles` (eda-base, eda-osic); PDK registry (`chipova/jobs/pdks.py`); compose | ✅ / ✅ / — (the App Store's catalog entry instead) |
| Tests: unit / integration, docker, e2e, security (permissions, API) | ✅ 33 + 15 tests, 14 suites |
| Repository layout | one Python package `chipova/` (`states`, `components`, `services`, `jobs`, `agents`, `domain`) instead of the suggested `app/` + `services/` split: Reflex wants the app in one package |

## Upstream versions used

| Upstream | Version | Where |
|---|---|---|
| Reflex | 0.10.0 | app |
| SiliconCompiler | 0.38.10 (`Design` / `ASIC` API), lambdapdk 0.2.22 | `chipova/eda-osic:2026.10-3` |
| IIC-OSIC-TOOLS | 2026.10 (`hpretl/iic-osic-tools@sha256:306585de…`) | base of `eda-osic` |
| OpenROAD | 26Q4-407-geb14e40b7 | eda-osic |
| Yosys | 0.70 (eda-osic), 0.52 (eda-base) | |
| KLayout | 0.30.12 (eda-osic and the app's layout worker) | |
| Magic / Netgen | 8.3.685 / 1.5.324 | eda-osic |
| Verilator | 5.052 (eda-osic), 5.032 (eda-base) | |
| Icarus Verilog | 14.0 devel (eda-osic), 12.0 (eda-base) | |
| nextpnr (iCE40, ECP5, Gowin) / IceStorm / Trellis / apicula | 0.7 (Debian 0.7-1+b3) / Debian's / 1.4 / 0.17 | eda-base |
| ngspice | 47 (eda-osic), 44.2 (eda-base) | |
| Debian | 13.7 (`trixie-slim@sha256:62bd423a…`) | base of `eda-base` |
| Monaco / Yjs / y-websocket / y-monaco | 0.55.1 / 13.6.18 / 2.0.4 / 0.1.6 (vendored), served by Chipova | browser |
| CACE / Xschem / noVNC | 2.11.0 / 3.4.8RC / the image's | eda-osic |
| JKU's IHP SG13G2 AMS chip template | 2026.09 (`cf12265`), LibreLane 3.1.0.dev3 from the image | eda-osic `/opt/chipova/ams-template` |
| PDKs (DRC/LVS decks, layer colours) | open_pdks `1689ac3f2dc7` (sky130A, gf180mcuD), IHP SG13G2 `a49358cc0b20`, as shipped in IIC-OSIC-TOOLS 2026.10 | eda-osic `/foss/pdks` |
| PDKs (Build ASIC) | lambdapdk 0.2.22 (SKY130, GF180 9-track 5 V), SiliconCompiler's IHP 130 data `d490cfb2e3258f71` | eda-osic `/opt/sc-cache` |
