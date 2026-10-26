"""The things Chipova keeps, as Pydantic models (the blueprint's section 8.1).

They are what the services return and what the REST API sends; the database rows (see
:mod:`chipova.db`) are turned into them with ``Model.from_row``. Every status is an enum, and
the allowed status changes are in :mod:`chipova.domain.machines`.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class LinkAccess(str, Enum):
    """What someone who has the project's link, but is not a member, may do."""

    NONE = "none"
    VIEWER = "viewer"
    EDITOR = "editor"


class ProjectKind(str, Enum):
    DIGITAL_ASIC = "digital_asic"
    FPGA = "fpga"
    AMS = "ams"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TIMED_OUT = "TIMED_OUT"

    @property
    def finished(self) -> bool:
        return self in FINISHED


FINISHED = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED, RunStatus.TIMED_OUT}


class ApprovalStatus(str, Enum):
    """A second state machine, apart from a run's: a run that succeeded says nothing about
    whether a person approved it."""

    NONE = "NONE"  # nothing to approve (a person asked for it)
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELED = "CANCELED"


class SignoffStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    WAIVED = "WAIVED"
    BLOCKED = "BLOCKED"


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    # Set only by a person, with every gate passed; Chipova never sets it on its own.
    FOUNDRY_READY = "FOUNDRY_READY"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class _Model(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="ignore")

    @classmethod
    def from_row(cls, row: Any) -> Any:
        data = dict(row)
        for name, field in cls.model_fields.items():
            value = data.get(name)
            if isinstance(value, str) and _is_json_field(field.annotation):
                try:
                    data[name] = json.loads(value) if value else field.get_default(call_default_factory=True)
                except ValueError:
                    data[name] = field.get_default(call_default_factory=True)
        return cls.model_validate(data)


def _is_json_field(annotation: Any) -> bool:
    text = str(annotation)
    return text.startswith(("dict", "list", "typing.Dict", "typing.List")) or "dict[" in text or "list[" in text


class ProjectSettings(_Model):
    """What a project's runs are set up with; kept in ``chipova.toml`` in the project's files,
    so it is part of every snapshot."""

    top: str = "top"
    testbench: str = ""  # the testbench's top module ("" = none)
    rtl: list[str] = Field(default_factory=list)  # RTL sources (paths); empty = every .v/.sv outside tb/
    sim: list[str] = Field(default_factory=list)  # testbench sources
    sdc: str = ""
    clock_port: str = "clk"
    clock_period_ns: float = 10.0
    pdk: str = "skywater130"  # a target of the PDK registry
    fpga_family: str = "ice40"  # ice40 | ecp5 | gowin: which Build FPGA flow
    fpga_device: str = "up5k"
    fpga_package: str = "sg48"
    fpga_pins: str = ""  # the pin file (.pcf, .lpf or .cst)
    pcf: str = ""  # the pin file's older name (iCE40 projects)
    spice: str = ""  # AMS: the top SPICE deck
    cace: str = ""  # AMS: the CACE datasheet (.yaml): the PVT corners
    schematic_tb: str = ""  # AMS: the Xschem testbench (.sch) to netlist and simulate

    @property
    def clock_mhz(self) -> float:
        return round(1000.0 / self.clock_period_ns, 3) if self.clock_period_ns > 0 else 0.0


class Project(_Model):
    id: str
    title: str
    kind: ProjectKind = ProjectKind.DIGITAL_ASIC
    template: str = ""
    owner: str = ""
    owner_name: str = ""
    link_access: LinkAccess = LinkAccess.EDITOR
    created_at: float = 0.0
    updated_at: float = 0.0
    # What AI agents may do here without a person approving first.
    ai_may_run: list[str] = Field(default_factory=lambda: ["rtl_lint", "rtl_sim"])


class Membership(_Model):
    project_id: str
    user: str
    role: Role
    added_by: str = ""
    added_at: float = 0.0


class FileEntry(_Model):
    project_id: str
    id: str
    path: str
    created_at: float = 0.0
    updated_at: float = 0.0
    updated_by: str = ""


class Revision(_Model):
    """A snapshot: the project's files frozen as they were. Its id is the hash of its source
    manifest, so the same files are the same revision."""

    id: str
    project_id: str
    git_commit: str
    source_sha: str
    parent: str = ""
    message: str = ""
    created_by: str = ""
    created_by_name: str = ""
    created_at: float = 0.0
    files: list[dict[str, Any]] = Field(default_factory=list)  # [{path, sha256, size}]


