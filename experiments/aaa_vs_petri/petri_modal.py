"""Run Petri-framework trajectory generation on Modal: one container per prose seed.

Same configuration as the local 3.1-pro baseline (auditor/realism Opus 4.8, 30 turns,
synthetic tools, rollback on, realism filter 0.6, 300 s request timeout, 1800 s sample
limit). Each container runs `inspect eval petri_trajectories.py` for a single seed and
returns its .eval; the local entrypoint writes them under --log-dir. Credentials come
from the repo .env (Anthropic key + Vertex service account); nothing is logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import modal

# No conditionals in object definitions: Modal must see identical Image/Secret
# dependencies locally and inside the container (the image is only built locally).
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("AAA_ROOT", HERE.parents[1] if len(HERE.parents) > 1 else HERE))
SEED_DIR = HERE / "petri_seeds_all"
KEYS = ("ANTHROPIC_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_SA_JSON")

app = modal.App("aaa-petri-trajectories")
image = (modal.Image.debian_slim(python_version="3.13")
         .pip_install("inspect-ai==0.3.246", "inspect-petri==3.1.0", "anthropic==0.116.0", "google-genai==2.11.0")
         .add_local_file(HERE / "petri_trajectories.py", "/opt/petri/petri_trajectories.py")
         .add_local_dir(SEED_DIR, "/opt/petri/seeds"))


def run_secret():
    """Locally: read .env (+ the Vertex service-account file). In the container the same
    keys are already injected, so the Secret is rebuilt from the environment."""
    values = {k: os.environ.get(k, "") for k in KEYS}
    env_file = ROOT / ".env"
    if not values["ANTHROPIC_API_KEY"] and env_file.exists():
        from dotenv import dotenv_values
        env = {**dotenv_values(env_file), **os.environ}
        values.update({"ANTHROPIC_API_KEY": env["ANTHROPIC_API_KEY"],
                       "GOOGLE_GENAI_USE_VERTEXAI": env.get("GOOGLE_GENAI_USE_VERTEXAI", "true"),
                       "GOOGLE_CLOUD_PROJECT": env["GOOGLE_CLOUD_PROJECT"],
                       "GOOGLE_CLOUD_LOCATION": env.get("GOOGLE_CLOUD_LOCATION", "global"),
                       "GOOGLE_SA_JSON": Path(env["GOOGLE_APPLICATION_CREDENTIALS"]).read_text()})
    return modal.Secret.from_dict(values)


@app.function(image=image, secrets=[run_secret()], timeout=14400, retries=0, max_containers=16, cpu=2, memory=4096)
def run_seed(seed_file: str, target: str, auditor: str, max_turns: int, realism_filter: float, time_limit: int = 1800) -> dict:
    sa = Path("/tmp/vertex-sa.json")
    sa.write_text(os.environ["GOOGLE_SA_JSON"])
    env = {**os.environ, "GOOGLE_APPLICATION_CREDENTIALS": str(sa), "INSPECT_LOG_FORMAT": "eval"}
    one = Path(tempfile.mkdtemp()) / "seed"
    one.mkdir()
    (one / seed_file).write_bytes(Path("/opt/petri/seeds", seed_file).read_bytes())
    logs = Path(tempfile.mkdtemp()) / "logs"
    cmd = [sys.executable, "-m", "inspect_ai", "eval", "petri_trajectories.py",
           "-T", f"seed_dir={one}", "-T", f"max_turns={max_turns}", "-T", f"realism_filter={realism_filter}",
           "--model-role", f"auditor={auditor}", "--model-role", f"realism={auditor}", "--model-role", f"target={target}",
           "--log-dir", str(logs), "--max-samples", "1", "--max-connections", "8", "--timeout", "300",
           "--time-limit", str(time_limit), "--display", "plain"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd="/opt/petri", env=env)
    evals = sorted(logs.glob("*.eval"))
    return {"seed_file": seed_file, "returncode": proc.returncode, "stdout_tail": proc.stdout[-3000:], "stderr_tail": proc.stderr[-3000:],
            "eval_name": evals[-1].name if evals else None, "eval_bytes": evals[-1].read_bytes() if evals else None}


@app.local_entrypoint()
def main(target: str = "google/gemini-3.8-flash", auditor: str = "anthropic/claude-opus-4-8",
         log_dir: str = "logs/petri-trajectories/gemini-3.8-flash-modal", max_turns: int = 30, realism_filter: float = 0.6,
         seeds: str = "", time_limit: int = 1800):
    out = ROOT / log_dir
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in SEED_DIR.glob("*.md"))
    if seeds:
        files = [f for f in files if f in seeds.split(",")]
    print(f"launching {len(files)} seeds on Modal -> {out}", flush=True)
    summary = []
    for r in run_seed.map(files, kwargs={"target": target, "auditor": auditor, "max_turns": max_turns, "realism_filter": realism_filter, "time_limit": time_limit}):
        if r["eval_bytes"]:
            (out / r["eval_name"]).write_bytes(r["eval_bytes"])
        (out / f"{r['seed_file']}.stdout.txt").write_text(r["stdout_tail"] + "\n--- stderr ---\n" + r["stderr_tail"])
        summary.append({k: r[k] for k in ("seed_file", "returncode", "eval_name")})
        print(json.dumps(summary[-1]), flush=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"done: {sum(1 for s in summary if s['eval_name'])}/{len(files)} evals written", flush=True)
