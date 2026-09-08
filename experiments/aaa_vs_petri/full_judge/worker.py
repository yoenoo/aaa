"""One bounded Modal job. Shared atomic claims/reservations prevent duplicate spend."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from unittest.mock import patch

from experiments.aaa_vs_petri.full_judge import spec


def now():
    return datetime.now(timezone.utc).isoformat()


def object_only(schema):
    schema.additionalProperties = False if schema.type == "object" else None
    if schema.items:
        object_only(schema.items)
    for value in (schema.properties or {}).values():
        object_only(value)
    for value in schema.anyOf or []:
        object_only(value)


def fatal(error):
    return getattr(error, "status_code", None) in {400, 401, 403, 404} or any(
        s in str(error).lower() for s in ("invalid_request_error", "authentication_error",
            "permission_error", "specified workspace api usage limits", "schema type is missing"))


async def execute_one(job, state):
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ResponseSchema, get_model
    from inspect_ai.model._providers import anthropic
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    if hashlib.sha256(job["input_text"].encode()).hexdigest() != job["input_sha256"]:
        raise ValueError("Transported input differs from frozen request")
    if job["family"] not in spec.FAMILIES or job["model"] != "anthropic/claude-opus-4-8":
        raise ValueError("Unexpected family/model")
    prefix = f"{job['run_hash']}/{job['id']}"
    row_key, claim_key, stop_key = prefix + "/row", prefix + "/claim", job["run_hash"] + "/halt"
    packet = json.loads(job["input_text"])
    prior = await state.get.aio(row_key, None)
    if prior and prior["status"] == "success":
        spec.validate(prior["result"], packet, job["family"])
        return {"id": job["id"], "status": "success", "reused": True}
    if not await state.put.aio(claim_key, {"claimed_at": now()}, skip_if_exists=True):
        return {"id": job["id"], "status": "claimed_elsewhere_or_interrupted"}
    model = None
    try:
        row = prior or {"id": job["id"], "audit_id": job["audit_id"], "family": job["family"],
            "model": job["model"], "status": "pending", "attempts": [], "execution_backend": "modal"}
        for attempt in row["attempts"]:
            if attempt["status"] == "reserved":
                attempt["status"] = "interrupted_outcome_unknown"
        if len(row["attempts"]) > 3:
            raise ValueError("Per-job ceiling exceeded")
        config = GenerateConfig(max_connections=1, max_retries=0, timeout=300, max_tokens=16000, cache_prompt="auto")
        model = get_model(job["model"], config=config, max_retries=0, streaming=False)
        if model.api.client.max_retries != 0:
            raise ValueError("SDK automatic retries must be disabled")
        generate_config = GenerateConfig(response_schema=ResponseSchema(name=job["family"], json_schema=job["schema"]), max_retries=0)
        messages = [ChatMessageSystem(content=job["prompt"]), ChatMessageUser(content=job["input_text"])]
        while len(row["attempts"]) < 3:
            if await state.get.aio(stop_key, None):
                row["status"] = "paused_provider_error"
                break
            number = len(row["attempts"]) + 1
            attempt = {"number": number, "status": "reserved", "reserved_at": now()}
            # Exactly three globally unique reservation slots per approved job.
            # Modal retries/preemption cannot reacquire an already consumed slot.
            reserved = await state.put.aio(prefix + f"/reservation/{number}", attempt, skip_if_exists=True)
            if not reserved:
                row["status"] = "reservation_recovery_required"
                break
            row["attempts"].append(attempt)
            await state.put.aio(row_key, row)
            old = transcript()
            capture = Transcript()
            init_transcript(capture)
            stop = False
            try:
                with patch.object(anthropic, "set_additional_properties_false", object_only):
                    reply = await model.generate(messages, config=generate_config)
                attempt.update(response=reply.completion, model_output=reply.model_dump(mode="json"),
                               usage=reply.usage.model_dump(mode="json") if reply.usage else {}, stop_reason=reply.stop_reason)
                row["result"] = spec.validate(json.loads(reply.completion), packet, job["family"])
                row["status"] = attempt["status"] = "success"
            except Exception as error:
                attempt.update(status="error", error_type=type(error).__name__, error=str(error))
                stop = fatal(error)
                if stop:
                    await state.put.aio(stop_key, {"job": job["id"], "time": now(), "reason": "Provider rejected request; inspect private attempt record before any resume."}, skip_if_exists=True)
            finally:
                attempt["completed_at"] = now()
                attempt["model_events"] = [e.model_dump(mode="json") for e in capture.events if e.event == "model"]
                init_transcript(old)
                await state.put.aio(row_key, row)
            if stop:
                row["status"] = "paused_provider_error"
                break
            if row["status"] == "success":
                break
        if row["status"] == "pending":
            row["status"] = "failed"
        await state.put.aio(row_key, row)
        return {"id": job["id"], "status": row["status"], "attempts": len(row["attempts"])}
    finally:
        if model is not None:
            await model.api.aclose()
        await state.pop.aio(claim_key, None)
