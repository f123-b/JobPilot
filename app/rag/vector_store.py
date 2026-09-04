from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .. import db
from ..config import settings
from ..services.embeddings import cosine_similarity, embed_text
from .chunking import TextChunk


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    user_id: str
    source_id: str
    chunk_index: int
    section: str
    content: str
    score: float
    embedding_backend: str
    metadata: dict[str, Any]


class ResumeVectorStore:
    """Resume vector store with optional Postgres/pgvector and SQLite fallback.

    `VECTOR_BACKEND=postgres` activates pgvector when POSTGRES_URL is configured.
    `auto` tries pgvector and falls back to SQLite if the optional service is absent.
    """

    def __init__(self) -> None:
        self.backend = settings.vector_backend

    async def _postgres_ready(self) -> bool:
        return bool(settings.postgres_url and self.backend in {"auto", "postgres"})

    async def _pg_connect(self):
        import psycopg
        from pgvector.psycopg import register_vector_async

        conn = await psycopg.AsyncConnection.connect(settings.postgres_url, autocommit=True)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await register_vector_async(conn)
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS resume_chunks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding vector({settings.vector_dim}) NOT NULL,
                embedding_backend TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_resume_chunks_user ON resume_chunks(user_id, source_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_resume_chunks_embedding_hnsw "
            "ON resume_chunks USING hnsw (embedding vector_cosine_ops)"
        )
        return conn

    async def replace_chunks(
        self,
        *,
        user_id: str,
        source_id: str,
        chunks: list[TextChunk],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        embedded: list[tuple[TextChunk, list[float], str]] = []
        for chunk in chunks:
            vector, backend = await embed_text(chunk.content)
            embedded.append((chunk, vector, backend))

        if await self._postgres_ready():
            try:
                from pgvector import Vector
                from psycopg.types.json import Jsonb

                conn = await self._pg_connect()
                try:
                    await conn.execute("DELETE FROM resume_chunks WHERE user_id=%s AND source_id=%s", (user_id, source_id))
                    for chunk, vector, embedding_backend in embedded:
                        chunk_id = f"{user_id}:{source_id}:{chunk.chunk_index}"
                        await conn.execute(
                            """INSERT INTO resume_chunks
                               (id,user_id,source_id,chunk_index,section,content,embedding,embedding_backend,metadata)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (
                                chunk_id,
                                user_id,
                                source_id,
                                chunk.chunk_index,
                                chunk.section,
                                chunk.content,
                                Vector(vector),
                                embedding_backend,
                                Jsonb(metadata),
                            ),
                        )
                finally:
                    await conn.close()
                return {"backend": "postgres-pgvector", "chunks": len(embedded), "source_id": source_id}
            except Exception:
                if self.backend == "postgres":
                    raise

        db.replace_resume_chunks(user_id=user_id, source_id=source_id, items=[
            {
                "chunk_index": chunk.chunk_index,
                "section": chunk.section,
                "content": chunk.content,
                "embedding": vector,
                "embedding_backend": embedding_backend,
                "metadata": metadata,
            }
            for chunk, vector, embedding_backend in embedded
        ])
        return {"backend": "sqlite-local-vector", "chunks": len(embedded), "source_id": source_id}

    async def search(self, *, user_id: str, query: str, top_k: int = 5, source_id: str | None = None) -> list[RetrievedChunk]:
        query_vector, _ = await embed_text(query)
        limit = max(1, min(top_k, 20))

        if await self._postgres_ready():
            try:
                from pgvector import Vector

                conn = await self._pg_connect()
                try:
                    if source_id:
                        cur = await conn.execute(
                            """SELECT id,user_id,source_id,chunk_index,section,content,
                                      1 - (embedding <=> %s) AS score, embedding_backend, metadata
                               FROM resume_chunks WHERE user_id=%s AND source_id=%s
                               ORDER BY embedding <=> %s LIMIT %s""",
                            (Vector(query_vector), user_id, source_id, Vector(query_vector), limit),
                        )
                    else:
                        cur = await conn.execute(
                            """SELECT id,user_id,source_id,chunk_index,section,content,
                                      1 - (embedding <=> %s) AS score, embedding_backend, metadata
                               FROM resume_chunks WHERE user_id=%s
                               ORDER BY embedding <=> %s LIMIT %s""",
                            (Vector(query_vector), user_id, Vector(query_vector), limit),
                        )
                    rows = await cur.fetchall()
                finally:
                    await conn.close()
                return [
                    RetrievedChunk(
                        id=str(row[0]), user_id=row[1], source_id=row[2], chunk_index=row[3],
                        section=row[4], content=row[5], score=float(row[6] or 0),
                        embedding_backend=row[7], metadata=row[8] if isinstance(row[8], dict) else {},
                    )
                    for row in rows
                ]
            except Exception:
                if self.backend == "postgres":
                    raise

        scored: list[RetrievedChunk] = []
        for row in db.list_resume_chunks(user_id=user_id, source_id=source_id):
            vector = row.get("embedding") or []
            score = cosine_similarity(query_vector, vector)
            scored.append(RetrievedChunk(
                id=str(row["id"]), user_id=row["user_id"], source_id=row["source_id"],
                chunk_index=row["chunk_index"], section=row["section"], content=row["content"],
                score=score, embedding_backend=row.get("embedding_backend") or "unknown",
                metadata=row.get("metadata") or {},
            ))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]


resume_vector_store = ResumeVectorStore()
