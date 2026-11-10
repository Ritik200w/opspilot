# OpsPilot

AI incident triage platform: receives alerts via webhook, gathers logs/metrics
context, asks Claude for a root-cause summary, posts it to Slack, stores incidents.

## Stack
Python 3.12, FastAPI, PostgreSQL, Redis, Docker, docker-compose.
Later: GitHub Actions, Terraform, Kubernetes.

## Structure
- app/        FastAPI code (api/, services/, models/, collectors/)
- tests/      pytest tests
- demo-app/   small sample service we break on purpose
- infra/      Terraform and k8s (later)

## Commands
- Run:   docker compose up --build
- Test:  pytest
- Lint:  ruff check . && ruff format --check .

## Rules
- Type hints on all functions; keep functions small.
- No secrets in code; read config from environment variables.
- Every new feature needs at least one test.
- Claude (the AI) only proposes fixes; a human approves them.
- Ask before adding new dependencies.
