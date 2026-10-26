"""The allowed status changes: a run's, an approval's, a release's.

    CREATED → QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELED | TIMED_OUT
    CREATED → CANCELED, QUEUED → CANCELED

An approval is its own machine, ``PROPOSED → APPROVED | REJECTED | EXPIRED``: a run waiting for a
person is CREATED with its approval PROPOSED, and is queued only once the approval is APPROVED.
"""

from __future__ import annotations

from chipova.domain.models import ApprovalStatus, ReleaseStatus, RunStatus


class InvalidTransition(ValueError):
    pass


RUN = {
    RunStatus.CREATED: {RunStatus.QUEUED, RunStatus.CANCELED},
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELED},
    RunStatus.RUNNING: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED, RunStatus.TIMED_OUT},
}

APPROVAL = {
    ApprovalStatus.PROPOSED: {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED},
}

RELEASE = {
    ReleaseStatus.DRAFT: {ReleaseStatus.IN_REVIEW},
    ReleaseStatus.IN_REVIEW: {ReleaseStatus.APPROVED, ReleaseStatus.REJECTED, ReleaseStatus.DRAFT},
    ReleaseStatus.APPROVED: {ReleaseStatus.FOUNDRY_READY, ReleaseStatus.DRAFT},
    ReleaseStatus.REJECTED: {ReleaseStatus.DRAFT},
}


def check(machine: dict, old, new) -> None:
    if new not in machine.get(old, set()):
        raise InvalidTransition(f"{getattr(old, 'value', old)} → {getattr(new, 'value', new)} is not allowed")


def check_run(old: RunStatus, new: RunStatus, approval: ApprovalStatus = ApprovalStatus.NONE) -> None:
    check(RUN, old, new)
    if old == RunStatus.CREATED and new == RunStatus.QUEUED and approval not in (ApprovalStatus.NONE, ApprovalStatus.APPROVED):
        raise InvalidTransition(f"the run waits for a person to approve it (approval {approval.value})")
