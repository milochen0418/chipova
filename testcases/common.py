"""Helpers shared by the Playwright suites (imported by each run_test.py)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:3000").rstrip("/")
# The Reflex backend: the same origin behind re-ddns, another port in a local run.
BACKEND_URL = os.environ.get("BACKEND_URL", BASE_URL).rstrip("/")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", Path(__file__).resolve().parent / "output"))
HEADLESS = os.environ.get("HEADLESS", "1").strip().lower() not in {"0", "false", "no", "off"}
SLOWMO = int(os.environ.get("PW_SLOWMO_MS", "0") or 0)
TIMEOUT = int(os.environ.get("PW_TIMEOUT_MS", "30000") or 30000)
SECRET = os.environ.get("DDNS_AUTH_SECRET", "")
_T0 = time.time()


def log(*args) -> None:
    print(f"[{time.time() - _T0:6.2f}]", *args, flush=True)


def launch(pw: Playwright) -> Browser:
    args = []
    if BASE_URL.startswith("https://") and ".reflex-ddns.com" in BASE_URL:
        # A Mac may resolve *.reflex-ddns.com to the Docker-internal IP.
        args.append("--host-resolver-rules=MAP *.reflex-ddns.com 127.0.0.1")
    return pw.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, args=args)


def sign_in_cookie(email: str, name: str) -> dict:
    """The platform's sign-in cookie for ``email`` (what Relack sets), signed with the test secret."""
    import jwt

    token = jwt.encode({"email": email, "name": name, "approved": True, "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    host = re.sub(r"^https?://", "", BASE_URL).split(":")[0].split("/")[0]
    return {"name": "ddns_auth", "value": token, "domain": host, "path": "/"}


def new_page(browser: Browser, errors: list[str], who: str, *, email: str = "", width: int = 1500, height: int = 920) -> Page:
    """A browser tab of its own (its own guest, or signed in as ``email``)."""
    ctx = browser.new_context(viewport={"width": width, "height": height}, ignore_https_errors=True, accept_downloads=True)
    if email:
        if not SECRET:
            raise SystemExit("signing in needs DDNS_AUTH_SECRET (the runner sets one)")
        ctx.add_cookies([sign_in_cookie(email, who)])
    page = ctx.new_page()
    page.set_default_timeout(TIMEOUT)

    def on_console(msg) -> None:  # noqa: ANN001
        if msg.type == "error" and "Outdated Optimize Dep" not in msg.text and "Failed to load resource" not in msg.text:
            errors.append(f"[{who}] console: {msg.text}")

    def on_error(err) -> None:  # noqa: ANN001
        # Reflex's own window.onerror trips on error events without an error object (a Monaco
        # worker stopped while loading): not the page's fault.
        if "at window.onerror" in (getattr(err, "stack", "") or ""):
            return
        if str(err) == "Canceled":
            return
        errors.append(f"[{who}] pageerror: {err}" + (f"\n{getattr(err, 'stack', '')}" if os.environ.get("PW_STACKS") else ""))

    page.on("console", on_console)
    page.on("pageerror", on_error)
    return page


def shot(page: Page, name: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT_DIR / f"{name}.png"))


def wait_for(fn, what: str, timeout: float = 30.0) -> None:
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            if fn():
                return
        except Exception as e:  # noqa: BLE001 - keep trying until the deadline
            last = e
        time.sleep(0.25)
    raise AssertionError(f"timed out: {what}" + (f" (last error: {last})" if last else ""))


def open_home(page: Page) -> None:
    page.goto(BASE_URL + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#new-project", timeout=120000)


def new_project(page: Page, title: str = "", template: str = "digital_heartbeat") -> str:
    """Makes a project from the home page; returns its id."""
    open_home(page)
    page.click("#new-project")
    if title:
        page.fill("#new-title", title)
    page.click(f"[data-template={template}]")
    page.click("#create-project")
    page.wait_for_url(re.compile(r".*/p/[a-f0-9]{10}"), timeout=60000)
    wait_editor(page)
    return page.url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]


def open_project(page: Page, project_id: str, wait: bool = True) -> None:
    page.goto(f"{BASE_URL}/p/{project_id}", wait_until="domcontentloaded")
    if wait:
        wait_editor(page)


def wait_editor(page: Page) -> None:
    page.wait_for_selector("#editor-panel .monaco-editor", timeout=90000)
    wait_bound(page)
    wait_for(lambda: editor_text(page), "the editor shows the file", 30)


def wait_bound(page: Page) -> None:
    """Waits until the open file's editor is joined to its shared document."""
    wait_for(lambda: page.evaluate("() => { const p = document.getElementById('editor-panel'); return !!p && p.getAttribute('data-chip-bound') === p.getAttribute('data-chip-doc'); }"), "the editor joined the shared file", 30)


_EDITOR = "(() => { const p = document.getElementById('editor-panel'); if (!p || !window.monaco) return null; return monaco.editor.getEditors().find(e => p.contains(e.getContainerDomNode())) || null; })()"


def editor_text(page: Page):
    return page.evaluate(f"() => {{ const e = {_EDITOR}; return e ? e.getValue() : null }}")


def editor_position(page: Page):
    return page.evaluate(f"() => {{ const e = {_EDITOR}; const p = e && e.getPosition(); return p ? [p.lineNumber, p.column] : null }}")


def markers(page: Page) -> list:
    return page.evaluate(f"() => {{ const e = {_EDITOR}; return e ? monaco.editor.getModelMarkers({{resource: e.getModel().uri}}).map(m => [m.startLineNumber, m.severity, m.message]) : [] }}")


def set_editor_text(page: Page, text: str) -> None:
    """Replaces the open file's text as a paste would (it reaches everyone through Yjs)."""
    wait_for(lambda: page.evaluate(f"() => !!{_EDITOR} && !{_EDITOR}.getOption(monaco.editor.EditorOption.readOnly)"), "the editor is writable")
    page.evaluate(f"(t) => {{ const e = {_EDITOR}; e.executeEdits('test', [{{ range: e.getModel().getFullModelRange(), text: t }}]); }}", text)


def open_file(page: Page, path: str) -> None:
    page.click(f"#explorer [data-file='{path}']")
    wait_for(lambda: page.get_attribute("#editor-panel", "data-chip-path") == path, f"{path} is open")
    wait_bound(page)
    wait_for(lambda: editor_text(page) is not None, "its text")


def selected_run(page: Page) -> str:
    return page.get_attribute("#chip-problems", "data-run") or ""


def run_flow(page: Page, flow: str, freeze: bool = True) -> str:
    """Starts a flow from the Run menu (freezing the editors first when it asks); returns the
    new run's id once it is the one shown."""
    before = selected_run(page)
    page.click("#run-menu")
    page.click(f"[data-flow={flow}]")
    deadline = time.time() + 30
    answered = False
    while time.time() < deadline:
        if not answered and page.locator("#freeze-and-run").count():
            page.click("#freeze-and-run" if freeze else "#run-latest", timeout=10000)
            answered = True
        now = selected_run(page)
        if now and now != before:
            return now
        time.sleep(0.2)
    raise AssertionError(f"no new {flow} run was shown")


def selected_status(page: Page) -> str:
    loc = page.locator("#bottom-panel #run-output").locator("xpath=..").locator("[data-status]").first
    return loc.get_attribute("data-status") or "" if loc.count() else ""


def wait_run_end(page: Page, timeout: float = 180) -> str:
    """Waits for the run shown in the Output tab to end; returns its status."""
    page.click("[data-bottom=output]")
    end = time.time() + timeout
    status = ""
    while time.time() < end:
        status = selected_status(page)
        if status in ("SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT"):
            return status
        time.sleep(0.4)
    raise AssertionError(f"the run didn't end (last status {status!r})")


def tool(name: str, ai: str = "claude-code", **args):
    """Calls one of Chipova's AI tools as the AI Hub does (a token signed with the test secret)."""
    os.environ.setdefault("DDNS_AUTH_SECRET", SECRET)
    from reflex_ddns_auth.tools import call_token

    req = urllib.request.Request(
        f"{BACKEND_URL}/_ddns_tool/call/{name}",
        data=json.dumps({"args": args}).encode(),
        headers={"Authorization": "Bearer " + call_token(os.environ.get("SERVICE_SUBDOMAIN", "chipova"), ai), "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def backend_get(path: str, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(BACKEND_URL + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def finish(errors: list[str]) -> None:
    if errors:
        print("Page errors:\n" + "\n".join(errors[:30]))
        sys.exit(1)
    print("OK")
