from __future__ import annotations

from contextlib import asynccontextmanager

from ..config import settings


@asynccontextmanager
async def checkpoint_context():
    """Yield a LangGraph checkpointer.

    Production: AsyncPostgresSaver when POSTGRES_URL is configured.
    Development: AsyncSqliteSaver on a local file.
    Minimal fallback: InMemorySaver if optional checkpoint packages are absent.
    """
    if settings.postgres_url and settings.checkpoint_backend in {"auto", "postgres"}:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            async with AsyncPostgresSaver.from_conn_string(settings.postgres_url) as saver:
                await saver.setup()
                yield saver
                return
        except Exception:
            if settings.checkpoint_backend == "postgres":
                raise

    if settings.checkpoint_backend in {"auto", "sqlite"}:
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
                yield saver
                return
        except Exception:
            if settings.checkpoint_backend == "sqlite":
                raise

    from langgraph.checkpoint.memory import InMemorySaver

    yield InMemorySaver()
