"""Fresh-client, bounded native-nullable Modal worker for the approved recovery."""
import hashlib
import json
from copy import deepcopy
from unittest.mock import patch

from experiments.aaa_vs_petri.full_judge import nullable_array, spec
from experiments.aaa_vs_petri.full_judge.worker import now, object_only, fatal


async def execute_one(job, state):
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ResponseSchema, get_model
    from inspect_ai.model._providers import anthropic
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    if hashlib.sha256(job['input_text'].encode()).hexdigest() != job['input_sha256']:
        raise ValueError('Input differs from the frozen packet')
    if job['family'] not in spec.FAMILIES or job['model'] != 'anthropic/claude-opus-4-8':
        raise ValueError('Unexpected judge family/model')
    initial = job['initial']
    expected = 0 if initial['status'] == 'success' else 3 - len(initial['attempts'])
    if job['max_new_attempts'] != expected or not 0 <= expected <= 3:
        raise ValueError('Invalid per-job recovery budget')
    prefix = f"{job['run_hash']}/{job['id']}"
    row_key, claim_key, stop_key = prefix + '/row', prefix + '/claim', job['run_hash'] + '/halt'
    packet = json.loads(job['input_text'])
    row = await state.get.aio(row_key, None) or deepcopy(initial)
    if row['status'] == 'success':
        spec.validate(row['result'], packet, job['family'])
        await state.put.aio(row_key, row)
        return {'id': job['id'], 'status': 'success', 'reused': True}
    if not await state.put.aio(claim_key, {'claimed_at': now()}, skip_if_exists=True):
        return {'id': job['id'], 'status': 'claimed_elsewhere_or_interrupted'}
    model = None
    try:
        if any(a['status'] == 'reserved' for a in row['attempts']):
            row['status'] = 'reservation_recovery_required'
            await state.put.aio(row_key, row)
            return {'id': job['id'], 'status': row['status']}
        if len(row['attempts']) > 3:
            raise ValueError('Per-job ceiling exceeded')
        # A container can process many jobs: do not retrieve a closed memoized client.
        model = get_model(job['model'], memoize=False,
            config=GenerateConfig(max_connections=1, max_retries=0, timeout=300, max_tokens=16000, cache_prompt='auto'),
            max_retries=0, streaming=False)
        if model.api.client.max_retries != 0:
            raise ValueError('Automatic SDK retries must remain disabled')
        config = GenerateConfig(response_schema=ResponseSchema(name=job['family'], json_schema=job['schema']), max_retries=0)
        messages = [ChatMessageSystem(content=job['prompt']), ChatMessageUser(content=job['input_text'])]
        while len(row['attempts']) < 3:
            if await state.get.aio(stop_key, None):
                row['status'] = 'paused_provider_error'
                break
            number = len(row['attempts']) + 1
            slot = number - len(initial['attempts'])
            if not 1 <= slot <= job['max_new_attempts']:
                raise ValueError('New-attempt allowance exhausted')
            attempt = {'number': number, 'recovery_slot': slot, 'origin': 'nullable_recovery',
                       'status': 'reserved', 'reserved_at': now(), 'response_transport': 'native_nullable_array'}
            if not await state.put.aio(prefix + f'/reservation/{slot}', attempt, skip_if_exists=True):
                row['status'] = 'reservation_recovery_required'
                break
            row['attempts'].append(attempt)
            row['status'] = 'pending'
            await state.put.aio(row_key, row)
            old, capture = transcript(), Transcript()
            init_transcript(capture)
            stop = False
            try:
                with patch.object(anthropic, 'set_additional_properties_false', object_only):
                    reply = await model.generate(messages, config=config)
                attempt.update(response=reply.completion, model_output=reply.model_dump(mode='json'),
                               usage=reply.usage.model_dump(mode='json') if reply.usage else {}, stop_reason=reply.stop_reason)
                row['result'] = nullable_array.validate(json.loads(reply.completion), packet, job['family'])
                row['status'] = attempt['status'] = 'success'
            except Exception as error:
                attempt.update(status='error', error_type=type(error).__name__, error=str(error))
                stop = fatal(error)
                if stop:
                    await state.put.aio(stop_key, {'job': job['id'], 'time': now(), 'reason': 'Provider rejection; inspect saved request before resuming.'}, skip_if_exists=True)
            finally:
                attempt['completed_at'] = now()
                attempt['model_events'] = [e.model_dump(mode='json') for e in capture.events if e.event == 'model']
                init_transcript(old)
                await state.put.aio(row_key, row)
            if stop:
                row['status'] = 'paused_provider_error'
                break
            if row['status'] == 'success':
                break
        if row['status'] == 'pending':
            row['status'] = 'failed'
        await state.put.aio(row_key, row)
        return {'id': job['id'], 'status': row['status'], 'counted_attempts': len(row['attempts'])}
    finally:
        if model is not None:
            await model.api.aclose()
        await state.pop.aio(claim_key, None)
