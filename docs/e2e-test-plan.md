# Chipova test plan

What is tested, where, and how to run it. The acceptance criteria are the blueprint's §12
(AC-01 … AC-12); "the plan" is §15's list (collaboration, AI patch approval, failing jobs,
permissions, artifact hashes) and §12's performance baselines.

## Running

```bash
poetry run pytest -m "not docker"                 # 33 unit / integration tests, no Docker (5 s)
poetry run pytest -m docker                       # 15 tests in real containers (needs both tool images, ~13 min)
poetry run ./run_test_suite.sh <suite>            # one E2E suite (Playwright, its own server and data folder)
scripts/ci.sh                                     # what CI runs: unit, the base image, Docker tests, 11 suites
```

`run_test_suite.sh` starts the app (`reflex_rerun.sh`) with a fresh `CHIPOVA_HOME` in the suite's
output folder, a test `DDNS_AUTH_SECRET` (so suites can sign people in and call the AI tools as
the AI Hub would), runs `testcases/<suite>/run_test.py`, and stops the server. With other apps on
3000/8000: `FRONTEND_PORT=3171 BACKEND_PORT=8171`. With a re-ddns dev install of this checkout
running, put `OUTPUT_DIR` outside the repository (its hot reload watches the checkout). Docker must
be running with the tool images installed (Tools & settings, or the Dockerfiles in
`infra/dockerfiles`). CI (`.github/workflows/ci.yml` → `scripts/ci.sh`) runs everything that doesn't
need the 17 GB IIC-OSIC image; the ASIC and analog Docker tests skip themselves without it, and
the `ams_corners` and `xschem_desktop` suites are run where the image is.

## Acceptance criteria

