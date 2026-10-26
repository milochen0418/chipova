"""No internet, only the network to Chipova (the blueprint's LAN-first): every request to another
host is blocked, and two people still open the editor, type at once and see each other's carets.
Nothing on the page even tries to reach another host."""

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BACKEND_URL, BASE_URL, editor_text, finish, launch, log, new_page, new_project, open_project, shot, wait_for  # noqa: E402

LOCAL = {urlparse(BASE_URL).hostname, urlparse(BACKEND_URL).hostname, "localhost", "127.0.0.1"}
blocked: list[str] = []


def cut_off(page) -> None:  # noqa: ANN001
    def route(r) -> None:  # noqa: ANN001
        host = urlparse(r.request.url).hostname
        if r.request.url.startswith(("data:", "blob:")) or host in LOCAL:
            r.continue_()
        else:
            blocked.append(r.request.url)
            r.abort("internetdisconnected")

    page.context.route(re.compile(".*"), route)


def caret(page, where: str) -> None:  # noqa: ANN001
    page.evaluate(
        "(where) => { const p = document.getElementById('editor-panel'); const e = monaco.editor.getEditors().find(x => p.contains(x.getContainerDomNode()));"
        " const m = e.getModel(); e.setPosition(where === 'end' ? m.getPositionAt(m.getValueLength()) : {lineNumber: 1, column: 1}); e.focus(); }",
        where,
    )


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    a = new_page(browser, errors, "A")
    b = new_page(browser, errors, "B")
    cut_off(a)
    cut_off(b)
    pid = new_project(a, "Offline")
    open_project(b, pid)
    monaco_from = a.evaluate("() => [...document.scripts].map(s => s.src).filter(s => s.includes('/vs/'))")
    log("Monaco from:", monaco_from[:2])
    assert monaco_from and all("/_chipova/monaco/" in s for s in monaco_from), monaco_from
    a.locator("#editor-panel .monaco-editor").click()
    b.locator("#editor-panel .monaco-editor").click()
    caret(a, "start")
    caret(b, "end")
    for ca, cb in zip("// lan A ", " // lan B"):
        a.keyboard.type(ca)
        b.keyboard.type(cb)
    wait_for(lambda: editor_text(a) == editor_text(b), "the same text in both", 15)
    text = editor_text(a)
    assert text.startswith("// lan A ") and text.rstrip().endswith("// lan B"), text[:40] + " … " + text[-30:]
    wait_for(lambda: a.locator(".yRemoteSelectionHead").count() > 0, "A sees B's caret")
    shot(a, "01_offline")
    log("co-editing without internet: ok")
    browser.close()
if blocked:
    errors.append("the page tried to reach other hosts: " + ", ".join(sorted(set(blocked))[:10]))
finish(errors)
