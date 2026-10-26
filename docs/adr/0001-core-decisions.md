# ADR 0001: Core decisions

- **Status**: accepted (2026-10-26)
- **Context**: the *Agentic IC Design Studio* blueprint ([product-spec.md](../product-spec.md)) asks
  for a Reflex app in the re-ddns Agentic App Store where people and authorised AI agents design
  chips together, with reproducible, containerised EDA runs on immutable snapshots and honest
  signoff. Its §3.2 recommends a stack for a multi-node service (PostgreSQL, MinIO, Redis/Celery,
  Hocuspocus). Chipova's first target is one App Store node: one container, one data volume, the
  host's Docker. These decisions follow from that, and say what changes if it stops being true.

## 1. Reflex is the whole product shell

**Decision**: pages, identity, rooms, permissions and every backend endpoint (REST, the co-editing
socket, downloads, the AI tools) live in the one Reflex app (`chipova/`), on its Starlette backend.
JavaScript is limited to what a browser must do: the editor binding, the waveform and layout
canvases, splitters (`assets/chipova/*.js`).

**Alternatives**: a separate FastAPI service for the API and a JS SPA for the IDE (the blueprint
forbids rewriting the product as a JS SPA); a Node service beside Reflex for co-editing.

**Consequences**: one process to install, configure and secure, one language for the rules
(permissions are checked by the same Python on every door). The backend is a single process: it
scales up, not out.

## 2. Co-editing: Yjs, with the relay inside the backend (pycrdt), not Hocuspocus

**Decision**: each text file is a Yjs document. The browser uses `yjs` and `y-websocket` with a
vendored `y-monaco` binding; the server side is Chipova's own relay (`services/collab.py`) speaking
the y-websocket protocol, holding each open document in `pycrdt`, persisting an append-only update
log and a compacted state, and writing the plain text to the working copy. The socket takes a
ticket signed for the person and checks their project access on connect and when it changes;
viewers' updates are dropped. Reflex `SharedState` carries only coarse room state (who is here,
runs, proposals, activity), never characters.

**Alternatives**: Hocuspocus (Node) as the blueprint suggests: more features (extensions, Redis
scaling), but a second runtime and process in the App Store container, its own auth hooks to keep
in step with Python's rules, and its own storage beside the project's. Reflex state for text:
rejected by the blueprint and unworkable for concurrent typing.

**Consequences**: the server can edit documents itself, as one more Yjs client: an accepted AI
proposal or a restored snapshot reaches everyone's editor as an edit, merged with their typing.
A crash loses no typing (the log). Rooms live in one process, so co-editing doesn't span several
backends. Yjs 13.6.18 and y-websocket 2.0.4 are bundled into the page and Monaco 0.55.1's files
are served by Chipova itself (`components/offline.py`), so editing needs no internet, only the
network to Chipova (e2e:`offline_lan` blocks every other host).

## 3. Snapshots are git commits named by their content

**Decision**: a bare git repository per project; `freeze` writes the working copy as a commit
through a temporary index; the revision id is the SHA-256 of the sorted (path, SHA-256) list, so
identical files give the identical id; runs get their input with `git archive` of that commit.

**Alternatives**: copying folders per snapshot (no diffs, no history tools); content-addressed
blobs in an object store (the blueprint's S3, overkill for one node).

**Consequences**: diffs, history and restoring come from git; a run's input can't be the live
editors by construction. Large binaries don't belong in snapshots (they are run outputs).

## 4. EDA runs are Docker containers started through the host's Docker socket

**Decision**: the engine (in the backend) keeps the queue in SQLite and starts one container per
run with docker-py: no network, user 1000:1000, all capabilities dropped, `no-new-privileges`,
CPU/memory/process limits, a time limit, the snapshot copied in read-only, outputs copied out and
hashed. Steps are argv lists from a flow's builder; parameters are checked against the flow's
definition; there is no way to pass a command or a shell string. A small runner inside the
container reports steps through log markers. The App Store gives the app the host's
`/var/run/docker.sock` (as PACS Lab has it).

**Alternatives**: Redis Queue or Celery workers (the blueprint's suggestion: a broker and worker
processes to run and secure for one node's queue); running tools in the web process (forbidden:
rule 4); Kubernetes jobs (not on an App Store node).

**Consequences**: every run is isolated and reproducible from its manifest; a backend restart
doesn't kill runs (they are followed again). The Docker socket is root-equivalent on the host: the
app container must be trusted, which is why only Chipova's own code talks to it and only with
fixed images, argv lists, and the isolation flags above. Runs execute on the same host as the app.

## 5. Two tool images, both pinned

**Decision**: `chipova/eda-base:1`, built here from Debian 13 packages on a base pinned by digest
(Icarus, Verilator, Yosys, nextpnr for iCE40, ECP5 and Gowin, IceStorm, Trellis, apicula, ngspice,
Graphviz: about 1.4 GB, native on Intel and ARM), for lint, simulation, synthesis, FPGA and SPICE;
and `chipova/eda-osic:2026.10-3`, the IIC-OSIC-TOOLS 2026.10 image pinned by digest plus the PDK
data SiliconCompiler fetches for SKY130, IHP SG13G2 and GF180 (so Build ASIC runs offline), for
RTL → GDSII, the layout checks, Xschem, CACE and the Xschem desktops. Each tool's version is read
from the image when it is installed and written into every run's manifest.

**Alternatives**: only IIC-OSIC-TOOLS (17 GB on disk before anyone can lint a file); building every
tool from source (hours, and versions we would have to maintain); unpinned `latest` tags (not
reproducible).

**Consequences**: a project can lint and simulate minutes after installing; ASIC needs the big
download. The images are rebuilt only on request (Tools & settings → Rebuild).

## 6. SiliconCompiler for RTL → GDSII; direct tool calls for the rest

**Decision**: Build ASIC uses SiliconCompiler 0.38.10 through its current `Design` / `ASIC` API and
the PDK's target (`sc_flow.py`), not the deprecated `Chip()`; Chipova shows SC's own flowgraph
(23 nodes) with each node's metrics and log. Lint, simulation, synthesis, FPGA and SPICE call the
tools directly through fixed argv lists.

**Alternatives**: SiliconCompiler's `Sim` and `FPGA` projects for those flows too (one
orchestrator for all), or LibreLane for RTL → GDSII.

