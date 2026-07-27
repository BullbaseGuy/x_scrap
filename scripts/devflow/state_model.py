from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TASK_STATUSES = {
    "PLANNING",
    "READY",
    "RUNNING",
    "VERIFYING",
    "WAITING_HUMAN",
    "BLOCKED",
    "POST_MERGE_BLOCKED",
    "DONE",
}
EXECUTION_STATUSES = {"PENDING", "RUNNING", "COMPLETED", "FAILED", "BLOCKED"}
ACCEPTANCE_STATUSES = {"PENDING", "PASS", "REVIEW_REQUIRED", "FAIL"}
SECURITY_STATUSES = {"PENDING", "PASS", "BLOCKED", "FAIL"}
POST_MERGE_STATUSES = {"PENDING", "RUNNING", "PASS", "FAIL"}


class StateError(ValueError):
    pass


def load_json_yaml(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot load JSON-compatible YAML: {path}") from exc
    if not isinstance(value, dict):
        raise StateError(f"state root must be an object: {path}")
    return value


def _require(data: dict[str, Any], key: str, expected: type) -> Any:
    value = data.get(key)
    if not isinstance(value, expected):
        raise StateError(f"{key} must be {expected.__name__}")
    return value


def _optional_positive_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StateError(f"{key} must be a positive integer or null")
    return value


def stage_number(stage: str) -> int:
    if len(stage) != 3 or not stage.startswith("W") or not stage[1:].isdigit():
        raise StateError(f"invalid stage: {stage}")
    return int(stage[1:])


@dataclass(frozen=True)
class TaskState:
    task_id: str
    status: str
    execution_status: str
    acceptance_status: str
    security_status: str
    working_branch: str
    pull_request: int | None
    current_stage: str
    last_completed_stage: str | None
    post_merge_status: str
    human_required: bool

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TaskState":
        if _require(data, "schema_version", int) != 2:
            raise StateError("task schema_version must equal 2")
        _require(data, "state_revision", int)
        task_id = _require(data, "task_id", str).strip()
        title = _require(data, "title", str).strip()
        status = _require(data, "status", str)
        execution_status = _require(data, "execution_status", str)
        acceptance = _require(data, "acceptance", dict)
        acceptance_domain = _require(acceptance, "domain", str).strip()
        acceptance_status = _require(acceptance, "status", str)
        security_status = _require(data, "security_status", str)
        working_branch = _require(data, "working_branch", str).strip()
        pull_request = _optional_positive_int(data, "pull_request")
        current_stage = _require(data, "current_stage", str)
        current_number = stage_number(current_stage)
        last_completed = data.get("last_completed_stage")
        if last_completed is not None:
            if not isinstance(last_completed, str):
                raise StateError("last_completed_stage must be a string or null")
            completed_number = stage_number(last_completed)
            if status == "DONE" and completed_number != current_number:
                raise StateError("DONE requires last_completed_stage == current_stage")
            if status != "DONE" and completed_number >= current_number:
                raise StateError("last_completed_stage must precede current_stage")
        elif status == "DONE":
            raise StateError("DONE requires last_completed_stage")

        post_merge = _require(data, "post_merge", dict)
        post_merge_status = _require(post_merge, "status", str)
        human_gate = _require(data, "human_gate", dict)
        human_required = _require(human_gate, "required", bool)
        if human_required:
            for key in ("reason", "minimum_action", "resume_from"):
                if not isinstance(human_gate.get(key), str) or not human_gate[key].strip():
                    raise StateError(f"human_gate.{key} is required")
        _require(data, "notification", dict)
        _require(data, "gate_results", dict)
        _require(data, "retry_budget", dict)
        for key in (
            "base_sha_at_start",
            "last_product_commit_sha",
            "last_successful_step",
            "next_action",
            "updated_at_utc",
        ):
            _require(data, key, str)

        if not task_id or not title or not acceptance_domain or not working_branch:
            raise StateError("identity, title, acceptance domain, and branch must not be empty")
        if status not in TASK_STATUSES:
            raise StateError(f"invalid task status: {status}")
        if execution_status not in EXECUTION_STATUSES:
            raise StateError(f"invalid execution_status: {execution_status}")
        if acceptance_status not in ACCEPTANCE_STATUSES:
            raise StateError(f"invalid acceptance status: {acceptance_status}")
        if security_status not in SECURITY_STATUSES:
            raise StateError(f"invalid security_status: {security_status}")
        if post_merge_status not in POST_MERGE_STATUSES:
            raise StateError(f"invalid post_merge status: {post_merge_status}")
        if status == "DONE":
            required = {
                "execution_status": execution_status == "COMPLETED",
                "acceptance": acceptance_status == "PASS",
                "security": security_status == "PASS",
                "post_merge": post_merge_status == "PASS",
                "human_gate": not human_required,
            }
            failed = [name for name, ok in required.items() if not ok]
            if failed:
                raise StateError("DONE invariant failed: " + ", ".join(failed))

        return cls(
            task_id=task_id,
            status=status,
            execution_status=execution_status,
            acceptance_status=acceptance_status,
            security_status=security_status,
            working_branch=working_branch,
            pull_request=pull_request,
            current_stage=current_stage,
            last_completed_stage=last_completed,
            post_merge_status=post_merge_status,
            human_required=human_required,
        )


def required_task_files(task_dir: Path, state: TaskState) -> list[Path]:
    required = [
        task_dir / "00_contract.md",
        task_dir / "01_master_plan.md",
        task_dir / "task_state.yaml",
        task_dir / "STATUS.md",
        task_dir / "HANDOFF.md",
        task_dir / "DECISIONS.md",
        task_dir / f"{state.current_stage}_plan.md",
    ]
    if state.last_completed_stage is not None:
        for number in range(stage_number(state.last_completed_stage) + 1):
            stage = f"W{number:02d}"
            required.extend([task_dir / f"{stage}_plan.md", task_dir / f"{stage}_result.md"])
    if state.status == "DONE":
        required.append(task_dir / "FINAL_REPORT.md")
    return required
