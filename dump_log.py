"""Manual CLI: convert .eval log(s) into viewer/public/data/<id>.json + index.json.

Usage:
    uv run python dump_log.py              # dump newest .eval in logs/
    uv run python dump_log.py LOG_PATH     # dump a specific log
    uv run python dump_log.py --all        # backfill every .eval in logs/

Normally unnecessary — the petri_viewer_dump hook does this automatically after each eval.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from inspect_ai.log import read_eval_log  # noqa: E402

from transcript import rebuild_index, write_transcript_and_index  # noqa: E402

REPO = Path(__file__).parent
LOGS_DIR = REPO / "logs"
DATA_DIR = REPO / "viewer" / "public" / "data"


def _all_logs() -> list[Path]:
    return sorted(LOGS_DIR.glob("*.eval"), key=lambda p: p.stat().st_mtime, reverse=True)


def _dump_one(log_path: Path) -> Path:
    log = read_eval_log(str(log_path))
    out = write_transcript_and_index(log, DATA_DIR, log_id=log_path.stem)
    print(f"wrote {out.relative_to(REPO)}")
    return out


def main() -> None:
    args = sys.argv[1:]
    if args == ["--all"]:
        logs = _all_logs()
        if not logs:
            print(f"No .eval files in {LOGS_DIR}")
            return
        for p in logs:
            try:
                _dump_one(p)
            except Exception as e:
                print(f"skipped {p.name}: {e}")
        rebuild_index(DATA_DIR)
        print(f"rebuilt {(DATA_DIR / 'index.json').relative_to(REPO)} ({len(logs)} logs)")
        return

    if args:
        log_path = Path(args[0])
    else:
        logs = _all_logs()
        if not logs:
            raise FileNotFoundError(f"No .eval files in {LOGS_DIR}")
        log_path = logs[0]
    _dump_one(log_path)


if __name__ == "__main__":
    main()
