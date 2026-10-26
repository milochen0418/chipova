"""On a phone (390 x 844, blueprint §4.4): the phone layout, not the editor's panes; the AI's
proposal is reviewed and accepted; a run the AI asked for is approved and ends; a file is read
and a comment put on one of its lines; the other views stack and nothing scrolls sideways."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import finish, launch, log, new_page, new_project, open_project, shot, tool, wait_for  # noqa: E402


def no_sideways_scroll(page) -> bool:  # noqa: ANN001
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    desk = new_page(browser, errors, "Desk")
    pid = new_project(desk, "On the go")
    phone = new_page(browser, errors, "Phone", width=390, height=844)
    open_project(phone, pid, wait=False)
    phone.wait_for_selector("[data-phone-tab=ai]", timeout=60000)
    assert phone.locator("#editor-panel").count() == 0, "no editor panes on a phone"
    # The AI proposes; the phone reviews and accepts it.
    src = tool("chipova.read_file", room=pid, path="rtl/heartbeat.v")["result"]["text"]
    prop = tool("chipova.propose_patch", room=pid, title="Six bits", changes=[{"path": "rtl/heartbeat.v", "content": src.replace("N = 8", "N = 6")}],
                rationale="A faster heartbeat for the demo board.")["result"]["proposal"]
    wait_for(lambda: phone.locator(f"[data-open-proposal='{prop}']").count() == 1, "the proposal on the phone")
    phone.click(f"[data-open-proposal='{prop}']")
    phone.wait_for_selector("#proposal-view [data-diff-file='rtl/heartbeat.v']")
    assert no_sideways_scroll(phone)
    shot(phone, "01_proposal")
    phone.click("#accept-proposal")
    wait_for(lambda: phone.locator(f"[data-proposal='{prop}'][data-proposal-status='APPROVED']").count() == 1, "accepted")
    log("accepted on the phone")
    # A run the AI asked for, approved on the phone.
    synth = tool("chipova.run", room=pid, flow="synth_yosys")["result"]
    phone.click("[data-phone-tab=runs]")
    wait_for(lambda: phone.locator(f"[data-approve-run='{synth['run']}']").count() == 1, "an approve button")
    shot(phone, "02_runs")
    phone.click(f"[data-approve-run='{synth['run']}']")
    wait_for(lambda: phone.get_attribute(f"[data-run='{synth['run']}']", "data-run-status") == "SUCCEEDED", "the synthesis ends", 120)
    log("approved and done")
    # Read a file and comment on its third line.
    phone.click("[data-phone-tab=files]")
    phone.click("[data-phone-file='rtl/heartbeat.v']")
    phone.wait_for_selector("#phone-file [data-phone-line='3']")
    phone.click("#phone-file [data-phone-line='3']")
    phone.fill("#comment-text", "Is 6 bits enough for the board?")
    phone.click("#comment-line")
    phone.click("[data-phone-tab=comments]")
    wait_for(lambda: phone.locator("[data-comment='rtl/heartbeat.v:3']").count() == 1, "the comment on line 3")
    shot(phone, "03_comment")
    # The other views stack.
    phone.click("[data-view=signoff]")
    phone.wait_for_selector("#signoff-checks [data-check=lint]")
    assert no_sideways_scroll(phone)
    phone.click("[data-view=implement]")
    phone.wait_for_selector("[data-start=synth_yosys]")
    assert no_sideways_scroll(phone)
    shot(phone, "04_implement")
    browser.close()
finish(errors)
