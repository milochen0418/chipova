"""What shows that a project is worked on together: who is here (round, in their colour, as in
the other apps), who you are, Call everyone, an incoming call, and the page's heartbeat and
goodbye. Ported from Codoc in CAD."""

from __future__ import annotations

import reflex as rx

from chipova.components.links import backend_base
from chipova.services.call import CALLS_ENABLED, CallState
from chipova.states.ide import IdeState
from chipova.states.room import ProjectRoom
from chipova.states.ui_state import AuthState, UiState

BYE_PATH = "/_chipova/bye"
BUTTON = "px-2.5 h-8 rounded-md text-xs font-semibold flex items-center gap-1.5 transition-all whitespace-nowrap"


def face(name: rx.Var, initials: rx.Var, avatar: rx.Var, color: rx.Var, size: str = "h-7 w-7") -> rx.Component:
    """A person's circle: their picture, else their initials, ringed in their colour."""
    ring = {"borderColor": color}
    return rx.cond(
        avatar != "",
        rx.image(src=avatar, alt=name, class_name=f"{size} rounded-full border-2 object-cover bg-slate-800", style=ring),
        rx.el.span(
            initials,
            class_name=f"{size} rounded-full border-2 flex items-center justify-center text-[10px] font-bold text-white",
            style={**ring, "backgroundColor": color},
        ),
    )


def person(p) -> rx.Component:
    return rx.el.button(
        face(p["name"], p["initials"], p["avatar"], p["color"]),
        rx.el.span(
            p["name"],
            class_name="absolute top-full mt-1.5 left-1/2 -translate-x-1/2 px-2 py-1 rounded bg-slate-950 text-slate-100 text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-30",
        ),
        on_click=rx.call_script("window._chipFollow && window._chipFollow(" + p["id"].to_string() + ")"),
        type="button",
        title=p["name"],
        custom_attrs={"data-name": p["name"]},
        class_name="chip-person group relative shrink-0 rounded-full hover:z-10 hover:scale-110 transition-transform",
    )


def presence() -> rx.Component:
    return rx.el.div(
        rx.el.div(rx.foreach(ProjectRoom.people, person), class_name="flex items-center -space-x-2"),
        rx.el.span(
            ProjectRoom.people_count.to(str) + " here",
            id="people-count",
            class_name="hidden xl:inline text-xs text-slate-400 whitespace-nowrap",
        ),
        id="presence",
        class_name="flex items-center gap-2 min-w-0",
    )


def identity() -> rx.Component:
    """Who you are here, and signing in or out (with reflex_ddns_auth)."""
    me = UiState.me
    mine = rx.el.div(
        face(me["name"], me["initials"], me["avatar"], rx.cond(me["color"] != "", me["color"], "#14b8a6"), size="h-7 w-7"),
        rx.el.span(me["name"], id="me-name", class_name="hidden lg:inline text-sm font-medium text-slate-200 max-w-[9rem] truncate"),
        class_name="flex items-center gap-2",
    )
    if AuthState is None:
        return mine
    link = "px-2 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap"
    return rx.el.div(
        mine,
        rx.cond(
            AuthState.is_logged_in,
            rx.el.a("Logout", href=AuthState.logout_url, class_name=f"{link} text-slate-400 hover:text-rose-400 hover:bg-rose-950/40"),
            rx.el.a("Login", href=AuthState.login_url, class_name=f"{link} text-white bg-teal-700 hover:bg-teal-600"),
        ),
        class_name="flex items-center gap-1.5",
    )


def call_button() -> rx.Component:
    if not CALLS_ENABLED:
        return rx.fragment()
    return rx.cond(
        ProjectRoom.call_count > 0,
        rx.el.button(
            rx.icon("phone-call", class_name="w-3.5 h-3.5"),
            rx.el.span("Join call · ", ProjectRoom.call_count),
            on_click=CallState.join_call,
            id="call-join",
            title="Join the call of the people in this project",
            class_name=f"{BUTTON} bg-emerald-600 hover:bg-emerald-500 text-white shadow",
        ),
        rx.el.button(
            rx.icon("phone", class_name="w-3.5 h-3.5"),
            rx.el.span("Call everyone", class_name="hidden 2xl:inline"),
            on_click=CallState.join_call,
            id="call-everyone",
            title="Call everyone in this project",
            aria_label="Call everyone",
            class_name=f"{BUTTON} bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700",
        ),
    )


