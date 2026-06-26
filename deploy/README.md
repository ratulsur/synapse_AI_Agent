# Deployment

Owner: cloud-developer

Packaging, configuration, and infrastructure for running the agent + API.

## Scope
- Containerization (Dockerfile / compose) for the API service.
- Environment + secrets wiring (OPENAI/GOOGLE/GROQ keys, LLM_PROVIDER, MCP
  endpoints) consistent with utils.model_loader.ApiKeyManager and
  configuration.yaml.
- SQLite volume / path for persistence (checkpointer + source_store); migration
  path to a hosted DB if needed.
- CI/CD and runtime config.

TODO(cloud-developer): add Dockerfile, compose, env templates, and IaC as needed.
Do not hardcode secrets; follow the .env convention (not committed).
