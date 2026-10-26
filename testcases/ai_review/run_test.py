"""An AI proposes, people decide (AC-02, AC-03, AC-10): a rejected proposal changes nothing and
the AI reads why; an accepted one is applied for everyone as a snapshot; a flow the project
doesn't let an AI run alone waits for a person; a command that isn't a flow is refused; every
tool call, reading ones too, is in the project's log."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import editor_text, finish, launch, log, new_page, new_project, shot, tool, wait_for  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A")
    pid = new_project(page, "AI review")
    before = editor_text(page)
    src = tool("chipova.read_file", room=pid, path="rtl/heartbeat.v")["result"]["text"]
    assert src == before
    # A proposal people reject: nothing changes, the AI reads the reason.
    r = tool("chipova.propose_patch", room=pid, title="Make the counter 16 bits",
             changes=[{"path": "rtl/heartbeat.v", "content": src.replace("N = 8", "N = 16")}], rationale="slower heartbeat")
    first = r["result"]["proposal"]
    wait_for(lambda: page.locator(f"[data-proposal='{first}']").count() == 1, "the proposal shows")
    page.click(f"[data-reject='{first}']")
    page.fill("#reject-reason", "N must stay 8 for the demo board")
    page.click("#confirm-reject")
    wait_for(lambda: page.locator(f"[data-proposal='{first}'][data-proposal-status='REJECTED']").count() == 1, "rejected")
    st = tool("chipova.proposal_status", room=pid, proposal=first)["result"]
    assert st["status"] == "REJECTED" and "demo board" in st["reason"], st
    assert editor_text(page) == before
    log("rejected, unchanged, reason read by the AI")
    # A proposal people accept: applied for everyone, a snapshot of it.
    r = tool("chipova.propose_patch", room=pid, title="Make the counter 6 bits",
             changes=[{"path": "rtl/heartbeat.v", "content": src.replace("N = 8", "N = 6")}],
             rationale="64 clocks between pulses", plan="rtl_lint and rtl_sim")
    second = r["result"]["proposal"]
    wait_for(lambda: page.locator(f"[data-open-proposal='{second}']").count() == 1, "the second proposal shows")
    page.click(f"[data-open-proposal='{second}']")
    page.wait_for_selector("#proposal-view [data-diff-file='rtl/heartbeat.v']")
    shot(page, "01_diff")
    page.click("#accept-proposal")
    wait_for(lambda: "parameter N = 6" in (editor_text(page) or ""), "the editor shows the accepted change")
    st = tool("chipova.proposal_status", room=pid, proposal=second)["result"]
    assert st["status"] == "APPROVED" and st["snapshot_short"], st
    wait_for(lambda: page.inner_text("#latest-snapshot") == st["snapshot_short"], "the accepted change is the latest snapshot")
    log("accepted as snapshot", st["snapshot_short"])
    # The AI may lint and simulate alone; synthesis waits for a person.
    sim = tool("chipova.run", room=pid, flow="rtl_sim")["result"]
    assert sim["status"] == "SUCCEEDED" and sim["snapshot_short"] == st["snapshot_short"], sim
    synth = tool("chipova.run", room=pid, flow="synth_yosys")["result"]
    assert synth["status"] == "WAITING_FOR_APPROVAL", synth
    page.click("[data-bottom=runs]")
    wait_for(lambda: page.locator(f"[data-approve-run='{synth['run']}']").count() == 1, "an approve button")
    page.click(f"[data-approve-run='{synth['run']}']")
    done = tool("chipova.get_run", room=pid, run=synth["run"], wait=True)["result"]
    assert done["status"] == "SUCCEEDED", done
    # No commands: only flows, only their parameters.
    for bad in ({"flow": "shell", "params": {"cmd": "id"}}, {"flow": "rtl_lint", "params": {"top": "x; id"}}, {"flow": "rtl_lint", "params": {"argv": ["id"]}}):
        res = tool("chipova.run", room=pid, **bad)
        assert res["ok"] is False, res
    res = tool("chipova.propose_patch", room=pid, title="escape", changes=[{"path": "../../x", "content": "x"}])
    assert res["ok"] is False
    page.click("[data-view=agents]")
    wait_for(lambda: page.locator("#agent-calls >> text=denied").count() >= 4, "the refusals are in the log")
    # Reading counts too: every tool call is in the log, not only what changed something.
    assert page.locator("#agent-calls >> text=tool.chipova.read_file").count() >= 1
    shot(page, "02_agents")
    browser.close()
finish(errors)
