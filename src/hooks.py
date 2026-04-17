"""Post-eval hook: auto-dump transcripts to viewer/public/data/<id>.json and rebuild the index."""

from __future__ import annotations

from pathlib import Path

from inspect_ai.hooks import Hooks, TaskEnd, hooks

from transcript import write_transcript_and_index

_REPO = Path(__file__).resolve().parent.parent
_DATA_DIR = _REPO / "viewer" / "public" / "data"


@hooks(name="petri_viewer_dump", description="Dumps transcript JSON to viewer after each task ends.")
class PetriViewerDump(Hooks):
    async def on_task_end(self, data: TaskEnd) -> None:
        log_id = data.eval_id or ""
        log_file = data.log.location if data.log else None
        print(f"[petri_viewer_dump] on_task_end fired: eval_id={log_id} file={log_file}", flush=True)
        try:
            # Samples are a LazyList — re-read from disk to ensure full state is present.
            if log_file:
                from inspect_ai.log import read_eval_log
                log = read_eval_log(log_file)
            else:
                log = data.log
            if not log or not log.samples:
                print(f"[petri_viewer_dump] skipped: no samples in log", flush=True)
                return
            out = write_transcript_and_index(log, _DATA_DIR, log_id=log_id)
            print(f"[petri_viewer_dump] wrote {out}", flush=True)
        except Exception as e:
            import traceback
            print(f"[petri_viewer_dump] failed: {e}\n{traceback.format_exc()}", flush=True)
