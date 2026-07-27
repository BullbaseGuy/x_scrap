from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any

from state_model import StateError, TaskState, load_json_yaml, required_task_files


def _safe_task_dir(root: Path, state_path: str, task_id: str) -> Path:
    relative = PurePosixPath(state_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] != ("docs", "implementation")
        or relative.name != "task_state.yaml"
        or len(relative.parts) != 4
        or relative.parts[2] != task_id
    ):
        raise StateError(f"unsafe canonical state_path for {task_id}: {state_path}")
    return root / Path(*relative.parts[:-1])


def validate_task_dir(task_dir: Path) -> dict[str, Any]:
    data = load_json_yaml(task_dir / "task_state.yaml")
    state = TaskState.from_mapping(data)
    missing = [path.as_posix() for path in required_task_files(task_dir, state) if not path.is_file()]
    return {
        "task_id": state.task_id,
        "status": state.status,
        "branch": state.working_branch,
        "pull_request": state.pull_request,
        "current_stage": state.current_stage,
        "missing": missing,
        "errors": ["missing required file(s): " + ", ".join(missing)] if missing else [],
    }


def validate_active_tasks(root: Path) -> dict[str, Any]:
    index = load_json_yaml(root / "docs/implementation/ACTIVE_TASKS.yaml")
    if set(index) != {"schema_version", "tasks"}:
        raise StateError("ACTIVE_TASKS accepts only schema_version and tasks")
    if index["schema_version"] != 1 or not isinstance(index["tasks"], list):
        raise StateError("invalid ACTIVE_TASKS schema")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    results: list[dict[str, Any]] = []
    for entry in index["tasks"]:
        if not isinstance(entry, dict):
            raise StateError("ACTIVE_TASKS entries must be objects")
        task_id = entry.get("task_id")
        state_path = entry.get("state_path")
        if not isinstance(task_id, str) or not task_id:
            raise StateError("ACTIVE_TASKS task_id must be non-empty")
        if not isinstance(state_path, str) or not state_path:
            raise StateError(f"state_path missing for {task_id}")
        if task_id in seen_ids or state_path in seen_paths:
            raise StateError(f"duplicate task or state path: {task_id}")
        seen_ids.add(task_id)
        seen_paths.add(state_path)
        result = validate_task_dir(_safe_task_dir(root, state_path, task_id))
        for key in ("status", "branch", "pull_request", "current_stage"):
            if entry.get(key) != result[key]:
                result["errors"].append(f"task index {key} differs from canonical state")
        if result["task_id"] != task_id:
            result["errors"].append("task index and canonical state task_id differ")
        results.append(result)
    errors = [error for result in results for error in result["errors"]]
    return {"status": "PASS" if not errors else "FAIL", "tasks": results, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-active", action="store_true")
    group.add_argument("--task-dir", type=Path)
    parser.add_argument("--no-git", action="store_true", help="accepted for template compatibility")
    parser.add_argument("--output", type=Path, default=Path("devflow-state-result.json"))
    args = parser.parse_args()
    try:
        result = (
            validate_active_tasks(Path("."))
            if args.all_active
            else _single_result(validate_task_dir(args.task_dir))
        )
    except (StateError, OSError) as exc:
        result = {"status": "FAIL", "tasks": [], "errors": [str(exc)]}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


def _single_result(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS" if not task["errors"] else "FAIL",
        "tasks": [task],
        "errors": task["errors"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
