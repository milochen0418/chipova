"""Templates make working projects: their files, a first snapshot, a lint that passes; the list
shows them with their last run; deleting asks first."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, new_project, open_home, run_flow, shot, wait_for, wait_run_end  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A")
    pid = new_project(page, "Smoke heartbeat")
    files = page.eval_on_selector_all("#explorer [data-file]", "els => els.map(e => e.getAttribute('data-file'))")
    log("files", files)
    assert {"rtl/heartbeat.v", "tb/tb_heartbeat.v", "constraints/heartbeat.sdc", "chipova.toml"} <= set(files), files
    assert page.inner_text("#latest-snapshot") != "none"
    run_flow(page, "rtl_lint")
    assert wait_run_end(page) == "SUCCEEDED"
    shot(page, "01_lint")
    for template, expect in (("fpga_blinky", "constraints/icebreaker.pcf"), ("ams_inverter", "spice/inverter.spice")):
        new_project(page, f"Smoke {template}", template)
        files = page.eval_on_selector_all("#explorer [data-file]", "els => els.map(e => e.getAttribute('data-file'))")
        assert expect in files, (template, files)
        log(template, "ok")
    open_home(page)
    wait_for(lambda: page.locator("#project-list [data-project]").count() == 3, "three projects listed")
    row = page.locator(f"[data-project='{pid}']")
    wait_for(lambda: "Lint" in row.inner_text(), "the heartbeat shows its last run")
    shot(page, "02_list")
    # Deleting asks first.
    last = page.locator("#project-list [data-project]").first
    last.locator("button[title=More]").click()
    page.get_by_role("menuitem", name="Delete").click()
    page.wait_for_selector("#confirm-delete")
    page.click("#confirm-delete")
    wait_for(lambda: page.locator("#project-list [data-project]").count() == 2, "one project gone")
    browser.close()
finish(errors)
