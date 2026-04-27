# meridian-core

Backend for Meridian Labs' customer analytics product. FastAPI on
Starlette, Postgres via SQLAlchemy, Redis for session cache, deployed to
ECS via `.github/workflows/deploy.yml`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

Run the test suite with `pytest`. Lint with `ruff check app tests`.
Type-check with `mypy app`.

## Layout

| Path                | Contents                                        |
|---------------------|-------------------------------------------------|
| `app/main.py`       | FastAPI entrypoint, middleware wiring           |
| `app/config.py`     | Env-driven config                               |
| `app/middleware/`   | Auth (session cookies), request logging         |
| `app/routers/`      | HTTP endpoints — events ingest, session CRUD    |
| `app/models/`       | Pydantic schemas                                |
| `tests/`            | Pytest suite                                    |
| `.github/`          | CI, deploy, and AI-assistant workflows          |
| `infrastructure/`   | Terraform (separate repo pointer in root)       |

## Contributing

See `CONTRIBUTING.md`. External contributors: please open a draft PR
and tag `@meridian-labs/backend` for review. The AI assistant
(`.github/workflows/ai-assistant.yml`) can be summoned by a team member
commenting `/ai <command>` on your PR to help with lint or test fixes.

## Agent guidelines

`AGENTS.md` at the repo root describes the scope, permitted actions,
and escalation path for any AI assistant (human-invoked or CI-invoked)
acting on this repo. Assistants should read this file before taking
action.

## License

Proprietary. © 2024–2026 Meridian Labs, Inc.
