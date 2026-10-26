"""Xschem in the browser: the person's desktop (a container of the IIC-OSIC-TOOLS image) starts
with a copy of the project's files and shows through noVNC in the page; what changes in it (a
file edited inside the desktop, standing in for drawing in Xschem) goes back to the project on
Save, for everyone; a file changed in both places is left alone and named; Close removes the
desktop. Needs the chipova/eda-osic image."""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import editor_text, finish, launch, log, new_page, new_project, open_file, set_editor_text, shot, wait_for  # noqa: E402

SCHEMATIC = "v {xschem version=3.4.8 file_version=1.2}\nG {}\nK {}\nV {}\nS {}\nE {}\n"


def desktops() -> list[str]:
    out = subprocess.run(["docker", "ps", "--filter", "label=chipova.desktop", "--format", "{{.Names}}"], capture_output=True, text=True)
    return [n for n in out.stdout.split() if n.startswith("chipova-desktop-dt-")]


def in_desktop(name: str, script: str) -> None:
    subprocess.run(["docker", "exec", "-u", "1000", name, "sh", "-c", script], check=True, timeout=30)


errors: list[str] = []
before = set(desktops())
with sync_playwright() as pw:
    browser = launch(pw)
    page = new_page(browser, errors, "A", width=1500, height=950)
    pid = new_project(page, "Schematics")
    page.click("#new-file")
    page.fill("#new-file-path", "xschem/inv.sch")
    page.click("#create-file")
    open_file(page, "xschem/inv.sch")
    set_editor_text(page, SCHEMATIC)
    wait_for(lambda: page.locator("#chip-sync").inner_text().startswith("Live"), "saved live")
    time.sleep(2)  # the server writes the working copy 1.5 s after the last change
    page.click("#xschem-button")
    frame = page.wait_for_selector("#desktop-frame", timeout=120000)
    started = set(desktops()) - before
    assert len(started) == 1, started
    name = started.pop()
    log("desktop:", name)
    inner = frame.content_frame()
    wait_for(lambda: inner.evaluate("() => document.documentElement.classList.contains('noVNC_connected')"), "noVNC connected to the desktop", 60)
    wait_for(lambda: subprocess.run(["docker", "exec", name, "pgrep", "-x", "xschem"], capture_output=True).returncode == 0, "Xschem runs", 30)
    time.sleep(3)
    shot(page, "01_desktop")
    # An edit in the desktop goes back to the project.
    in_desktop(name, f"cd /foss/designs/{pid} && printf 'T {{hello from xschem}} 0 0 0 0 0.4 0.4 {{}}\\n' >> xschem/inv.sch")
    page.click("#desktop-save")
    wait_for(lambda: page.locator("text=Saved to the project: changed: xschem/inv.sch").count() > 0, "saved")
    page.click("#desktop-hide")
    open_file(page, "xschem/inv.sch")
    wait_for(lambda: "hello from xschem" in (editor_text(page) or ""), "the editor has the desktop's change")
    log("desktop → project: ok")
    # The same file changed in both places: the project's text stays, and Save names it.
    set_editor_text(page, editor_text(page) + "T {from the editor} 0 40 0 0 0.4 0.4 {}\n")
    time.sleep(2)
    in_desktop(name, f"cd /foss/designs/{pid} && printf 'T {{from the desktop}} 0 80 0 0 0.4 0.4 {{}}\\n' >> xschem/inv.sch")
    page.click("#xschem-button")
    page.wait_for_selector("#desktop-frame")
    page.click("#desktop-save")
    wait_for(lambda: page.locator("text=Left alone, as they changed in the project meanwhile: xschem/inv.sch").count() > 0, "the conflict is named")
    page.click("#desktop-close")
    wait_for(lambda: name not in desktops(), "the desktop is removed", 30)
    open_file(page, "xschem/inv.sch")
    text = editor_text(page) or ""
    assert "from the editor" in text and "from the desktop" not in text, text
    log("conflict kept the project's text; desktop closed")
    browser.close()
finish(errors)
