# Synapse AI Agent

A research and analyst agent built on [LangChain](https://www.langchain.com/), with pluggable LLM providers and a configuration-driven model layer.

> **Project status:** Early-stage skeleton. The model/config/logging/exception foundations are in place and runnable; the agent orchestration and retrieval pipeline are not yet implemented.

## Features

- **Config-driven model loading** — models, providers, and parameters are defined in a single YAML file and loaded through one entry point.
- **Pluggable LLM providers** — switch between OpenAI, Google Gemini, and Groq at runtime via an environment variable, with no code changes.
- **Centralized API key management** — keys are loaded from the environment and their presence is logged without ever exposing the values.
- **Structured logging** — JSON-formatted logs via `structlog`, written simultaneously to the console and a timestamped file.
- **Consistent error handling** — a custom exception type wraps underlying errors and reports the deepest call site for faster debugging.

## Requirements

- Python **3.13+**
- [uv](https://docs.astral.sh/uv/) for environment and dependency management
- API keys for the provider(s) you intend to use (OpenAI, Google, and/or Groq)

## Installation

```bash
# Clone the repository
git clone https://github.com/ratulsur/synapse_AI_Agent.git
cd synapse_AI_Agent

# Create the virtual environment (Python 3.13)
uv venv venv --python 3.13

# Install dependencies (editable install)
uv pip install --python venv/bin/python -e .
```

## Configuration

### Environment variables

Create a `.env` file in the project root (it is git-ignored):

```dotenv
# Provider API keys (set the ones you use)
OPENAI_API_KEY=your-openai-key
GOOGLE_API_KEY=your-google-key
GROQ_API_KEY=your-groq-key

# Selects which LLM provider to load (defaults to "openai")
LLM_PROVIDER=openai

# Optional: override the config file location
# CONFIG_PATH=/path/to/configuration.yaml
```

| Variable         | Required        | Description                                                                                        |
| ---------------- | --------------- | -------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY` | If using OpenAI | API key for OpenAI models.                                                                         |
| `GOOGLE_API_KEY` | If using Google | API key for Gemini and the embedding model.                                                        |
| `GROQ_API_KEY`   | If using Groq   | API key for Groq models.                                                                            |
| `LLM_PROVIDER`   | No              | One of `openai`, `google`, `groq`. Must match a key under `llm` in the YAML. Defaults to `openai`. |
| `CONFIG_PATH`    | No              | Explicit path to the configuration file. Overrides the default location.                           |

### Configuration file

Model and retrieval settings live in [`config/configuration.yaml`](config/configuration.yaml):

```yaml
embedding_model:
  provider: "google"
  model_name: "models/text-embedding-004"

retriever:
  top_k: 4

llm:
  groq:
    provider: "groq"
    model_name: "deepseek-r1-distill-llama-70b"
  google:
    provider: "google"
    model_name: "gemini-2.0-flash"
  openai:
    provider: "openai"
    model_name: "gpt-4o"
```

The embedding provider is fixed to Google; only the LLM provider is switchable via `LLM_PROVIDER`.

## Usage

Run modules from the project root so the package imports resolve:

```bash
# Load and print the parsed configuration
venv/bin/python -m utils.config_loader

# Exercise embedding + LLM loading (requires API keys)
venv/bin/python -m utils.model_loader
```

Loading models programmatically:

```python
from utils.model_loader import ModelLoader

loader = ModelLoader()
embeddings = loader.load_embeddings()   # GoogleGenerativeAIEmbeddings
llm = loader.load_llm()                 # provider chosen by LLM_PROVIDER

response = llm.invoke("Summarize the latest research on retrieval-augmented generation.")
print(response.content)
```

## Project structure

```
synapse_AI_Agent/
├── config/
│   └── configuration.yaml      # Model, embedding, and retriever settings
├── exception/
│   └── custom_exception.py     # ResearchAnalystException wrapper
├── log/
│   ├── __init__.py             # Shared GLOBAL_LOGGER instance
│   └── logger.py               # structlog + stdlib logging configuration
├── utils/
│   ├── config_loader.py        # Single source of truth for loading the YAML
│   └── model_loader.py         # ApiKeyManager + ModelLoader (LLMs & embeddings)
├── main.py                     # Placeholder entry point
└── pyproject.toml
```

## Adding a new LLM provider

1. Add a provider block under `llm` in `config/configuration.yaml`.
2. Add a matching branch in `ModelLoader.load_llm()` in `utils/model_loader.py`.
3. Add any new API key to `ApiKeyManager`.

## License

No license has been specified for this project yet.
