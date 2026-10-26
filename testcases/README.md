# E2E testcases

Playwright end-to-end suites, one per folder:

- `testcases/<suite_name>/run_test.py`
- `testcases/<suite_name>/output/` (screenshots and logs, ignored by git)

Each `run_test.py` exits `0` on success and non-zero on failure, and writes its screenshots into
`OUTPUT_DIR` (provided by the runner). Shared helpers are in `common.py`: a browser tab per person
(a guest, or signed in with the platform's cookie signed by the test secret), making and opening
projects, waiting until the editor is joined to its shared document, reading and replacing the
editor's text, starting a flow from the Run menu and waiting for it to end, calling Chipova's AI
tools as the AI Hub does, and plain HTTP calls to the backend.

Every run starts its own server with its own data folder (`CHIPOVA_HOME=$OUTPUT_DIR/home`, fresh
each time), so your projects are never touched; the runs are real containers on your Docker, so
Docker must be running with the tool images installed (`chipova/eda-base:1`; the ASIC flows need
`chipova/eda-osic:2026.10-1`). The runner sets `DDNS_AUTH_SECRET` to a test value and
`SERVICE_SUBDOMAIN=chipova`. A suite's own server settings go in `testcases/<suite>/server.env`
(`KEY=value` lines), which the runner loads before it starts the server.

## Suites

| Suite | What it checks |
|-------|----------------|
| `smoke_home` | Each template makes a working project: its files, a first snapshot, a lint that passes; the list shows them with their last run; deleting asks first. |
| `collab_live` | Two people on one project: both see two people; both type at once at the two ends of the same file and end with the same text holding both edits; each sees the other's caret; the dot for editors differing from the snapshot, cleared for both when one freezes; which file the other has open; someone leaving is seen at once. |
| `lint_sim` | A syntax error fails Lint with the problem at its line (the problems list, the editor's marker, a click goes there); the fixed design lints clean and the marker goes; the simulation passes and its waveform is drawn (a cursor, a signal added); a testbench that prints FAIL fails its run and says why. |
| `ai_review` | An AI (through the tool endpoint) proposes; rejected with a reason, nothing changes and the AI reads the reason; accepted, the change is in everyone's editor and is the latest snapshot; the AI simulates alone, but its synthesis waits for a person's approval; a command, an injected parameter, an extra argv and a path outside the project are refused; every call, reading ones too, is on the Agents page. |
| `fpga_build` | The iCEBreaker blinky builds to a bitstream with its Fmax; the bitstream downloads and its SHA-256 is the recorded one, and the server checks it again; built again on the same snapshot, Compare finds nothing different. |
| `permissions` | A private project refuses someone without access on the page, the REST API (his own token), the co-editing socket (a genuine ticket: closed with 4403) and a download link signed for him, and audits each refusal; made a viewer, he reads but can't type, run or freeze, and the link works. |
| `signoff_release` | Two signed-in people: nothing is PASS before it ran; a release asked for at once is held at its gate, the requester can't approve it and the reviewer is told what is missing; after the runs, a lint waiver asked by one and approved by the other reads WAIVED; the reviewer approves and the package (sources, bitstream, manifest saying it is not a foundry signoff) downloads. |
| `perf_baseline` | Measures (blueprint §12): the co-editing delay between two tabs, catching up after five 3 s drops, queue waits with six runs and two at once, every artifact's SHA-256 on download, the same FPGA build twice; writes `perf.json` with the machine's CPU, memory and Docker. See [docs/e2e-test-plan.md](../docs/e2e-test-plan.md). |

## Running

```bash
poetry run ./run_test_suite.sh smoke_home
poetry run ./run_test_suite.sh collab_live
poetry run ./run_test_suite.sh lint_sim
poetry run ./run_test_suite.sh ai_review
poetry run ./run_test_suite.sh fpga_build
poetry run ./run_test_suite.sh permissions
poetry run ./run_test_suite.sh signoff_release
poetry run ./run_test_suite.sh perf_baseline
```

If ports 3000/8000 belong to another app, use others: `FRONTEND_PORT=3171 BACKEND_PORT=8171`.
With a re-ddns dev install of this checkout running (its hot reload watches the checkout), write
the output elsewhere: `OUTPUT_DIR=/tmp/chipova-e2e/<suite>`. Run one suite at a time: the runner
stops whatever holds its two ports when it ends.

The suites that only need the browser and guests (`smoke_home`, `lint_sim`, `fpga_build`) also
run against the live app, without the runner:
`BASE_URL=https://chipova.reflex-ddns.com OUTPUT_DIR=/tmp/chipova-live poetry run python testcases/lint_sim/run_test.py`
(Chromium maps `*.reflex-ddns.com` to 127.0.0.1). They make projects there: delete them afterwards.

Optional env vars:
- `BASE_URL` (default `http://127.0.0.1:3000`) and `BACKEND_URL`
- `HEADLESS=0` to watch the browser
- `PW_SLOWMO_MS=100` to slow actions down
- `PW_TIMEOUT_MS=60000` to change Playwright timeouts
