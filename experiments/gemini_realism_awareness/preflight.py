"""Two tiny authorized connectivity calls, with durable budget accounting."""
import asyncio
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ['AAA_EXPERIMENT_BUDGET'] = '1'
os.environ['AAA_EXPERIMENT_JOB'] = 'connectivity-pro-opus'
from experiments.gemini_realism_awareness import budget
from dotenv import load_dotenv
from inspect_ai.model import get_model, GenerateConfig


async def main():
    load_dotenv(budget.ROOT / '.env')
    for model in ['google/gemini-3.1-pro-preview', 'anthropic/claude-opus-4-8']:
        try:
            response = await get_model(model).generate('Reply with OK.', config=GenerateConfig(max_tokens=64, max_retries=0, timeout=60))
            print(json.dumps({'model': model, 'status': 'reachable', 'usage': response.usage.model_dump() if response.usage else None}), flush=True)
        except Exception as exc:
            print(json.dumps({'model': model, 'status': 'failed', 'error_type': type(exc).__name__}), flush=True)
            raise SystemExit(1)


if __name__ == '__main__': asyncio.run(main())
