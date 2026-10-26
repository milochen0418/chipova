# Chipova architecture

How Chipova is put together, for people and agents changing it. The product view is in
[product-spec.md](product-spec.md) (the blueprint), the screens in [ui-flows.md](ui-flows.md),
and why it is built this way in [adr/0001-core-decisions.md](adr/0001-core-decisions.md).

## 1. The parts

The blueprint (§3.1) separates the UI, co-editing, agents, storage and EDA jobs. In Chipova they are
modules of **one Reflex backend process**, plus **one Docker container per EDA run**:

```
                        re-ddns Agentic App Store (sign-in cookie, AI Hub, call apps)
                                              │
  ┌───────────────────────────────── Chipova backend (Reflex 0.10 + Starlette) ─────────────────────┐
  │  pages + states (chipova/states, chipova/components)        product shell, rooms, roles          │
  │  ProjectRoom (Reflex SharedState)                           presence, runs, proposals, activity  │
  │  co-editing relay  /_chipova/yjs/<project>-<file>          services/collab.py (pycrdt)           │
  │  REST API  /api/…  (+ SSE)                                  services/api.py                       │
  │  artifacts, waveforms, layouts  /_chipova/a|wave|layout/…   services/artifacts.py                │
  │  AI tools  /_ddns_tool/manifest|call                        agents/ai_tools.py (reflex_ddns_auth) │
  │  domain: models, state machines, roles                      domain/                               │
  │  services: projects, revisions, proposals, reviews,         services/                             │
  │            signoff, releases, audit                                                               │
  │  job engine: queue, scheduler, collect, manifest            jobs/engine.py                        │
  │  flows (FlowProvider), PDKs (PDKProvider), tool profiles    jobs/flows*.py, pdks.py, profiles.py  │
  │  KLayout worker process (layout tiles)                      jobs/layout.py, layout_worker.py      │
  └───────────────┬─────────────────────────────────────────────────────────────┬────────────────────┘
                  │ CHIPOVA_HOME                                                  │ Docker socket
                  ▼                                                               ▼
   chipova.db (SQLite, WAL)          projects/<id>/repo.git (snapshots)     one container per run
   projects/<id>/work, docs (live)   projects/<id>/runs/<run>/ (outputs)    chipova/eda-base:1
   secret (signing key)                                                      chipova/eda-osic:2026.10-1
```

| Blueprint part (§3) | In Chipova |
|---|---|
| Reflex IC Design IDE, Project / AI / Review UI | `chipova/components`, `chipova/states`, pages `/`, `/p/[project_id]`, `/settings` |
| API / Auth / ACL | `domain/roles.py`, `services/projects.py` (`access`, `require`), `services/api.py`, platform sign-in cookie, guests |
| Collaboration Service (Yjs; Hocuspocus or similar) | `services/collab.py`: a y-websocket–compatible relay in the backend, `assets/chipova/collab.js` in the browser |
| Versioned storage (Git + DB + object store) | bare git per project, SQLite, run folders on disk (no object store) |
| EDA Job Orchestrator (queue, containers) | `jobs/engine.py` (SQLite queue + asyncio scheduler) and `jobs/docker_runner.py` |
| Digital pipeline (SiliconCompiler, Yosys, OpenROAD, KLayout, Netgen) | `jobs/flows.py` (lint, sim, synth, FPGA), `jobs/flows_asic.py` (SiliconCompiler ASIC, DRC, LVS) |
| AMS pipeline (IIC-OSIC-TOOLS, Xschem, ngspice, CACE) | ngspice only (`ams_ngspice`); the IIC-OSIC-TOOLS image is installed, Xschem/CACE are not wired |
| Artifacts + evidence | `runs/<run>/out`, `artifacts` table (SHA-256), `manifest.json` |
| Signoff Center / Release Gate | `services/signoff.py`, `services/releases.py` |

## 2. Who is calling

Every door works out an `Actor` (`services/actors.py`) first:

| Door | Identity |
|---|---|
| Pages (Reflex events) | the platform's `ddns_auth` cookie (a JWT checked with `DDNS_AUTH_SECRET`), else a **guest**: a random key the browser keeps (`rx.LocalStorage`), shown only as `guest-<sha256(key)[:16]>` and "Guest NNNN" |
| REST API | `Authorization: Bearer chv1.…` (an HMAC token made on the Agents page, 30 days, a person's or an agent's), or the sign-in cookie |
| AI tools | the AI Hub's call token (a JWT for the app `chipova`, checked by `reflex_ddns_auth.tools`); the caller is `agent:<name>` |
| Co-editing socket | a ticket (HMAC with this installation's `secret`) made for the person when the page opens a file |
| Downloads, waveforms, layouts | a link signed for the person (`u`, `x` expiry, `s` HMAC), checked again against their access at every fetch |

## 3. Who may do what

`domain/roles.py` has the table: **viewer** (view, comment, download), **reviewer** (+ review,
approve waivers and releases), **editor** (+ edit, snapshot, run, decide on proposals, approve runs,
ask for a release), **owner** (everything + manage). A person's roles are their membership's and
what the project's link gives everyone (`editor`, `viewer` or nothing); they may do whatever any of
them may. An agent has the roles of the person it works for (or its own membership), minus
`NEVER_FOR_AGENTS`: edit, decide on proposals, approve runs, review, approve waivers, approve
releases, manage.

The check is made at each door, not only in the page:

- pages: `IdeState.on_load_project` (no access: the "gone" page with **Ask for access**);
- every service call: `projects.require(project, actor, action)` raises `Denied` and audits it;
- the co-editing socket: checked when it connects, again when someone's role or the link changes
  (`collab.refresh_access`); viewers' sockets drop their updates; refusals close with 4401/4403/4404;
- signed links: the signature, the expiry and the person's access now;
- the engine: a flow AIs may not run alone is created as **waiting for approval**.

Approvals are never by whoever asked: a waiver's approver, a release's approver are someone else
(`signoff.decide_waiver`, `releases.approve`).

## 4. Files, live and frozen

Blueprint §6.2's three kinds of version:

- **Working copy**: each text file is a Yjs document `<project>-<file id>`. The relay keeps it in
  memory (`pycrdt`), appends every update to `docs/<file>.ylog` as it comes, writes the full state
  to `.ystate` and the text to `work/<path>` 1.5 s after the last change (compacting the log), so a
  crash loses no typing. The server can edit it too (an accepted proposal, a restored snapshot): the
  edit reaches every editor as anyone's typing would.
- **Snapshot / revision**: `revisions.freeze` writes the working copy as a commit of the project's
  bare git repository through a temporary index (no checkout). Its id is
  `sha256:<sha256 of the sorted [path, sha256(file)] list>`, so the same files always give the same
  snapshot (freezing twice makes nothing new). `git archive` of the commit is a run's only input.
- **Release**: a snapshot + its checklist + approvals + the hashes of its evidence (section 7).

`chipova.toml` (the project's settings) is a file like the others; the Settings form writes it with
optimistic concurrency (the hash it was read at), so two people saving at once don't overwrite each
other. Binary files are never co-edited: GDS, VCD, bitstreams are run outputs, immutable.

## 5. Runs

### States

```
submit ─► CREATED ──(no approval needed, or a person approved)──► QUEUED ─► RUNNING ─► SUCCEEDED
              │                                                     │          ├────► FAILED
              └──(an AI asked; a person rejected)──► CANCELED  ◄────┘          ├────► CANCELED
                                                                               └────► TIMED_OUT
approval:  NONE   or   PROPOSED ─► APPROVED | REJECTED | EXPIRED      (domain/machines.py)
```

The approval is its own state machine: a run that succeeded says nothing about whether anyone
approved anything. `machines.check_run` refuses CREATED → QUEUED unless the approval is NONE or
APPROVED.

### From a request to a container

1. `engine.submit` checks the person may run, the flow exists and is enabled, the snapshot exists,
   and the parameters against the flow's definition (`flows.check_params`: unknown parameters are
   refused; modules must be identifiers of the snapshot's sources, files must be in the snapshot,
   choices and numbers in range). There is no way to pass a command. Refusals are audited and make
   no container.
2. The flow's builder turns the snapshot and parameters into a `JobSpec`: a list of steps, each an
   **argv list** (no shell strings), its working folder, environment and time limit, plus scripts
   the flow ships (`jobs/container/`), inputs from another run (a DRC run gets the GDS of its
   Build ASIC run in `/work/in`) and limits.
3. The scheduler starts up to `CHIPOVA_MAX_PARALLEL_RUNS` queued runs in order. Each gets a
   container of the flow's first installed profile image, created with `network_mode=none`, user
   `1000:1000`, `cap_drop=ALL`, `no-new-privileges`, CPU (`nano_cpus`), memory, process limits and a
   label naming the run. The workspace is copied in (`put_archive`): `/work/src` (the snapshot,
   owned by root, read-only), `/work/job.json`, `/work/runner.py`, `/work/job/*`, `/work/in/*`;
   `/work/out`, `/work/home`, `/work/tmp` are writable.
4. `runner.py` (standard library only) runs the steps and prints markers the engine follows live:
   `@@chipova step-start <id> <time>`, `step-end <id> <exit code> <seconds>`, `step-skip <id>`, and
   for SiliconCompiler's flowgraph `node-start/node-end <step>/<index>` (from `sc_flow.py` watching
   SC's node folders). A failed step skips the rest unless it may fail.
5. At the end (or at the time limit: stop, TIMED_OUT) the engine copies `/work/out` back
   (`get_archive`, extracted refusing links and paths outside, capped by `CHIPOVA_MAX_OUTPUT_MB`),
   keeps each output matching the flow's artifact patterns with its SHA-256 and size, parses
   problems (`jobs/parsers.py`: tool, severity, file, line, column) and metrics, decides the
   verdict from the required steps, writes `manifest.json`, and removes the container.
6. A backend that stops leaves containers running; at the next start the engine finds each
   RUNNING run's container by name and follows it again (a container that is gone fails its run),
   and removes version-probe containers a stop left half-made (older than 10 minutes: another
   Chipova on the same Docker may be probing).

### The manifest (`runs/<run>/manifest.json`, schema `chipova.run-manifest/1`)

The run (flow and version, status, who asked and how, approval, times, exit code), the project, the
snapshot (id, git commit, source hash, every file's SHA-256), the settings, the parameters, the
profile (image tag, image id, the base it was built on with its digest, every tool's version as
the image reported it), the limits, the isolation, each step (argv, its SHA-256, status, exit code,
times, metrics) and each artifact (name, kind, size, SHA-256). `engine.compare(a, b)` lines two
manifests up for the **Compare** view.

### Flows (the FlowProvider)

`flows.FLOWS` maps an id to a `Flow`: a versioned `FlowDefinition` (title, category, the profiles
that can run it, parameters with kinds and defaults from `chipova.toml`, time limit) and a builder.

| Flow | Image | Steps |
|---|---|---|
| `rtl_lint` | eda-base or osic | `verilator --lint-only -Wall`, `iverilog` elaboration |
| `rtl_sim` | eda-base or osic | `iverilog` + `vvp` (or Verilator `--binary`), VCD kept; the testbench's `PASS`/`FAIL` lines decide |
| `synth_yosys` | eda-base or osic | Yosys script (stat, netlist), RTL schematic (Yosys `show` → Graphviz SVG) |
| `fpga_ice40` | eda-base or osic | `synth_ice40` → `nextpnr-ice40` (pin file, target clock) → `icepack` |
| `ams_ngspice` | eda-base or osic | `ngspice -b`: `.meas` results, `wrdata` tables as charts |
| `asic_sc` | osic | `sc_flow.py`: SiliconCompiler `Design` + `ASIC` + the PDK's target, 23 flowgraph nodes, then the full GDS (`gds_merge_cells.py`) and its picture |
| `signoff_drc` | osic | KLayout `sky130A_mr.drc` (results counted from the `.lyrdb`) and Magic DRC |
| `signoff_lvs` | osic | Magic extraction → Netgen against the gate-level netlist (`add_bulk_pins.py`) |

### Tool profiles

`jobs/profiles.py` lists the images: each is built from `infra/dockerfiles/<name>/Dockerfile` on a
base pinned by digest (Debian `trixie-slim@sha256:62bd…`; `hpretl/iic-osic-tools:2026.10@sha256:3065…`),
through the platform's package cache when there is one. Installing records the image id and probes
each tool's version (the first line it prints) into the `profiles` table; every run's manifest
repeats them. The IIC-OSIC image also bakes in the PDK data SiliconCompiler fetches (lambdapdk), so
Build ASIC runs offline.

### PDKs (the PDKProvider)

`jobs/pdks.py`: `skywater130` (flow, DRC and LVS decks, layer colours; marked experimental
preview), `ihp130` (flow, layer colours; no DRC/LVS here), `gf180` (listed, not set up). Nothing
outside this registry names a PDK.

## 6. Live updates

- **Pages** of a project are linked to one `ProjectRoom` (a Reflex `SharedState`). Services call
  listeners when something changes (`engine.listeners`, `proposals.listeners`, `collab.on_saved`,
  `collab.on_presence`); `states/room.py` `push_later(project, "runs", …)` recomputes those parts of
  the room once, and Reflex sends the delta to every linked tab. Each tab's own view (which run,
  which file) is its own state.
- **API clients** follow a run with `GET /api/runs/{id}/events` (server-sent events: the run and its
  steps whenever they change, then `end`).
- **Co-editing** is Yjs' own protocol on its socket (sync, updates, awareness for carets).

## 7. Signoff and release

`signoff.checklist(project, revision)` is computed, not stored: each check's resolver looks at the
runs **of that snapshot** (its own or, for layout checks, those checking a Build ASIC run of it) and
the waivers of that snapshot, and returns one of NOT_CONFIGURED, NOT_RUN, RUNNING, PASS, FAIL,
WAIVED, BLOCKED with its evidence (run id, deck, numbers) or why. Which checks are required depends
on the project's kind. Resolvers are registered per check (the VerificationProvider): lint and
simulation in `signoff.py`, FPGA timing from `fpga_ice40`, DRC, LVS, STA, PEX, power, antenna in
`flows_asic.register()`; AMS corners is BLOCKED (no CACE flow), full chip NOT_CONFIGURED.

A waiver (`waivers` table) has the check, the rule, the reason, the snapshot, who asked and who
decided; an approved waiver makes the check WAIVED, never PASS. A release (`releases` table) goes
DRAFT → IN_REVIEW → APPROVED | REJECTED (back to DRAFT to change it); `releases.gate` lists what is
missing (required checks not PASS/WAIVED, the approval); approving needs the gate passed and
someone other than the requester; FOUNDRY_READY needs an APPROVED release, the owner and their
written statement. The package is a zip: `RELEASE_MANIFEST.json` (the snapshot, its checklist,
every included file's SHA-256, the approvals, a "not a foundry signoff" note), `source/`, the
evidence runs' outputs and `approval.json`.

## 8. AI agents

`agents/ai_tools.py` registers 15 tools with `reflex_ddns_auth.tools.tool` (the AgentToolProvider);
the AI Hub lists them for agents and calls `/_ddns_tool/call/<name>` with its token. `room` is the
project id. Reading tools (guide, list_projects, get_project, read_file, history, diff,
list_flows, proposal_status, get_run, read_log, waveform) go through the same access checks as
people; writing tools only **propose** (`propose_patch`: whole new files; `proposals.py` keeps the
base text, shows the diff, merges with what people typed meanwhile with `git merge-file` when
accepted, and refuses conflicts), **freeze**, **run** (an allowed flow, its parameters checked; it
waits for approval unless the project lets AIs run that flow alone: `rtl_lint`, `rtl_sim` by
default) and **cancel**. Every call is audited (reading tools by the wrapper, writing ones by the
service they call), with the agent's name; the Agents page shows the project's.

## 9. Pictures

- **Waveforms**: `jobs/vcd.py` parses a VCD once (cached), and `/_chipova/wave/{artifact}` returns
  the signal list or a window of chosen signals, thinned to about the screen's width
  (`assets/chipova/wave.js` draws it on a canvas).
- **Layouts**: `jobs/layout.py` keeps a KLayout worker process (`layout_worker.py`, framed JSON over
  pipes) that loads a GDS with its PDK's layer properties and draws PNG tiles; `/_chipova/layout/{artifact}`
  answers `info` (cells, size, layers) and tiles; `assets/chipova/layout.js` shows them with markers
  (DRC results from the `.lyrdb`), notes, a ruler and shared views. The page says it is a picture,
  not a DRC or LVS result.

## 10. On disk (`CHIPOVA_HOME`)

```
chipova.db                         projects, members, files, revisions, runs, run_steps, artifacts,
                                   agent_actions, reviews, comments, waivers, releases, audit,
                                   access_requests, profiles
secret                             this installation's signing key (tickets, links, API tokens)
projects/<project>/
  repo.git/                        snapshots (bare git)
  work/<path>                      the working copy as text
  docs/<file>.ystate|.ylog         the co-edited documents
  runs/<run>/manifest.json         what went in and came out
  runs/<run>/out/…                 the outputs: steps/<id>/stdout.log, sim/wave.vcd, asic/final/…
  releases/<release>.zip           release packages
cache/                             layout tiles
```

Deleting a project removes its folder; its rows stay marked deleted and the audit log keeps its
history.