class FlowParam(_Model):
    name: str
    title: str
    kind: str = "str"  # str | int | float | bool | choice | file
    default: Any = None
    choices: list[str] = Field(default_factory=list)
    help: str = ""


class FlowDefinition(_Model):
    id: str
    version: str
    title: str
    category: str  # verify | implement | signoff | ams
    description: str = ""
    profiles: list[str] = Field(default_factory=list)
    params: list[FlowParam] = Field(default_factory=list)
    timeout: int = 600
    enabled: bool = True
    disabled_reason: str = ""


class Run(_Model):
    id: str
    project_id: str
    revision_id: str
    flow_id: str
    flow_version: str = ""
    profile_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.CREATED
    approval_status: ApprovalStatus = ApprovalStatus.NONE
    approval_by: str = ""
    approval_at: float = 0.0
    requested_by: str = ""
    requested_by_name: str = ""
    requested_via: str = "ui"  # ui | ai | api
    source_run: str = ""  # a signoff run checks the outputs of this run
    created_at: float = 0.0
    queued_at: float = 0.0
    started_at: float = 0.0
    ended_at: float = 0.0
    container: str = ""
    image: str = ""
    image_digest: str = ""
    exit_code: int | None = None
    error: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    problems: dict[str, Any] = Field(default_factory=dict)


class RunStep(_Model):
    run_id: str
    idx: int
    node: str
    title: str = ""
    status: StepStatus = StepStatus.PENDING
    started_at: float = 0.0
    ended_at: float = 0.0
    exit_code: int | None = None
    command: list[str] = Field(default_factory=list)
    command_digest: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class Artifact(_Model):
    id: str
    run_id: str
    project_id: str
    kind: str
    name: str
    sha256: str
    size: int
    created_at: float = 0.0
    access_scope: str = "project"


class Problem(_Model):
    severity: Severity
    tool: str
    step: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    code: str = ""
    message: str


class AgentAction(_Model):
    """Something an AI agent proposed (a patch), waiting for a person to decide."""

    id: str
    project_id: str
    agent: str
    on_behalf_of: str = ""
    kind: str = "patch"
    title: str = ""
    rationale: str = ""
    plan: str = ""
    base_revision: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PROPOSED
    decided_by: str = ""
    decided_by_name: str = ""
    decided_at: float = 0.0
    reason: str = ""
    applied_revision: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0


class Review(_Model):
    id: str
    project_id: str
    revision_id: str
    reviewer: str
    reviewer_name: str = ""
    status: str  # approved | changes_requested | commented
    comment: str = ""
    created_at: float = 0.0


class Comment(_Model):
    id: str
    project_id: str
    anchor_kind: str  # file | run | step | violation | layout | revision
    anchor: dict[str, Any] = Field(default_factory=dict)
    revision_id: str = ""
    author: str = ""
    author_name: str = ""
    body: str = ""
    created_at: float = 0.0
    resolved: bool = False


class Waiver(_Model):
    id: str
    project_id: str
    revision_id: str
    category: str
    rule_id: str = ""
    reason: str = ""
    requested_by: str = ""
    requested_by_name: str = ""
    approved_by: str = ""
    approved_by_name: str = ""
    status: str = "PROPOSED"  # PROPOSED | APPROVED | REJECTED
    created_at: float = 0.0
    decided_at: float = 0.0


class SignoffCheck(_Model):
    """One line of the signoff checklist of a revision, worked out from its runs."""

    category: str
    title: str
    status: SignoffStatus
    run_id: str = ""
    rule_deck: str = ""
    summary: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    waivers: list[Waiver] = Field(default_factory=list)
    required: bool = True
    why: str = ""


class Release(_Model):
    id: str
    project_id: str
    revision_id: str
    title: str = ""
    status: ReleaseStatus = ReleaseStatus.DRAFT
    requested_by: str = ""
    requested_by_name: str = ""
    created_at: float = 0.0
    runs: list[str] = Field(default_factory=list)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    manifest_sha: str = ""
    package_artifact: str = ""


class AuditEntry(_Model):
    id: int = 0
    ts: float = 0.0
    project_id: str = ""
    actor: str = ""
    actor_name: str = ""
    actor_kind: str = "human"  # human | agent | system
    action: str = ""
    target: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    decision: str = "ok"  # ok | denied | error
    detail: str = ""
