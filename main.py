"""Command-line entry point for the Synapse AI research/analyst agent.

Run from the project root:

    python main.py --prompt "Summarize recent advances in RAG"
    python main.py                       # interactive REPL
    python main.py --provider groq       # override LLM_PROVIDER for this run
    python main.py --show-config         # print the resolved configuration and exit

The selected LLM provider comes from the ``LLM_PROVIDER`` environment variable
(default ``openai``); ``--provider`` overrides it for the current process.
"""

import os
import sys
import json
import argparse

from langchain_core.messages import SystemMessage, HumanMessage

from log import GLOBAL_LOGGER as log
from exception.custom_exception import ResearchAnalystException
from utils.config_loader import load_config
from utils.model_loader import ModelLoader

SYSTEM_PROMPT = (
    "You are Synapse, a meticulous research and analyst assistant. "
    "Answer with well-structured, factual analysis. When you are uncertain "
    "or lack the information to answer, say so plainly rather than guessing."
)


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="synapse-ai-agent",
        description="Synapse AI research/analyst agent.",
    )
    parser.add_argument(
        "-p",
        "--prompt",
        help="Run a single query and exit. If omitted, an interactive REPL starts.",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "google", "groq"],
        help="LLM provider to use (overrides the LLM_PROVIDER environment variable).",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print the resolved configuration as JSON and exit.",
    )
    return parser


def answer(llm, prompt: str) -> str:
    """Send a single prompt to the LLM and return its text response."""
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    response = llm.invoke(messages)
    return response.content


def run_repl(llm) -> None:
    """Run an interactive read-eval-print loop until the user exits."""
    print("Synapse AI agent ready. Type your question, or 'exit'/'quit' to leave.\n")
    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()  # newline after ^C/^D
            break

        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            break

        try:
            print(f"\nsynapse> {answer(llm, prompt)}\n")
        except Exception as e:  # keep the session alive on a single failed turn
            log.error("Failed to generate a response", error=str(e))
            print("synapse> Sorry, I couldn't process that request. See logs for details.\n")

    log.info("Interactive session ended")


def main(argv: list[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    try:
        if args.show_config:
            print(json.dumps(load_config(), indent=2))
            return 0

        log.info("Starting Synapse AI agent", provider=os.getenv("LLM_PROVIDER", "openai"))
        llm = ModelLoader().load_llm()

        if args.prompt:
            print(answer(llm, args.prompt))
        else:
            run_repl(llm)

        return 0

    except ResearchAnalystException as e:
        log.error("Agent failed", error=str(e))
        print(f"Error: {e.error_message}", file=sys.stderr)
        return 1
    except Exception as e:
        wrapped = ResearchAnalystException("Unexpected failure in main", e)
        log.error("Agent crashed", error=str(wrapped))
        print(f"Error: {wrapped.error_message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
