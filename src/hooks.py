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
        if not data.log or not data.log.samples:
            return
        try:
            log_id = data.eval_id or ""
            out = write_transcript_and_index(data.log, _DATA_DIR, log_id=log_id)
            print(f"[petri_viewer_dump] wrote {out}")
        except Exception as e:
            print(f"[petri_viewer_dump] failed: {e}")