def incoming_call() -> rx.Component:
    if not CALLS_ENABLED:
        return rx.fragment()
    me = UiState.me["user"]
    rung = (
        (ProjectRoom.call_ringing_from != "")
        & ProjectRoom.call_invited.contains(me)
        & ~ProjectRoom.call_responded.contains(me)
        & ~IdeState.missing
    )
    round_button = "p-2.5 rounded-full flex cursor-pointer border-0"
    return rx.cond(
        rung,
        rx.el.div(
            rx.el.div(
                rx.icon("phone-incoming", class_name="h-5 w-5 text-white"),
                class_name="h-10 w-10 rounded-full bg-emerald-500 flex items-center justify-center shrink-0 animate-pulse",
            ),
            rx.el.div(
                rx.el.span("Incoming call", class_name="text-[11px] font-semibold uppercase tracking-wider text-emerald-400"),
                rx.el.span(ProjectRoom.call_ringing_from, class_name="text-sm font-bold text-slate-100 truncate"),
                rx.el.span("is calling everyone in this project", class_name="text-xs text-slate-400"),
                class_name="flex flex-col min-w-0 flex-1",
            ),
            rx.el.button(
                rx.icon("phone-off", class_name="h-4 w-4"),
                on_click=CallState.decline_call,
                title="Decline",
                aria_label="Decline",
                class_name=f"{round_button} bg-rose-950 text-rose-400 hover:bg-rose-900",
            ),
            rx.el.button(
                rx.icon("phone", class_name="h-4 w-4"),
                on_click=CallState.join_call,
                title="Accept",
                aria_label="Accept",
                class_name=f"{round_button} bg-emerald-600 text-white hover:bg-emerald-500",
            ),
            role="alertdialog",
            aria_label="Incoming call",
            class_name="fixed bottom-6 right-4 sm:right-6 z-[1001] w-[min(21rem,calc(100vw-2rem))] flex items-center gap-3 p-3 rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl",
        ),
    )


_CALL_HEARTBEAT_JS = """
if (window.__chipCallHb) clearInterval(window.__chipCallHb);
window.__chipCallHb = setInterval(function () {
    var el = document.getElementById('call-heartbeat-trigger');
    if (!el) { clearInterval(window.__chipCallHb); window.__chipCallHb = null; return; }
    el.click();
}, 3000);
"""


@rx.memo
def call_keepalive() -> rx.Component:
    """While in a call, keep its heartbeat going on every page."""
    return rx.cond(
        CallState.current_room != "",
        rx.el.button(
            id="call-heartbeat-trigger",
            on_click=CallState.heartbeat,
            on_mount=rx.call_script(_CALL_HEARTBEAT_JS),
            tab_index=-1,
            aria_hidden="true",
            class_name="sr-only",
        ),
    )


_PRESENCE_JS = f"""
if (window.__chipPing) clearInterval(window.__chipPing);
window.__chipPing = setInterval(function () {{
    var el = document.getElementById('chip-ping');
    if (!el) {{ clearInterval(window.__chipPing); window.__chipPing = null; return; }}
    el.click();
}}, 5000);
if (!window.__chipBye) {{
    // Closing or reloading the tab: the others stop seeing it at once. A beacon, because a
    // websocket message doesn't get out of a page that is going away; to the backend's address
    // the page put on the button, with the tab's token as Reflex keeps it.
    window.__chipBye = function () {{
        var el = document.getElementById('chip-ping');
        var token = window.sessionStorage.getItem('token');
        if (!el || !token || !navigator.sendBeacon) return;
        try {{
            var url = new URL('{BYE_PATH}', el.dataset.backend);
            navigator.sendBeacon(url.toString(), JSON.stringify({{ token: token }}));
        }} catch (e) {{}}
    }};
    window.addEventListener('pagehide', window.__chipBye);
}}
"""


def page_hooks() -> rx.Component:
    """Still here: a ping every 5 s keeps this tab among the people in the project."""
    return rx.el.button(
        id="chip-ping",
        on_click=IdeState.ping,
        on_mount=rx.call_script(_PRESENCE_JS),
        custom_attrs={"data-backend": backend_base()},
        tab_index=-1,
        aria_hidden="true",
        class_name="sr-only",
    )
