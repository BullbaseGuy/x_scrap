from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from x_scrap.security import ensure_private_directory, open_private_text, write_private_text


def write_export(
    output_dir: Path,
    *,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    coverage: dict[str, Any],
    posts: Iterable[dict[str, Any]],
) -> None:
    output_dir = ensure_private_directory(output_dir)
    post_list = list(posts)
    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "profile.json", profile)
    _write_json(output_dir / "coverage.json", coverage)
    with open_private_text(
        output_dir / "tweets.jsonl",
        encoding="utf-8",
        newline="\n",
    ) as handle:
        for post in post_list:
            handle.write(json.dumps(post, ensure_ascii=False, sort_keys=True) + "\n")
    fields = [
        "post_id",
        "created_at",
        "username",
        "text",
        "url",
        "conversation_id",
        "in_reply_to_post_id",
        "quoted_post_id",
        "reposted_post_id",
        "language",
        "is_reply",
        "is_quote",
        "is_retweet",
        "sources",
    ]
    with open_private_text(
        output_dir / "tweets.csv",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for post in post_list:
            row = dict(post)
            row["sources"] = ",".join(post.get("sources", []))
            writer.writerow(row)
    summary = f"""# X user export summary

- Job: `{manifest['job_id']}`
- User: `@{manifest['username']}`
- Posts: **{manifest['post_count']}**
- Coverage: `{coverage['status']}`
- Start: `{manifest['start_at']}`
- Cutoff: `{manifest['cutoff_at']}`

## Interpretation

The coverage status refers to content publicly retrievable through the configured X account and current search index at collection time. It does not claim recovery of deleted, protected, suspended, de-indexed, or otherwise unavailable posts.
"""
    write_private_text(output_dir / "summary.md", summary)


def _write_json(path: Path, value: Any) -> None:
    write_private_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
    )
