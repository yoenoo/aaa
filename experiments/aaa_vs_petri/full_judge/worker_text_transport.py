"""Transport-only fallback for Anthropic's >16 nullable-property schema limit.

Keep exact prompts, inputs, local schemas/validators and reservation accounting.
Only scheming's native response_schema argument is omitted; its full JSON schema
remains in the unchanged system prompt. Debugging stays native structured JSON.
"""
from unittest.mock import patch
from experiments.aaa_vs_petri.full_judge import spec, worker


async def execute_one(job, state):
    if job["family"] != spec.FAMILIES[0]:
        return await worker.execute_one(job, state)
    import inspect_ai.model
    original_config = inspect_ai.model.GenerateConfig

    def config_without_native_schema(**kwargs):
        kwargs.pop("response_schema", None)
        return original_config(**kwargs)

    try:
        with patch.object(inspect_ai.model, "GenerateConfig", config_without_native_schema):
            return await worker.execute_one(job, state)
    finally:
        key = f"{job['run_hash']}/{job['id']}/row"
        row = await state.get.aio(key, None)
        if row:
            for attempt in row["attempts"]:
                events = attempt.get("model_events", [])
                attempt["response_transport"] = ("native_schema" if any(e.get("config", {}).get("response_schema") for e in events)
                    else "prompt_schema_with_unchanged_strict_local_validation")
            await state.put.aio(key, row)
