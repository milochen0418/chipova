"""Who may do what in a project.

    viewer    read files, runs and reports; download artifacts; comment
    reviewer  a viewer who also approves: reviews of revisions, waivers, releases
    editor    a viewer who also works: edits files, freezes snapshots, starts and stops runs,
              accepts or rejects AI proposals, approves runs an AI asked for, asks for a release
    owner     everything, also the project's settings, members and deleting it

Someone can hold several roles at once (a reviewer member of a project anyone may edit is an
editor too): what they may do is everything any of their roles may. An approver is never the one
who asked (see :mod:`chipova.services.releases`), and an AI agent acts with the roles of the
person it works for, but never edits files directly, approves, waives or releases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from chipova.domain.models import LinkAccess, Role

VIEW = "view"
COMMENT = "comment"
DOWNLOAD = "download"
EDIT = "edit"
SNAPSHOT = "snapshot"
RUN = "run"
DECIDE_PROPOSAL = "decide_proposal"
APPROVE_RUN = "approve_run"
REQUEST_RELEASE = "request_release"
REVIEW = "review"
APPROVE_WAIVER = "approve_waiver"
APPROVE_RELEASE = "approve_release"
MANAGE = "manage"

_VIEWER = {VIEW, COMMENT, DOWNLOAD}
_REVIEWER = _VIEWER | {REVIEW, APPROVE_WAIVER, APPROVE_RELEASE}
_EDITOR = _VIEWER | {EDIT, SNAPSHOT, RUN, DECIDE_PROPOSAL, APPROVE_RUN, REQUEST_RELEASE}
_OWNER = _REVIEWER | _EDITOR | {MANAGE}

ALLOWED: dict[Role, set[str]] = {
    Role.VIEWER: _VIEWER,
    Role.REVIEWER: _REVIEWER,
    Role.EDITOR: _EDITOR,
    Role.OWNER: _OWNER,
}

# What an AI agent may never do, whatever the roles of the person it works for: it proposes
# changes instead of editing, and people decide.
NEVER_FOR_AGENTS = {EDIT, DECIDE_PROPOSAL, APPROVE_RUN, REVIEW, APPROVE_WAIVER, APPROVE_RELEASE, MANAGE}

_RANK = {Role.VIEWER: 0, Role.REVIEWER: 1, Role.EDITOR: 2, Role.OWNER: 3}


@dataclass(frozen=True)
class Access:
    """What one person (or the AI working for them) may do in one project."""

    roles: frozenset[Role] = frozenset()
    agent: bool = False

    def can(self, action: str) -> bool:
        if self.agent and action in NEVER_FOR_AGENTS:
            return False
        return any(action in ALLOWED[r] for r in self.roles)

    @property
    def role(self) -> Role | None:
        """The role to show (the highest)."""
        return max(self.roles, key=lambda r: _RANK[r]) if self.roles else None

    @property
    def label(self) -> str:
        names = [r.value.capitalize() for r in sorted(self.roles, key=lambda r: -_RANK[r])]
        if Role.OWNER in self.roles:
            names = ["Owner"]
        return " + ".join(names) if names else "No access"


def access(member: Role | None, link: LinkAccess, agent: bool = False) -> Access:
    """A member's role, together with what the project's link gives everyone who has it."""
    roles = {r for r in (member, link_role(link)) if r is not None}
    return Access(frozenset(roles), agent)


def link_role(link: LinkAccess) -> Role | None:
    return {LinkAccess.VIEWER: Role.VIEWER, LinkAccess.EDITOR: Role.EDITOR}.get(link)


def can(roles: Iterable[Role], action: str, agent: bool = False) -> bool:
    return Access(frozenset(roles), agent).can(action)
