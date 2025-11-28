# Actor Mesh Demo – Crash Course

## What This Repo Is
- Full-stack demo of an “actor mesh” for e-commerce support: FastAPI gateway + NATS JetStream message bus + chain of actors (sentiment → intent → context → decision → response → guardrails → aggregator) with escalation and execution hooks.
- Includes mock REST services (customer/orders/tracking) and a simple web chat widget (HTTP + WebSocket).
- Designed to showcase choreography-style routing (smart routers, naive processors) with progressive payload enrichment.

## High-Level Flow
- Entry: `api/gateway.py` handles `/api/chat` HTTP POST and `/ws` WebSockets. It wraps requests into `models.message.Message` with a `Route` (default `StandardRoutes.FULL_PROCESSING_PIPELINE`) and publishes to `ecommerce.support.<first_actor>`.
- Bus: NATS JetStream stream `ECOMMERCE_SUPPORT` (work-queue retention) carries all subjects under `ecommerce.support.*`.
- Actors (`actors/*.py`) subscribe to their subject, enrich the `MessagePayload`, advance the route, and publish to the next subject. Retry/error metadata stored in `Message.metadata`.
- Smart routing:
  - `decision_router.py` rewrites the route for urgency/VIP/low-confidence/actionable cases.
  - `escalation_router.py` handles errors/low confidence/human handoff/fallback responses.
- Exit: `response_aggregator.py` publishes final responses to `ecommerce.support.gateway.response`, which the gateway/WebSocket manager listens to. It also logs to SQLite (intended) before responding.

## Actors at a Glance
- `sentiment_analyzer.py`: Rule-based sentiment/urgency/complaint/escalation keyword detection.
- `intent_analyzer.py`: LiteLLM-based intent + entity extraction with rule-based fallback.
- `context_retriever.py`: Fetches customer profile/orders/tracking via mock services; caches in Redis (simplified client expected).
- `decision_router.py`: Adjusts route for escalation, fast paths, action execution, or human review.
- `response_generator.py`: Builds reply text (LLM + templates); adds action hints.
- `guardrail_validator.py`: Content/policy validation; flags unsafe outputs.
- `execution_coordinator.py`: Simulated execution of refunds/updates/etc. against mock services.
- `escalation_router.py`: Retry/error recovery/human handoff/fallback response routing.
- `response_aggregator.py`: Final delivery + SQLite logging + metadata summarization.

## Supporting Services
- Mock APIs: `mock_services/*` (FastAPI), ports 8001/8002/8003 in Makefile/docker-compose.
- Gateway/web: `api/gateway.py`, `api/websocket.py`, web assets in `web/`.
- Demos/tests: `demo.py` exercises scenarios; `tests/test_basic_flow.py` runs actor pipeline sans NATS; `tests/integration/test_system_e2e.py` expects full stack.

## Running Locally (fast path)
1) `./install.sh` (creates venv, installs deps, starts NATS/Redis via Docker if available).  
2) `cp .env.example .env` and add LLM keys if you want LLM paths; rule-based fallbacks work without.  
3) Start everything: `make start` (NATS+Redis, mock services, actors, gateway).  
4) Open chat UI: `make web-widget` then visit `http://localhost:8000/widget` or `/static/chat.html`.  
5) Minimal demo without NATS/services: `python tests/test_basic_flow.py` (uses actors directly, but context retrieval will fail unless mock APIs/Redis are up).

### Key Ports
- Gateway 8000 (HTTP/WebSocket), NATS 4222/8222, Redis 6379, Mock services 8001-8003.

## Tests & Tooling
- `make test` currently runs `tests/test_basic_flow.py`.
- Richer suites: `make test-unit`, `make test-integration`, `make test-e2e-all`, `make test-phase6` (web). E2E assumes Docker Compose infra.
- Lint/format: `make format`, `make lint`; watch for mypy/ruff settings in `pyproject.toml`.

## Deployment Notes
- `docker-compose.yml` builds gateway + actors + mock services + infra. Dockerfile expects `storage/` code (see gaps below) and uses multi-stage targets `gateway`, `actor`, `mock-services`.
- Kubernetes manifests under `k8s/` (k3d scripts + overlays) if you need cluster deploy.

## What to Focus On First
- Read `README.md` (architecture + commands) then skim `docs/QUICKSTART.md` and `docs/MAKEFILE_GUIDE.md` for command cheats.
- Study `models/message.py` (Route/MessagePayload), `actors/base.py` (NATS workflow), `api/gateway.py` + `api/websocket.py` (entrypoints), `demo.py` for scenario expectations.
- Check `docker-compose.yml`/`Makefile` for how pieces start and how ports/subjects map.
- For debugging flows, start with `tests/test_basic_flow.py` (actor-only) and `tests/integration/test_actor_flow.py` (mocked NATS) to see expected enrichments.

## What’s Mostly Redundant/Marketing
- `docs/IMPLEMENTATION_SUMMARY.md`, large sections of `README.md` under “What This Demonstrates”, and agent-spec docs are glossy overviews; skim only if you need talking points.
- Repeated command references across README/QUICKSTART/MAKEFILE_GUIDE—pick one (MAKEFILE_GUIDE) to avoid duplication.

## Known Gaps / Blockers
- **Missing storage package**: imports expect `storage/redis_client.py`, `storage/redis_client_simple.py`, and `storage/sqlite_client.py`, but the repository doesn’t contain a `storage/` directory. This breaks actors (context retriever, response aggregator), tests, Docker builds, and anything using persistence/caching. You’ll need to recreate or stub these modules to run the full stack.
- LLM-dependent paths (`intent_analyzer`, `response_generator`, guardrails) require API keys or will fall back to rule-based/templates; expect degraded outputs without keys.
- ResponseAggregator currently lacks access to the full `Message` when invoked via base class payload-only path; logging/delivery uses fallbacks—be aware when debugging.

## Quick Command Cheats (after venv activation)
- Start infra only: `make start-infrastructure` (NATS+Redis).
- Start mock APIs: `make start-services`; stop with `make stop-services`.
- Start actors: `make start-actors`; gateway: `make start-gateway`.
- Full restart: `make restart`; clean env: `make clean` (removes venv/data/logs/PIDs).
- Health/logs: `make health`, `make status`, `make logs`, `make monitor`.

## Suggested Next Steps to Get Running
- Implement minimal `storage/redis_client.py` + `storage/redis_client_simple.py` + `storage/sqlite_client.py` per expectations in tests and actor imports (see `tests/unit/test_storage.py` and `tests/unit/test_storage_simple.py` for required API).
- Once storage exists, rerun `make start` and `make test` to validate.
- If Dockerized run is desired, rebuild after storage is added: `make docker-build && make docker-run` or `docker-compose up`.
