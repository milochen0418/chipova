"""Programming a board through one's own board helper (scripts/board_helper.py, run here with
--dry-run: no board needed): with no helper running, the dialog says how to start one; once it
runs, the person picks it and the board, the helper takes the job, checks the bitstream's SHA-256
and reports, and the run shows how it went."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "testcases"))
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BACKEND_URL, OUTPUT_DIR, finish, launch, log, new_page, new_project, shot, wait_for  # noqa: E402

ALICE = "alice@example.com"

errors: list[str] = []
helper = None
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "Alice", email=ALICE)
    new_project(page, "Board", "fpga_blinky")
    page.click("[data-view=implement]")
    page.click("[data-start=fpga_ice40]")
    wait_for(lambda: page.locator("#implement-view [data-node='pack'][data-node-status=SUCCEEDED]").count() == 1, "the bitstream", 300)
    page.click("#program-board-open")
    page.wait_for_selector("#look-again")
    assert "board_helper.py" in page.inner_text("[role=dialog]"), "it says how to start a helper"
    from chipova.services import api  # noqa: E402 — the app's own signing, with its secret
    from chipova.services.actors import Actor  # noqa: E402

    token = api.make_token(Actor(ALICE, "Alice", email=ALICE))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    helper_log = open(OUTPUT_DIR / "helper.log", "w")  # noqa: SIM115
    helper = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "board_helper.py"), "--url", BACKEND_URL, "--token", token, "--name", "Test bench", "--dry-run", "--once"],
        stdout=helper_log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    def helper_listed() -> bool:
        if page.locator("#look-again").count():
            page.click("#look-again")
        return page.locator("#board-helper option").count() > 0

    wait_for(helper_listed, "the helper shows up", 30)
    assert page.input_value("#board-name") == "ice40_generic"  # openFPGALoader's name for the iCEBreaker
    shot(page, "01_dialog")
    page.click("#program-board")
    wait_for(lambda: page.locator("[data-board-status=DONE], [data-board-status=FAILED]").count() > 0, "the helper reports", 60)
    status = page.get_attribute("[data-board-job]", "data-board-status")
    page.locator("[data-board-job] summary").first.click()
    text = page.inner_text("[data-board-job]")
    log("job:", status, "|", " ".join(text.split())[:160])
    assert status == "DONE" and "SHA-256" in text and "matches" in text and "dry run" in text, text
    assert helper.wait(timeout=30) == 0, "the helper ends after its one job"
    shot(page, "02_done")
    browser.close()
if helper is not None and helper.poll() is None:
    helper.kill()
finish(errors)
