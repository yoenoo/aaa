"""Six parallel Modal containers; exactly the frozen 36 jobs / 108 request cap."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

import modal

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

app = modal.App("aaa-petri-full-judge-v1")
state = modal.Dict.from_name("aaa-petri-full-judge-v1-records", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.13").pip_install(
    "inspect-ai==0.3.246", "anthropic==0.116.0", "pydantic==2.13.4", "pyyaml==6.0.3",
).env({"PYTHONPATH": "/opt/aaa:/opt/aaa/src"})
for relative in ("src/awareness_v5.py", "src/awareness_v3.py", "src/judge_v4.py",
                 "experiments/aaa_vs_petri/full_judge/spec.py", "experiments/aaa_vs_petri/full_judge/worker.py"):
    image = image.add_local_file(ROOT / relative, "/opt/aaa/" + relative)
image = image.add_local_dir(ROOT / "src/prompts", "/opt/aaa/src/prompts", ignore=["**/__pycache__/**"])


def judge_secret():
    # Inject only the required provider key, not the multi-provider sandbox
    # secret, project .env, Modal authentication file, or arbitrary env vars.
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and modal.is_local():
        from dotenv import dotenv_values
        key = dotenv_values(ROOT / ".env").get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("Missing Anthropic key; no credential values logged")
    return modal.Secret.from_dict({"ANTHROPIC_API_KEY": key})


@app.function(image=image, secrets=[judge_secret()], retries=0, max_containers=6,
              timeout=1100, cpu=1, memory=2048)
async def judge_job(job):
    from experiments.aaa_vs_petri.full_judge.worker import execute_one
    return await execute_one(job, state)


@app.local_entrypoint()
def main(output: str = "logs/petri-full-judge/integrated-v1-opus48", approved_paid_run: bool = False,
         fetch_only: bool = False, canary_only: bool = False):
    from experiments.aaa_vs_petri.full_judge.run import verify, atomic_json, now
    run = (ROOT / output).resolve()
    manifest = verify(run)
    if manifest["execution_backend"] != "modal":
        raise ValueError("Run was not prepared for Modal")
    run_hash = hashlib.sha256((run / "manifest.json").read_bytes()).hexdigest()
    jobs = json.loads((run / "jobs.json").read_text())
    if len(jobs) != 36 or len({j["id"] for j in jobs}) != 36:
        raise ValueError("Only the 36 frozen jobs are authorized")
    schemas = json.loads((run / "schemas.json").read_text())
    payloads = []
    for job in jobs:
        content = (run / "inputs" / f"{job['id']}.json").read_text()
        payloads.append({**job, "run_hash": run_hash, "model": manifest["judge_model"],
            "input_text": content, "input_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "prompt": (run / "prompts" / f"{job['family']}.txt").read_text(),
            "schema": schemas[job["family"]]["inlined"]})

    def fetch():
        counts, reserved = Counter(), 0
        for job in jobs:
            row = state.get(f"{run_hash}/{job['id']}/row", None)
            if row is not None:
                if row["id"] != job["id"] or len(row["attempts"]) > 3:
                    raise ValueError("Invalid remote checkpoint")
                atomic_json(run / "predictions" / f"{job['id']}.json", row)
                counts[row["status"]] += 1
            else:
                counts["not_started"] += 1
            for number in range(1, 4):
                reserved += state.contains(f"{run_hash}/{job['id']}/reservation/{number}")
        if reserved > 108:
            raise ValueError("Request ceiling exceeded")
        progress = {"recorded_at": now(), "execution_backend": "modal", "job_status_counts": dict(counts),
                    "requests_reserved": reserved, "request_ceiling": 108, "run_hash": run_hash,
                    "modal_dictionary": "aaa-petri-full-judge-v1-records"}
        atomic_json(run / "progress.json", progress)
        print(json.dumps(progress, indent=2), flush=True)
        return progress

    if fetch_only:
        fetch()
        return
    if not approved_paid_run:
        raise ValueError("Explicit approval required before dispatching paid jobs")
    if state.get(run_hash + "/halt", None):
        fetch()
        raise ValueError("Remote provider halt is set; inspect before resuming")
    # Test both output schemas on actual planned jobs, in parallel, before fanout.
    canaries = [p for p in payloads if p["audit_id"] == jobs[0]["audit_id"]]
    try:
        outcomes = list(judge_job.map(canaries, order_outputs=False))
        for result in outcomes:
            print(json.dumps(result), flush=True)
        if any(result["status"] != "success" for result in outcomes):
            raise RuntimeError("A Modal canary failed; remaining jobs not dispatched")
        for item in canaries:
            recorded = state.get(f"{run_hash}/{item['id']}/row")
            if not any(a.get("model_events") for a in recorded["attempts"]):
                raise RuntimeError("Native model event capture missing; inspect before fanout")
        if not canary_only:
            for result in judge_job.map([p for p in payloads if p not in canaries], order_outputs=False):
                print(json.dumps(result), flush=True)
                row = state.get(f"{run_hash}/{result['id']}/row", None)
                if row:
                    atomic_json(run / "predictions" / f"{result['id']}.json", row)
    finally:
        fetch()