**Consequences**: the short flows start in a fraction of a second, their exact commands are in the
manifest, and their problems are parsed from the tools' own output; two kinds of adapter to keep.
DRC and LVS are separate flows on the Build ASIC run's full GDS (KLayout and Magic decks, Netgen),
not SC's own checks, so a signoff check is never confused with a P&R metric.

## 7. One node's storage: SQLite, git and files

**Decision**: metadata, queue and audit in SQLite (WAL, one connection, a lock); sources in git;
run outputs and release packages as files under `CHIPOVA_HOME` (the App Store volume).

**Alternatives**: PostgreSQL + MinIO (the blueprint's §3.2): the right choice for several nodes,
not needed on one.

**Consequences**: back up one folder. Moving to PostgreSQL and S3 later touches `db.py`,
`paths.py` and the artifact routes (signed links stay the same idea).

## 8. Signoff is computed from runs; waivers and releases are records

**Decision**: a snapshot's checklist is computed from the runs of that snapshot each time it is
shown; each check has a resolver (registered per check) returning NOT_CONFIGURED, NOT_RUN,
RUNNING, PASS, FAIL, WAIVED or BLOCKED with its evidence. Waivers are records (reason, rule,
snapshot, who asked, who decided) and turn a check WAIVED, never PASS. A release's gate is the same
checklist plus an approval by someone else; FOUNDRY_READY is only the owner's written statement.

**Alternatives**: storing check results (they go stale when runs change).

**Consequences**: there is no way for a check to read PASS without a passing run of that snapshot;
a check with no flow is NOT_CONFIGURED; a check that can't run here (no deck or corners for the
PDK, no CACE datasheet) is BLOCKED and says why.

## 9. AI agents come through the platform's AI Hub, and only propose

**Decision**: Chipova offers its tools to the AI Hub with `reflex_ddns_auth`'s `@tool` (the hub
signs each call for the app); scripts and other agents use the REST API with tokens. An agent acts
with the roles of the person it works for minus what agents may never do (edit, decide on
proposals, approve runs, review, approve waivers or releases, manage). It changes files only by
proposing whole new files, which a person accepts (merged with what people typed meanwhile, frozen
as a snapshot) or rejects with a reason. Runs it asks for wait for a person unless the project lets
AIs run that flow alone (lint and simulation by default). Every call is audited.

**Alternatives**: an agent framework inside Chipova with its own model keys; letting agents edit
the Yjs documents directly.

**Consequences**: one place (the hub) decides which models and whose accounts reach Chipova; the
model only sees what the person it works for may see. Chipova has no chat of its own: the **AI**
button opens the hub's assistant on the project.

## 10. Xschem runs in a desktop container, shown through noVNC

**Decision**: the **Xschem** button starts a container of the IIC-OSIC image per person and
project (its own VNC desktop, a copy of the project's files) and shows the image's own noVNC in the
page; the backend proxies noVNC and bridges its WebSocket to the desktop after checking a ticket
signed for the person. **Save** copies the changed text files back into the co-edited documents.

**Alternatives**: a schematic editor written for the browser (it would have to read and write
Xschem's format with the PDKs' symbols); one shared desktop per project (people would fight over
one mouse).

**Consequences**: the real Xschem with the PDKs' libraries, nothing to install; editing a schematic
is one person's at a time, and their changes reach the others on Save, where a file changed in
both places is left alone and named. Each desktop costs 2 CPUs and 2 GB while it runs; an idle one
is removed after 20 minutes.

## 11. Boards are programmed by a helper on the person's computer

**Decision**: Chipova never touches USB. A **board helper** (`scripts/board_helper.py`, Python's
standard library and openFPGALoader) runs on the computer the board is plugged into, with a token
of its owner: it asks Chipova for jobs (long polling, outbound only), downloads the bitstream
through a signed link, checks its SHA-256 and programs the board, then reports.

**Alternatives**: passing USB devices into the app's container (the App Store's apps run on a
server, the boards sit on people's desks); WebUSB from the page (not every browser, and not
openFPGALoader's cable drivers).

**Consequences**: it works through NAT and firewalls; a helper only receives what its own owner
sent it, from projects where they may program boards; agents never may (PROGRAM_BOARD is never
theirs).

## Revisit when

- more than one backend is needed (co-editing rooms and the queue are in one process; the data is
  local): Hocuspocus or a Redis-backed relay, PostgreSQL, S3, a broker;
- the App Store can't hand out the Docker socket, or runs must go to other machines: a remote runner
  speaking the same JobSpec;
- the Xschem desktops must scale past one computer: they are containers on the same Docker
  daemon, 2 CPUs and 2 GB each.
