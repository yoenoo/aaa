# Authorized budget and accounting

User authorization: use up to **$1,000 for the entire experiment**; prioritize Gemini 3.1 Pro, then Gemini 3.8 Flash. This is a ceiling, not a spending target.

The ledger at `logs/gemini-realism-awareness/budget.json` reserves model spend before every provider request, including retries, and uses a file lock across processes. API envelope: $900. Infrastructure envelope: $100. Outstanding requests count at their reservation amount. Interrupted/failed requests are not automatically refunded. Reconcile them before treating that capacity as available.

Pilot requests are text-only, with at most 2 MB of serialized messages/tool schemas/configuration and 16,384 output tokens. Each request reserves $25. This is a conservative envelope using the maximum rates below and room for provider framing. Usage settles the reservation against conservative rates; missing, invalid, or negative usage retains the reservation. A limit or accounting failure propagates Inspect's `LimitExceededError` before further calls.

Accounting rates in USD per million tokens:

| Model | Input upper rate | Output upper rate |
|---|---:|---:|
| google/gemini-3.1-pro-preview | 4.00 | 18.00 |
| google/gemini-3.8-flash | 1.65 | 7.50 |
| anthropic/claude-opus-4-8 | 10.00 | 25.00 |

These intentionally use long-context Pro pricing, rates above current introductory Flash pricing, and the maximum Opus cache-write rate for all input. Cache counts may overlap normal input counts; counting both deliberately overestimates. They are **usage-based conservative estimates, not verified invoices**.

Pricing checked against the official [Google Cloud pricing page](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) and [Anthropic pricing page](https://platform.claude.com/docs/en/about-claude/pricing) during setup. Do not silently extend this envelope to another model, modality, paid tool, priority tier, or larger request.

Each AAA sandbox reserves $3 against the infrastructure envelope. The generated compose file caps it at 2 CPUs, 4 GiB, and one hour, with a five-minute idle timeout; the sample has a shorter 20-minute limit and cleanup enabled. This includes margin for image provisioning at the [published Modal CPU and memory rates](https://modal.com/pricing); inspect actual sandbox/build usage before expanding beyond this small pilot. Petri's local synthetic condition uses no Modal sandbox.

Two initial connectivity calls succeeded. Their conservative accounted cost was $0.001326. One AAA launch then stopped locally on a missing model-pricing registry entry before any trajectory provider calls; its $3 infrastructure reservation remains conservatively held pending reconciliation. The subsequent launch removed that optional registry dependency; the independent pre-request guard remains active.

Eighteen offline checks cover reservation exhaustion, invalid usage, duplicate settlement, propagation through Inspect's real hook dispatcher, infrastructure limits, preservation of baseline seed objects, diagnostic failure-to-success behavior, the historical analysis corrections, exclusion of invalid or unassessable judgments from awareness negatives, shared scenario facts, synthetic Petri resource boundaries, verbatim role enforcement, observation windows, and ownership/credit semantics. Run:

```sh
.venv/bin/python -m unittest discover -s experiments/gemini_realism_awareness -p 'test_*.py' -v
```