| AC | Given / when / then | Tests | Result (2026-10-26) |
|---|---|---|---|
| AC-01 | Two people edit the same RTL at once; content and carets agree; a dropped connection recovers | E2E `collab_live` (both type at once at both ends of a file: the same text with both edits; each sees the other's caret; the dirty dot; freezing clears it for both; leaving), `perf_baseline` (5 drops of 3 s while both type: all converge), unit `test_a_crash_loses_no_typing` | Verified for two editors. A third person *watching* is not a separate test (a viewer's read-only editor is tested in `permissions`). |
| AC-02 | An AI proposes a diff; the user rejects it: the source is unchanged, the reason recorded | E2E `ai_review`, unit `test_rejecting_keeps_the_source_and_the_reason`, `test_an_ai_token_proposes_but_never_decides` | Verified |
| AC-03 | An AI's patch is accepted: a traceable change and a new snapshot | E2E `ai_review` (the editor shows it, it is the latest snapshot, the AI reads the decision), unit `test_accepting_applies_it_and_freezes_a_snapshot`, `test_people_editing_meanwhile_are_merged_or_stop_it` | Verified |
| AC-04 | Lint/sim on a syntax error: FAILED, log kept, jump to the line | E2E `lint_sim` (the problem's line, the editor's marker, the click goes there), Docker `test_a_syntax_error_fails_the_lint_with_its_line` | Verified |
| AC-05 | Simulation writes a VCD: a real waveform in the browser, the artifact's hash checkable | E2E `lint_sim` (the viewer draws `tb_heartbeat` signals, a cursor), `fpga_build` (download == recorded SHA-256, server re-check), `perf_baseline` (every artifact of a sim run), unit `test_a_download_link_is_its_persons_unchanged_and_in_time` | Verified |
| AC-06 | The same snapshot built again: same or different tools/PDK/settings, compared | E2E `fpga_build` (built twice, Compare: 16 rows, none differ), `perf_baseline` (bitstream and every output identical); the manifest records image id, tool versions, settings, params | Verified for the FPGA flow. ASIC rebuilds are not compared (GDS files carry timestamps). |
| AC-07 | No DRC deck: BLOCKED, never PASS | unit `test_timing_parasitics_power_and_antenna_come_from_the_signoff_run_of_that_layout` (a layout of a PDK with no deck or corners: DRC, LVS, STA BLOCKED), `test_checks_come_only_from_runs_on_that_snapshot` (no layout: BLOCKED), `test_pvt_corners_come_from_a_cace_run_of_that_snapshot` (no datasheet: BLOCKED), E2E `signoff_release` (nothing PASS before runs) | Verified |
| AC-08 | Simulation and ASIC build artifacts tied to their flowgraph nodes | Docker `test_heartbeat_to_gds_then_drc_and_lvs` (≥ 20 SiliconCompiler nodes with their status, each node's log readable, GDS and netlist artifacts), `test_lint_sim_synth_on_the_heartbeat` | Verified (nodes link to their logs; artifacts are per run, named by the step's folder) |
| AC-09 | A viewer without access to a private project reads its artifact: API and WS refuse, audited | E2E `permissions` (page, REST with his own token, the co-editing socket with a genuine ticket: 4403, a download link signed for him: 403; four audited refusals; then as a viewer: reads, can't type, run or freeze), unit `test_a_private_project_is_refused_on_every_route`, `test_a_viewer_reads_but_cannot_freeze_or_run`, `test_access_link_and_members` | Verified |
| AC-10 | An AI tries a command that isn't allowed: refused, no container | E2E `ai_review` (`shell`, `top="x; id"`, `argv`, a path outside the project: refused and in the log), Docker `test_unknown_flows_and_parameters_are_refused_without_a_container`, unit `test_runs_are_only_allowed_flows_with_their_parameters`, `test_proposals_cannot_reach_outside_the_project`, `test_paths_cannot_leave_the_project` | Verified |
| AC-11 | A release candidate without LVS or approval: the gate holds and lists what is missing | E2E `signoff_release` (two people: the gate holds, the requester can't approve, a waiver needs the other person and reads WAIVED, then approval and the package), unit `test_a_release_is_gated_and_lists_what_is_missing`, `test_an_asic_release_without_lvs_is_blocked` | Verified |
| AC-12 | An analog container build fails: the log kept, marked unfinished, never "tape-out ready" | Docker `test_a_failing_analog_run_keeps_its_log_and_nothing_says_ready` (a deck ngspice can't run: FAILED, log kept, no required check passes, the release gate holds, foundry ready refused), `test_ihp_inverter_meets_its_specs_at_every_corner_then_fails_a_tighter_one` (CACE fails a spec: FAILED with the spec and which conditions broke it, AMS PVT corners FAIL) | Verified for the ngspice and CACE flows |

## The blueprint's minimum test list (§15.8)

| Area | Unit / integration | Docker | E2E |
|---|---|---|---|
| Collaboration | `test_a_crash_loses_no_typing` | | `collab_live`, `perf_baseline` |
| AI patch approval | `test_proposals.py` (5), `test_an_ai_token_proposes_but_never_decides` | `test_an_ai_asking_for_synthesis_waits_for_a_person` | `ai_review` |
| Failing jobs | | `test_a_syntax_error_fails_the_lint_with_its_line`, `test_a_failing_analog_run_…`, `test_ihp_inverter_…_then_fails_a_tighter_one` | `lint_sim` (a syntax error, a testbench FAIL) |
| Permissions | `test_access_link_and_members`, `test_api_links.py` (3) | | `permissions` |
| Artifact hashes | `test_a_download_link_is_its_persons_unchanged_and_in_time` | `test_lint_sim_synth_on_the_heartbeat` | `fpga_build`, `perf_baseline` |

Also: snapshots (`test_create_from_template_…`, `test_same_files_give_the_same_revision_…`), the
settings form's concurrency, signoff and waivers (`test_signoff_release.py`), RTL → GDSII → DRC →
LVS → timing, parasitics, antenna and power/IR on each PDK (`test_heartbeat_to_gds_then_drc_and_lvs`
for SKY130, `test_heartbeat_signs_off_on_ihp_sg13g2`, `test_heartbeat_signs_off_on_gf180`), a
backend restart during a build (`test_a_restarted_backend_follows_a_running_build_to_its_end`),
ECP5 and Gowin bitstreams (`test_ecp5_and_gowin_boards_…`), the package plan
(`test_the_package_plan_is_checked_against_the_design`), Xschem simulation on SKY130 and IHP and
CACE corners (`test_ams_docker.py`), the IHP chip built from scratch and its Full chip check
(`test_chip_docker.py`; about 5 minutes and 3 GB) and what its overlay takes (`test_chip_overlay.py`),
board jobs and lab records (`test_boards.py`, `test_lab.py`),
templates and deleting (`smoke_home`); the E2E suites `offline_lan` (no host but Chipova's
reachable), `board_helper`, `phone_view`, `lab_package`, `ams_corners` and `xschem_desktop`.

## Performance baselines (§12: measured, not promised)

Suite `perf_baseline` measures and writes `perf.json`; the 2026-10-26 run is kept in
[perf/baseline-2026-10-26.json](perf/baseline-2026-10-26.json).

**Machine**: MacBook Pro, Apple silicon (arm64), 14 CPUs, 24 GB, macOS 15.3.1; Docker Desktop
29.8.0 with 14 CPUs and 14.1 GB; the app on the same machine (`reflex run`, dev mode), Chromium
headless, both browser tabs on the same machine.

| What | Method | Result |
|---|---|---|
| Co-editing delay | 40 edits in A's editor (Monaco → Yjs → relay → Yjs → Monaco); B's editor stamps when each appears; both use the same clock | median 3 ms, p95 5 ms, max 7 ms |
| Reconnecting | B's connection dropped for 3 s while A and B both edit; then reconnected; time until both editors hold the same text with both edits | 5 of 5 converged; median 274 ms after reconnecting |
| Queue | 6 lint runs asked for at once with `CHIPOVA_MAX_PARALLEL_RUNS=2` | never more than 2 at once; wait from queued to started median 1.2 s, max 1.4 s; a lint run (container start to collected) median 0.22 s |
| Artifact integrity | every artifact of a simulation run downloaded through its signed link and hashed | 3 of 3 match the recorded SHA-256 |
| Reproducibility | the iCE40 build run twice on the same snapshot | bitstream and every output identical (0.5 s each) |
| Container interruption | the backend stopped 8 s into a Build ASIC run, then started again (`test_a_restarted_backend_…`) | the same container followed to SUCCEEDED, its GDS collected |
| Long runs (live app, 2026-10-26) | the heartbeat (6-bit) through the live app's Build ASIC, DRC and LVS | Build ASIC 30.6 s (SKY130, 76 cells), DRC 2.1 s, LVS 0.8 s |
| Large layouts | — | not measured: no large GDS fixture yet |

Not covered by these numbers: many people in one file, slow or lossy networks, a remote browser
(the delays above don't include a real network), a loaded Docker host.

## What is not tested

- A third person watching while two edit (AC-01's wording); more than two editors at once.
- Programming a real board (the board helper is tested with `--dry-run`, and openFPGALoader was run
  up to its own hardware access without a board), and a real bench with instruments (OpenHTF
  records were made with the bench script's `--simulate`).
- The AI Hub itself (suites call Chipova's tool endpoint with tokens signed as the hub signs them;
  the hub's own routing was checked by hand: it lists Chipova's 15 tools).
- Call everyone (the call app's side).
- Installing the tool images from the Tools page: no suite covers it (the suites use the images
  already installed).
- Rebuilding an ASIC layout twice and comparing it (GDS files carry timestamps; the numbers can be
  compared by hand).
