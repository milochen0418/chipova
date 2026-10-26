"""The iCEBreaker blinky builds to a bitstream with its timing; the bitstream downloads and its
SHA-256 is the one recorded; built again on the same snapshot, Compare finds nothing different
(AC-06)."""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, new_project, shot, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A")
    new_project(page, "Blinky", "fpga_blinky")
    page.click("[data-view=implement]")
    page.click("[data-start=fpga_ice40]")
    wait_for(lambda: page.locator("#implement-view [data-node='pack'][data-node-status=SUCCEEDED]").count() == 1, "the bitstream is packed", 300)
    wait_for(lambda: page.locator("#run-facts").count() == 1 and "Fmax" in page.inner_text("#run-facts"), "the timing shows")
    facts = page.inner_text("#run-facts")
    log("facts:", " | ".join(facts.split("\n")[:8]))
    shot(page, "01_fpga")
    # The run's last refresh redraws the artifact rows (with new signed links): let it settle.
    wait_for(lambda: page.locator("#artifacts [data-download='fpga/blinky.bin']").count() == 1, "the bitstream is listed")
    page.wait_for_timeout(1500)
    row = page.locator("#artifacts tr", has_text="fpga/blinky.bin")
    sha = row.locator("code[title]").get_attribute("title")
    with page.expect_download() as d:
        row.locator("[data-download='fpga/blinky.bin']").click()
    data = Path(d.value.path()).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha, "the downloaded bitstream isn't the recorded one"
    assert len(data) > 100000, len(data)
    log(f"bitstream {len(data)} bytes, sha256 matches")
    row.locator("[data-verify='fpga/blinky.bin']").click()
    wait_for(lambda: page.locator("text=SHA-256 matches").count() > 0, "the server checks it again")
    # AC-06: the same build again on the same snapshot, compared with the first: what went in
    # (snapshot, parameters, image, tool versions) and what came out (every output's SHA-256).
    first = page.locator("#implement-view [data-run]").first.get_attribute("data-run")
    page.click("text=Run again")
    wait_for(lambda: page.locator("#implement-view [data-run]").count() == 2, "the second build is listed")
    second = next(r for r in page.eval_on_selector_all("#implement-view [data-run]", "els => els.map(e => e.getAttribute('data-run'))") if r != first)
    wait_for(lambda: "Succeeded" in page.inner_text(f"#implement-view [data-run='{second}']"), "the second build", 300)
    page.click(f"#implement-view [data-run='{second}']")
    wait_for(lambda: page.locator(f"#compare-run option[value='{first}']").count() == 1, "the first build to compare with")
    page.select_option("#compare-run", first)
    page.click("#compare-button")
    page.wait_for_selector("#run-compare")
    rows = page.locator("#run-compare tbody tr").count()
    differs = page.locator("#run-compare >> text=differs").count()
    log(f"compared: {rows} rows, {differs} differ")
    assert rows >= 10 and differs == 0, (rows, differs)
    assert page.locator("#run-compare tr", has_text="Artifact fpga/blinky.bin").count() == 1
    shot(page, "02_compare")
    browser.close()
finish(errors)
