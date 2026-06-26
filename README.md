# sunbird-va-api

## Delete all volumes
```
docker system prune -a --volumes
```

----
# Create a new network
```
docker network create networkname
```
# Run seperate Redis
```
docker run -d --name redis-stack --network networkname -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```
# Docker Setup
```
docker compose up --build --force-recreate --detach
```
# Stop
```
docker compose down --remove-orphans
```
docker compose down --remove-orphans
docker compose up --build --force-recreate --detach
docker logs -f container name

# Marqo Setup

```
docker run --name marqo -p 8882:8882 \
    -e MARQO_MAX_CONCURRENT_SEARCH=50 \
    -e VESPA_POOL_SIZE=50 \
    marqoai/marqo:latest
```

----
# Deployment env (ai4i / Qwen "agrinet-model")

These settings let the same image run against the full agrinet/Qwen model. They
replace the temporary DevOps runtime patches once configured in the env repo
(`ai4i-services-env/.../mh-oan-api.env`). See `.env.example` for the full list.

## Redis AUTH
The shared platform Redis requires a password. `app/core/cache.py` and
`app/core/limiter.py` read `REDIS_PASSWORD` from the environment and include it
in the aiocache config / slowapi storage URI when set; when unset, behavior is
unchanged (password-less Redis). This replaces the DevOps `cache.py`/`limiter.py`
ConfigMap patch.

```
REDIS_PASSWORD=<redis-password>   # base64-stored in the env repo secrets:
```

## LLM endpoint — route via ai4i orchestrate (preferred)
OAN uses an OpenAI-compatible client. Point it at the **ai4i orchestrate /
inference-service**, which exposes `POST /api/v1/chat/completions`:

```
VLLM_AGRINET_MODEL_URL=http://<inference-service>/api/v1
VLLM_MODERATION_MODEL_URL=http://<inference-service>/api/v1
```

The client appends `/chat/completions`; a full `.../chat/completions` URL is
auto-trimmed back to the root (`agents/models.py:_normalize_openai_base_url`).
Direct-vLLM (`http://65.2.186.224:8080/v1`) remains a valid fallback for POC.

## Qwen context budget
Qwen `agrinet-model` has a **16k** context and the system/agent prompt is
~12-13k tokens, so:

```
max_output_tokens <= 16384 - actual_prompt_tokens
```

`AGRINET_MAX_TOKENS=4096` overflows the 16k window (vLLM returns 400). Either
lower the output cap (`AGRINET_MAX_TOKENS=1024`) or trim the prompt
(`AGRINET_PROMPT_MAX_CHARS`). Both are env-only toggles (`agents/agrinet.py`).