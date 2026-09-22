# Inference providers

Inference configuration is deployment-level. Defaults remain offline-safe:
`REQUIREMENT_ANALYSIS_PROVIDER=rules` and
`AGENT_IMPLEMENTATION_PROVIDER=disabled`.

## OpenAI-compatible provider

```dotenv
OPENAI_COMPATIBLE_BASE_URL=https://gateway.example
OPENAI_COMPATIBLE_API_KEY=...
OPENAI_COMPATIBLE_MODEL=...
OPENAI_COMPATIBLE_MAX_TOKENS=4096
```

BotQ posts to `/v1/chat/completions` with bearer authentication and requires
valid JSON in `choices[0].message.content`. Provider lists are ordered fallback
chains, such as `REQUIREMENT_ANALYSIS_PROVIDER=rules,openai_compatible,heroku`
and `AGENT_IMPLEMENTATION_PROVIDER=openai_compatible,runpod`.

Only HTTPS destinations are accepted. URL credentials, private or reserved
addresses, redirects, prompts, request bodies, keys, and raw provider output
are excluded from logs and diagnostics. Validate configuration without a
network request with:

```text
PYTHONPATH=backend python scripts/validate_provider_config.py --json
```

Rotate keys in the deployment secret manager. Roll back by removing
`openai_compatible` from the provider list or restoring `rules` and
`disabled`; no database migration is required.
