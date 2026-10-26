"""Analog across corners (needs chipova/eda-osic): the IHP inverter template's datasheet passes
CACE at every corner, its specs and schematic show on the run, and the signoff's AMS PVT check
passes; Xschem simulation netlists the testbench and ngspice measures its delays."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, new_project, run_flow, shot, wait_for, wait_run_end  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A", width=1500, height=950)
    new_project(page, "Inverter corners", "ams_corners_ihp")
    files = page.eval_on_selector_all("#explorer [data-file]", "els => els.map(e => e.getAttribute('data-file'))")
    assert {"cace/inverter.yaml", "xschem/inverter.sch", "xschem/inverter_tb.sch"} <= set(files), files
    run_flow(page, "ams_cace")
    assert wait_run_end(page, 600) == "SUCCEEDED"
    page.click("[data-view=implement]")
    page.wait_for_selector("#implement-view")
    wait_for(lambda: "5 of 5 specs met at every corner" in page.inner_text("#run-facts"), "CACE's verdict")
    facts = page.inner_text("#run-facts")
    for spec in ("Delay, output falling", "Delay, output rising", "Switching threshold VM", "Noise margin low", "Noise margin high"):
        assert spec in facts, (spec, facts)
    wait_for(lambda: page.locator("#implement-view img[alt=schematic]").count() == 1, "the testbench's schematic")
    log("CACE:", " | ".join(facts.split("\n")[:4]))
    shot(page, "01_corners")
    page.click("[data-view=code]")
    run_flow(page, "ams_xschem")
    assert wait_run_end(page, 300) == "SUCCEEDED"
    page.click("[data-view=implement]")
    wait_for(lambda: "tpd_hl" in page.inner_text("#run-facts"), "the measured delays")
    log("Xschem:", " | ".join(page.inner_text("#run-facts").split("\n")[:4]))
    shot(page, "02_xschem")
    page.click("[data-view=signoff]")
    page.wait_for_selector("#signoff-checks [data-check=ams_pvt]")
    assert page.get_attribute("#signoff-checks [data-check=ams_pvt]", "data-check-status") == "PASS"
    shot(page, "03_signoff")
    log("AMS PVT corners PASS on the signoff")
    browser.close()
finish(errors)
