"""SQLite checkpointer factory for the LangGraph StateGraph.

Wraps ``langgraph.checkpoint.sqlite.SqliteSaver`` so the graph can persist state
per thread_id, survive process restarts, and resume from human-in-the-loop
interrupts. DB path read from configuration.yaml via utils.config_loader.

Intended API:
    def get_checkpointer() -> BaseCheckpointSaver: ...

Owner: backend-developer (path/ops config: cloud-developer)
"""

# TODO(backend-developer): implement get_checkpointer().
