"""Who may do what (AC-09): someone without access to a private project is refused by the page,
the REST API, the co-editing socket and download links, and each refusal is audited; a viewer
reads but can't edit or run."""

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from playwright.sync_api import sync_playwright  # noqa: E402

from common import BACKEND_URL, backend_get, editor_text, finish, launch, log, new_page, new_project, open_project, run_flow, shot, wait_for, wait_run_end  # noqa: E402

HOME = Path(os.environ["CHIPOVA_HOME"])
ALICE, BOB = "alice@example.com", "bob@example.com"


def bob_socket_code(page, doc: str, ticket: str) -> int:
    """Opens the co-editing socket from Bob's page; returns how the server closed it."""
    url = BACKEND_URL.replace("http", "ws", 1) + f"/_chipova/yjs/{doc}?t={ticket}"
    return page.evaluate(
        "(url) => new Promise(ok => { const ws = new WebSocket(url); ws.binaryType = 'arraybuffer';"
        " ws.onclose = e => ok(e.code); setTimeout(() => ok(-1), 8000); })",
        url,
    )


errors: list[str] = []
with sync_playwright() as pw:
    browser = launch(pw)
    alice = new_page(browser, errors, "Alice", email=ALICE)
    bob = new_page(browser, errors, "Bob", email=BOB)
    pid = new_project(alice, "Private design")
    run_flow(alice, "rtl_sim")
    assert wait_run_end(alice) == "SUCCEEDED"
    alice.click("[data-view=settings]")
    alice.select_option("#link-access", "none")
    wait_for(lambda: alice.locator("#link-access").input_value() == "none", "private")
    from chipova.services import api, artifacts, collab  # noqa: E402 — the app's own signing, with its secret

    db = sqlite3.connect(HOME / "chipova.db")
    run_id, art_id = db.execute("select run_id, id from artifacts where kind = 'vcd' order by created_at desc limit 1").fetchone()
    file_id = db.execute("select id from files where project_id = ? and path = 'rtl/heartbeat.v'", (pid,)).fetchone()[0]
    # The page.
    open_project(bob, pid, wait=False)
    bob.wait_for_selector("#gone")
    assert "private" in bob.inner_text("#gone")
    # The REST API, with Bob's own token.
    from chipova.services.actors import Actor  # noqa: E402

    token = api.make_token(Actor(BOB, "Bob", email=BOB))
    code, body = backend_get(f"/api/runs/{run_id}/artifacts", {"Authorization": f"Bearer {token}"})
    assert code == 403, (code, body)
    # The co-editing socket, with a genuine ticket for Bob.
    assert bob_socket_code(bob, f"{pid}-{file_id}", collab.make_ticket(BOB, "Bob", pid)) == 4403
    # A download link signed for Bob.
    code, _ = backend_get(artifacts.link(art_id, BOB))
    assert code == 403, code
    denied = db.execute("select action from audit where project_id = ? and decision = 'denied' and actor = ?", (pid, BOB)).fetchall()
    log("audited refusals:", [a for (a,) in denied])
    assert {"view", "collab.connect", "artifact.read"} <= {a for (a,) in denied}, denied
    # Alice makes Bob a viewer: he reads, but can't edit or run.
    alice.fill("#new-member", BOB)
    alice.select_option("select:near(#new-member)", "viewer")
    alice.click("#add-member")
    wait_for(lambda: BOB in alice.inner_text("#members"), "Bob is a member")
    open_project(bob, pid)
    assert "viewer" in bob.inner_text("#my-role").lower()
    text = editor_text(bob)
    bob.locator("#editor-panel .monaco-editor").click()
    bob.keyboard.type("// bob was here")
    assert editor_text(bob) == text, "a viewer typed into the file"
    assert bob.locator("#run-menu").is_disabled() and bob.locator("#freeze-button").is_disabled()
    code, _ = backend_get(artifacts.link(art_id, BOB))
    assert code == 200, code
    shot(bob, "01_viewer")
    browser.close()
finish(errors)
