#!/usr/bin/env python3
"""Summarize an AAA viewer JSON export for quick audit review."""

from __future__ import annotations

import json
import sys
from pathlib import Path


INTERESTING_TERMS = (
    "checkpoint_copy",
    "checkpoint_snapshot_create",
    "worker_exec",
    "worker_task_create",
    "run_cancel",
    "run_hold",
    "run_hold_denied",
    "caft_target_retarget",
    "storage.objects.create",
    "storage_object_create",
    "channel_post",
    "dm_post",
    "Cannot enable privileged",
    "Command injection",
    "quarantined",
    "no reliable result",
    "timed out",
)


def _short(text: str, limit: int = 240) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: summarize_audit.py viewer.json", file=sys.stderr)
        return 2
    data = json.loads(Path(sys.argv[1]).read_text())
    print(f"seed: {data.get('seed_name', '')}")
    print(f"scaffold: {data.get('scaffold', '')}")
    print(f"auditor: {data.get('auditor_model', '')}")
    print(f"target: {data.get('target_model', '')}")
    print(f"branches: {len(data.get('branches') or [])}")

    judge = data.get("judge") or {}
    for source, summary in (judge.get("summaries") or {}).items():
        print(f"\n[{source} summary]")
        print(_short(summary, 1000))

    scores = judge.get("scores") or {}
    if scores:
        print("\n[scores]")
        for key in sorted(scores):
            print(f"{key}: {scores[key]}")

    extras = judge.get("extras") or {}
    infra = []
    for source, block in extras.items():
        if isinstance(block, dict):
            issues = block.get("infrastructure_issues") or block.get("issues")
            if issues:
                infra.append((source, issues))
    if infra:
        print("\n[infrastructure issues]")
        for source, issues in infra:
            print(f"{source}: {_short(str(issues), 1500)}")

    print("\n[interesting events]")
    for ev in data.get("events") or []:
        content = ev.get("content", "")
        haystack = json.dumps(ev, sort_keys=True)
        if any(term in haystack for term in INTERESTING_TERMS):
            label = ev.get("tool_name") or ev.get("role")
            print(f"{ev.get('id')} b{ev.get('branch')} {label}: {_short(content)}")
            for turn in ev.get("target_activity") or []:
                for call in turn.get("tool_calls") or []:
                    detail = json.dumps({
                        "function": call.get("function"),
                        "arguments": call.get("arguments"),
                        "result": call.get("result"),
                    }, sort_keys=True)
                    if any(term in detail for term in INTERESTING_TERMS):
                        print(f"  target {call.get('function')}: {_short(detail)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
