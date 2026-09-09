"""Budget ledger: every provider request is reserved durably, under a file lock, before it is sent."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "logs/judge-calibration/ledger.json"
ALLOCATIONS = {"smoke": 10, "baseline": 422, "awareness": 223, "realism": 153, "applicability": 120, "integration": 390, "petri": 190, "phase2": 600}


class BudgetExhausted(RuntimeError):
    """The requested reservation would exceed the allocation cap."""


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    """Replace the file in one rename so an interruption never leaves a torn state file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".state-", delete=False) as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temp = Path(stream.name)
    temp.replace(path)


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path):
    path = Path(path)
    if not path.exists():
        atomic_json(path, {"allocations": dict(ALLOCATIONS), "entries": []})
    data = json.loads(path.read_text())
    if set(data) != {"allocations", "entries"} or not isinstance(data["entries"], list):
        raise ValueError(f"Malformed ledger: {path}")
    return data


def usage(path=LEDGER):
    """Per-allocation cap/used/remaining; creates the ledger with zero usage if missing."""
    with locked(path):
        data = _read(path)
    used = {name: 0 for name in data["allocations"]}
    for entry in data["entries"]:
        used[entry["allocation"]] = used.get(entry["allocation"], 0) + entry["n"]
    return {name: {"cap": cap, "used": used.get(name, 0), "remaining": cap - used.get(name, 0)}
            for name, cap in data["allocations"].items()}


def reserve(allocation, run_id, n=1, path=LEDGER, note=None):
    """Append a reservation or raise BudgetExhausted. Nothing is ever released."""
    if not isinstance(n, int) or n < 1:
        raise ValueError("Reserve a positive integer number of requests")
    with locked(path):
        data = _read(path)
        if allocation not in data["allocations"]:
            raise ValueError(f"Unknown allocation {allocation!r}; expected one of {sorted(data['allocations'])}")
        used = sum(e["n"] for e in data["entries"] if e["allocation"] == allocation)
        cap = data["allocations"][allocation]
        if used + n > cap:
            raise BudgetExhausted(f"Allocation {allocation!r} has {cap - used} of {cap} left; refused {n}")
        entry = {"seq": len(data["entries"]) + 1, "allocation": allocation, "run_id": run_id, "n": n, "reserved_at": now()}
        if note:
            entry["note"] = note
        data["entries"].append(entry)
        atomic_json(path, data)
    return entry


def status_text(path=LEDGER):
    rows = usage(path)
    width = max(len(name) for name in rows)
    lines = [f"{'allocation':<{width}}  used  cap  remaining"]
    for name, row in rows.items():
        lines.append(f"{name:<{width}}  {row['used']:>4}  {row['cap']:>3}  {row['remaining']:>9}")
    total_used = sum(r["used"] for r in rows.values())
    total_cap = sum(r["cap"] for r in rows.values())
    lines.append(f"{'total':<{width}}  {total_used:>4}  {total_cap:>3}  {total_cap - total_used:>9}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status"])
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    args = parser.parse_args()
    print(status_text(args.ledger))
