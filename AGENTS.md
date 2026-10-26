# AGENTS.md

This file describes how an AI coding agent (and humans) should work in this repository.

## 0) Always read the docs first

Before making changes or running commands, **read all README.md files in this repo** and follow them.

- Repo overview & dev workflow: `README.md`
- E2E test runner conventions: `testcases/README.md`
- How it is built: `docs/architecture.md`; why: `docs/adr/0001-core-decisions.md`
- What is done and what isn't: `docs/status.md` (update it when you change what Chipova can do)

If you already read them earlier in the session, **re-check** when unsure.

## 1) Python / Poetry requirements (strict)

This project targets **Python 3.11** (always set the Poetry env to 3.11 before installing deps or running commands).

- Prefer Poetry-managed environments (the venv is in-project: `.venv`).
- If Poetry selected another Python (e.g. 3.12+), switch it:

```bash
poetry env use python3.11
poetry env info
poetry install
```

If `python3.11` is not available on PATH, use an absolute path to the 3.11 executable.

## 2) Default rule: use `poetry run` for scripts

When running any repo scripts, prefer:

- `poetry run <command>`

This ensures the correct virtualenv + dependencies are used.

## 3) Running the app: prefer `reflex_rerun.sh`

When you need to start/restart the Reflex app during development, **prefer the repo helper script**.

```bash
poetry run ./reflex_rerun.sh
```

Notes:
- Prefer `poetry run ./reflex_rerun.sh` over `poetry run reflex run`.
- It runs on the expected ports: frontend `3000`, backend `8000`. **Other apps on this machine may
  hold them** (and the script frees its ports by force): check `lsof -nP -iTCP:3000 -iTCP:8000
  -sTCP:LISTEN` first, and use other ports when they are taken:
  `REFLEX_API_URL=http://localhost:8150 poetry run reflex run --frontend-port 3150 --backend-port 8150`.
- Runs need **Docker** and the tool images (Tools & settings → Install, or `infra/dockerfiles`).
- Run one Chipova server per checkout at a time: two share `.web/`.

## 4) Tests

Unit and integration tests (pytest; `-m docker` ones start real containers):

```bash
poetry run pytest -m "not docker"
poetry run pytest -m docker
scripts/ci.sh            # what CI runs (STAGES="unit docker", SUITES="…" to pick; see its header)
```

E2E suites live under `testcases/<suite_name>/run_test.py`. Do **not** run Playwright suites by
starting/stopping the server manually unless you have to; use the repo runner, which starts and
stops the server, gives the suite a fresh data folder (`CHIPOVA_HOME`) and a test sign-in secret,
and collects artifacts:

```bash
poetry run ./run_test_suite.sh smoke_home
```

Optional environment variables (see `testcases/README.md`):

- `FRONTEND_PORT` / `BACKEND_PORT` (other ports when 3000/8000 are taken)
- `OUTPUT_DIR` (**outside the repo** when a re-ddns dev install of this checkout is running: its
  hot reload watches the checkout, and a reload drops everyone's editing sockets)
- `BASE_URL` (default `http://127.0.0.1:3000`), `HEADLESS=0` to watch the browser

## 5) Rules of this codebase

- **No commands from outside**: a run is a flow's builder turning a snapshot and checked
  parameters into argv lists. Never add a way to pass a shell string or an arbitrary command, for
  people, the API or AI tools.
- **Access is checked at every door**: services call `projects.require(project, actor, action)`;
  the co-editing socket, signed links and AI tools check again. Don't rely on the page hiding a
  button.
- **AI agents propose, people decide**: agents never edit files, decide on proposals, approve runs,
  review, approve waivers or releases (`roles.NEVER_FOR_AGENTS`).
- **No fake success**: a signoff check is PASS only from a passing run of that snapshot; a check
  with no flow is NOT_CONFIGURED, one that can't run here is BLOCKED with why. Never mark anything
  FOUNDRY_READY automatically.
- **Runs only read snapshots**, never the live editors.
- **Edit callees before callers** while a re-ddns dev install hot-reloads this checkout: a caller
  saved before the function it calls exists crashes the live app until the next save.

## 6) Expectations when acting as an agent

- Prefer the smallest, focused change set.
- After code changes, run the closest relevant check (at minimum the related suite via `run_test_suite.sh`).
- Report outcomes: what you ran, pass/fail, and where artifacts/logs were written.

## 7) Smart way to help the Agent to debug

```
poetry run ./reflex_rerun.sh --loglevel debug
```
