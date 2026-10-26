"""Two people on one project: who is here, typing at once in the same file, carets, the editors
differing from the snapshot, and someone leaving."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import editor_text, finish, launch, log, new_page, new_project, open_project, shot, wait_for  # noqa: E402

def caret(page, where: str) -> None:
    """Puts the page's caret at the start or the end of the open file."""
    page.evaluate(
        "(where) => { const p = document.getElementById('editor-panel'); const e = monaco.editor.getEditors().find(x => p.contains(x.getContainerDomNode()));"
        " const m = e.getModel(); const end = m.getPositionAt(m.getValueLength()); e.setPosition(where === 'end' ? end : {lineNumber: 1, column: 1}); e.focus(); }",
        where,
    )


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    a = new_page(browser, errors, "A")
    b = new_page(browser, errors, "B")
    pid = new_project(a, "Together")
    open_project(b, pid)
    wait_for(lambda: a.inner_text("#people-count").startswith("2") and b.inner_text("#people-count").startswith("2"), "both see two people")
    assert a.locator("#dirty-dot").count() == 0
    # Both type at once in the same file, A at its start and B at its end: everyone ends with
    # the same text, with both edits.
    a.locator("#editor-panel .monaco-editor").click()
    b.locator("#editor-panel .monaco-editor").click()
    caret(a, "start")
    caret(b, "end")
    for ca, cb in zip("// from A ", " // fromB!"):
        a.keyboard.type(ca)
        b.keyboard.type(cb)
    wait_for(lambda: editor_text(a) == editor_text(b), "the same text in both", 15)
    text = editor_text(a)
    assert text.startswith("// from A ") and text.rstrip().endswith("// fromB!"), text[:60] + " … " + text[-40:]
    log("merged")
    wait_for(lambda: a.locator(".yRemoteSelectionHead").count() > 0 and b.locator(".yRemoteSelectionHead").count() > 0, "each sees the other's caret")
    wait_for(lambda: a.locator("#dirty-dot").count() == 1 and b.locator("#dirty-dot").count() == 1, "both see the editors differ from the snapshot", 20)
    shot(a, "01_together")
    # A freezes: the dot goes for both.
    a.click("#freeze-button")
    a.fill("#snapshot-message", "both edits")
    a.click("#confirm-freeze")
    wait_for(lambda: b.locator("#dirty-dot").count() == 0, "B sees the snapshot", 20)
    wait_for(lambda: "both edits" in b.inner_text("#explorer-pane"), "B's snapshot list has it")
    # The file A has open shows as open for B.
    wait_for(lambda: b.locator("#explorer [title^='Open by']").count() > 0, "B sees which file is open")
    # B leaves: A sees one person at once.
    t = time.time()
    b.close(run_before_unload=True)
    wait_for(lambda: a.inner_text("#people-count").startswith("1"), "A sees B gone", 15)
    log(f"B gone after {time.time() - t:.1f}s")
    browser.close()
finish(errors)
