"""Lint finds a syntax error at its line (problems, the editor's marker, a click goes there); a
fixed design lints clean; the simulation passes with its waveform; a testbench that says FAIL
fails its run."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import editor_position, editor_text, finish, launch, log, markers, new_page, new_project, open_file, run_flow, set_editor_text, shot, wait_for, wait_run_end  # noqa: E402

errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A")
    new_project(page, "Lint and sim")
    good = editor_text(page)
    broken = good.replace("count <= count + 1'b1;", "count <= count + 1'b1")
    set_editor_text(page, broken)
    run_flow(page, "rtl_lint")
    assert wait_run_end(page) == "FAILED"
    page.click("[data-bottom=problems]")
    wait_for(lambda: page.locator("#problems [data-problem^='rtl/heartbeat.v:']").count() > 0, "a problem in heartbeat.v")
    where = page.locator("#problems [data-problem^='rtl/heartbeat.v:']").first.get_attribute("data-problem")
    line = int(where.split(":")[1])
    log("problem at", where)
    assert 17 <= line <= 19, where
    wait_for(lambda: any(m[0] == line for m in markers(page)), "the editor marks the line")
    page.locator("#problems [data-problem^='rtl/heartbeat.v:']").first.click()
    wait_for(lambda: (editor_position(page) or [0])[0] == line, "the click goes to the line")
    shot(page, "01_lint_error")
    set_editor_text(page, good)
    run_flow(page, "rtl_lint")
    assert wait_run_end(page) == "SUCCEEDED"
    wait_for(lambda: not any(m[1] == 8 for m in markers(page)), "the error marker is gone")
    run_flow(page, "rtl_sim")
    assert wait_run_end(page) == "SUCCEEDED"
    page.click("[data-bottom=wave]")
    wait_for(lambda: page.locator("#wave-viewer[data-ready='1']").count() == 1, "the waveform is shown")
    box = page.locator("#wave-viewer canvas").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.7, box["y"] + 50)
    wait_for(lambda: page.get_attribute("#wave-viewer", "data-cursor") not in (None, ""), "a cursor")
    page.locator(".chip-wave-search").fill("tb_heartbeat.dut.count")
    page.locator(".chip-wave-search").press("Enter")
    page.locator(".chip-wave-search").dispatch_event("change")
    shot(page, "02_wave")
    # A testbench that expects the wrong thing: its FAIL fails the run.
    open_file(page, "tb/tb_heartbeat.v")
    set_editor_text(page, editor_text(page).replace("if (pulses != 3)", "if (pulses != 4)"))
    run_flow(page, "rtl_sim")
    assert wait_run_end(page) == "FAILED"
    wait_for(lambda: "testbench reported a failure" in page.inner_text("#bottom-panel"), "it says why")
    shot(page, "03_sim_fail")
    browser.close()
finish(errors)
