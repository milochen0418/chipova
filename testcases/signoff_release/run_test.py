"""Signoff and release with two people (AC-07, AC-11): checks come from this snapshot's runs; a
waiver needs someone else to approve it and shows as WAIVED; a release can't be approved before
its gate passes, nor by whoever asked for it; once approved, its package downloads."""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, new_project, open_project, run_flow, shot, wait_for, wait_run_end  # noqa: E402

ALICE, BOB = "alice@example.com", "bob@example.com"


def check_status(page, category: str) -> str:
    return page.get_attribute(f"#signoff-checks [data-check='{category}']", "data-check-status") or ""


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    alice = new_page(browser, errors, "Alice", email=ALICE)
    bob = new_page(browser, errors, "Bob", email=BOB)
    pid = new_project(alice, "Blinky release", "fpga_blinky")
    alice.click("[data-view=settings]")
    alice.fill("#new-member", BOB)
    alice.select_option("select:near(#new-member)", "reviewer")
    alice.click("#add-member")
    wait_for(lambda: BOB in alice.inner_text("#members"), "Bob is a reviewer")
    # Nothing ran yet: no PASS anywhere.
    alice.click("[data-view=signoff]")
    alice.wait_for_selector("#signoff-checks [data-check='sim']")
    assert check_status(alice, "sim") == "NOT_RUN" and check_status(alice, "fpga_timing") == "NOT_RUN"
    # A release asked for now is held at its gate.
    alice.click("[data-view=release]")
    alice.click("#new-release")
    alice.fill("#release-title", "Bitstream 1")
    alice.click("#create-release")
    alice.wait_for_selector("[data-release][data-release-status=DRAFT]")
    alice.click("[data-review]")
    alice.wait_for_selector("[data-release][data-release-status=IN_REVIEW]")
    assert alice.locator("[data-approve-release]").count() == 0, "the requester can't approve"
    open_project(bob, pid)
    bob.click("[data-view=release]")
    bob.wait_for_selector("[data-approve-release]")
    bob.click("[data-approve-release]")
    bob.fill("#decision-text", "looked at the sources")
    bob.click("#confirm-decision")
    wait_for(lambda: bob.locator("text=The gate is not passed").count() > 0, "Bob is told what is missing")
    assert bob.locator("[data-release][data-release-status=IN_REVIEW]").count() == 1
    shot(bob, "01_gate_blocked")
    log("gate held the release")
    bob.click("text=Cancel")
    # The evidence, on the release's snapshot.
    alice.click("[data-view=code]")
    run_flow(alice, "rtl_sim", freeze=False)
    assert wait_run_end(alice) == "SUCCEEDED"
    run_flow(alice, "fpga_ice40", freeze=False)
    assert wait_run_end(alice, 300) == "SUCCEEDED"
    # A waiver for the lint: asked by Alice, approved by Bob, WAIVED (not PASS).
    alice.click("[data-view=signoff]")
    alice.wait_for_selector("#signoff-checks [data-check='lint']")
    wait_for(lambda: check_status(alice, "sim") == "PASS" and check_status(alice, "fpga_timing") == "PASS", "sim and timing pass")
    alice.click("[data-waive='lint']")
    alice.fill("#waiver-reason", "Lint is run by the board vendor's own flow for this IP")
    alice.click("#confirm-waiver")
    bob.click("[data-view=signoff]")
    bob.wait_for_selector("[data-approve-waiver]")
    bob.click("[data-approve-waiver]")
    wait_for(lambda: check_status(bob, "lint") == "WAIVED", "lint is WAIVED")
    shot(bob, "02_signoff")
    # Now Bob can approve, and the package downloads.
    bob.click("[data-view=release]")
    bob.wait_for_selector("[data-approve-release]")
    bob.click("[data-approve-release]")
    bob.fill("#decision-text", "sim and timing pass on this snapshot")
    bob.click("#confirm-decision")
    wait_for(lambda: bob.locator("[data-release][data-release-status=APPROVED]").count() == 1, "approved")
    bob.click("[data-package]")
    bob.wait_for_selector("[data-download-package]")
    with bob.expect_download() as d:
        bob.click("[data-download-package]")
    with zipfile.ZipFile(d.value.path()) as z:
        names = z.namelist()
        manifest = z.read("RELEASE_MANIFEST.json").decode()
    assert "source/rtl/blinky.v" in names and any(n.endswith("blinky.bin") for n in names), names[:20]
    assert '"passed": true' in manifest and "NOT a foundry signoff" in manifest
    log("package:", len(names), "files")
    shot(bob, "03_released")
    browser.close()
finish(errors)
