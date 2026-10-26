"""The Lab page: "Check the package plan" passes on the Heartbeat's QFN-16 plan and draws its bond
diagram; two OpenHTF records dropped on the page (one chip in spec, one with its pulse too slow)
show beside the spec and the design's own values; the signoff's Package & pinout check passes."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "testcases"))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, new_project, shot, wait_for  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A")
    new_project(page, "Test chip")
    page.click("[data-view=lab]")
    page.wait_for_selector("#lab-view")
    assert page.locator("[data-measure=pulse_period_us][data-verdict='not measured']").count() == 1, "the spec, before any chip"
    page.click("[data-start=package_check]")
    wait_for(lambda: page.locator("#bond-diagram").count() == 1, "the bond diagram", 120)
    facts = page.inner_text("#run-facts")
    log("plan:", " | ".join(facts.split("\n")[:6]))
    assert "QFN-16" in facts
    shot(page, "01_package")
    page.set_input_files("#lab-upload input[type=file]", [str(FIXTURES / "openhtf_chip001_pass.json"), str(FIXTURES / "openhtf_chip002_fail.json")])
    wait_for(lambda: page.locator("[data-lab-record]").count() == 2, "two test records")
    period = page.locator("[data-measure=pulse_period_us]")
    wait_for(lambda: period.get_attribute("data-verdict") == "out of spec", "CHIP-002's pulse is too slow")
    assert "1 / 2" in period.inner_text() and "2.56" in period.inner_text(), period.inner_text()
    assert page.get_attribute("[data-measure=pulse_width_ns]", "data-verdict") == "in spec"
    page.locator("#lab-compare").scroll_into_view_if_needed()
    shot(page, "02_measurements")
    page.click("[data-view=signoff]")
    page.wait_for_selector("#signoff-checks [data-check=package]")
    assert page.get_attribute("#signoff-checks [data-check=package]", "data-check-status") == "PASS"
    log("package check PASS on the signoff")
    browser.close()
finish(errors)
