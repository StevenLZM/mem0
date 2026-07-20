"""A deterministic teaching model of a memory system, not production code."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol


TOKEN_RE = re.compile(r"[a-zA-Z0-9_+#.-]+")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def tokenize(text: str) -> frozenset[str]:
    return frozenset(token.lower() for token in TOKEN_RE.findall(text))


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, min(dot / (left_norm * right_norm), 1.0))


class Embedder(Protocol):
    def embed(self, text: str) -> tuple[float, ...]: ...


class DeterministicEmbedder:
    def __init__(self, dimensions: int = 64):
        self.dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


@dataclass(frozen=True)
class Scope:
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("user_id", "agent_id", "run_id"):
            value = getattr(self, field_name)
            if value is None:
                continue
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot be empty or whitespace-only")
            if any(character.isspace() for character in normalized):
                raise ValueError(f"{field_name} cannot contain whitespace")
            object.__setattr__(self, field_name, normalized)
        if not any((self.user_id, self.agent_id, self.run_id)):
            raise ValueError("at least one scope id is required")

    def contains(self, other: "Scope") -> bool:
        return all(
            expected is None or expected == actual
            for expected, actual in (
                (self.user_id, other.user_id),
                (self.agent_id, other.agent_id),
                (self.run_id, other.run_id),
            )
        )


@dataclass(frozen=True)
class MemoryInput:
    text: str
    memory_type: str = "semantic"
    entities: tuple[str, ...] = ()
    expires_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    text: str
    memory_type: str
    scope: Scope
    vector: tuple[float, ...]
    keywords: frozenset[str]
    entities: frozenset[str]
    content_hash: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    metadata: dict[str, object]


@dataclass(frozen=True)
class HistoryEvent:
    memory_id: str
    event: str
    old_text: str | None
    new_text: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class ScoreDetails:
    semantic_score: float
    keyword_score: float
    entity_boost: float
    max_possible_score: float
    final_score: float


@dataclass(frozen=True)
class SearchHit:
    record: MemoryRecord
    score: float
    details: ScoreDetails | None = None


class MemoryEngine:
    """Trusted teaching engine; its ID-only methods are not multi-tenant APIs."""

    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or DeterministicEmbedder()
        self.records: dict[str, MemoryRecord] = {}
        self.events: list[HistoryEvent] = []
        self._next_id = 1

    def add(
        self,
        memory: MemoryInput,
        scope: Scope,
        *,
        now: datetime | None = None,
    ) -> MemoryRecord:
        current_time = now or datetime.now(timezone.utc)
        normalized = normalize_text(memory.text)
        content_hash = hashlib.md5(normalized.encode()).hexdigest()
        for record in self.records.values():
            if record.expires_at is not None and record.expires_at < current_time:
                continue
            if record.scope == scope and record.content_hash == content_hash:
                return record

        memory_id = f"mem-{self._next_id:04d}"
        self._next_id += 1
        record = MemoryRecord(
            id=memory_id,
            text=memory.text,
            memory_type=memory.memory_type,
            scope=scope,
            vector=self.embedder.embed(memory.text),
            keywords=tokenize(memory.text),
            entities=frozenset(normalize_text(entity) for entity in memory.entities),
            content_hash=content_hash,
            created_at=current_time,
            updated_at=current_time,
            expires_at=memory.expires_at,
            metadata=dict(memory.metadata),
        )
        self.records[memory_id] = record
        self.events.append(HistoryEvent(memory_id, "ADD", None, record.text, current_time))
        return record

    def search(
        self,
        query: str,
        scope: Scope,
        *,
        top_k: int = 5,
        threshold: float = 0.0,
        query_entities: tuple[str, ...] = (),
        explain: bool = False,
        now: datetime | None = None,
    ) -> list[SearchHit]:
        current_time = now or datetime.now(timezone.utc)
        query_vector = self.embedder.embed(query)
        query_keywords = tokenize(query)
        normalized_entities = frozenset(normalize_text(entity) for entity in query_entities)
        has_keyword_signal = bool(query_keywords)
        has_entity_signal = bool(normalized_entities)
        max_possible = 1.0 + float(has_keyword_signal) + (0.5 if has_entity_signal else 0.0)
        hits: list[SearchHit] = []

        for record in self.records.values():
            if not scope.contains(record.scope):
                continue
            if record.expires_at is not None and record.expires_at < current_time:
                continue

            semantic = cosine(query_vector, record.vector)
            if semantic < threshold:
                continue
            keyword = len(query_keywords & record.keywords) / len(query_keywords) if query_keywords else 0.0
            entity = 0.5 if normalized_entities & record.entities else 0.0
            final = min((semantic + keyword + entity) / max_possible, 1.0)
            details = ScoreDetails(semantic, keyword, entity, max_possible, final) if explain else None
            hits.append(SearchHit(record, final, details))

        hits.sort(key=lambda hit: (-hit.score, hit.record.id))
        return hits[:top_k]

    def update(
        self,
        memory_id: str,
        *,
        text: str,
        entities: tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> MemoryRecord:
        current_time = now or datetime.now(timezone.utc)
        old = self.records[memory_id]
        normalized = normalize_text(text)
        updated = replace(
            old,
            text=text,
            vector=self.embedder.embed(text),
            keywords=tokenize(text),
            entities=(
                frozenset(normalize_text(entity) for entity in entities) if entities is not None else old.entities
            ),
            content_hash=hashlib.md5(normalized.encode()).hexdigest(),
            updated_at=current_time,
        )
        self.records[memory_id] = updated
        self.events.append(HistoryEvent(memory_id, "UPDATE", old.text, updated.text, current_time))
        return updated

    def delete(self, memory_id: str, *, now: datetime | None = None) -> None:
        current_time = now or datetime.now(timezone.utc)
        old = self.records.pop(memory_id)
        self.events.append(HistoryEvent(memory_id, "DELETE", old.text, None, current_time))

    def history(self, memory_id: str) -> list[HistoryEvent]:
        return [event for event in self.events if event.memory_id == memory_id]


def run_demo() -> None:
    now = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    engine = MemoryEngine()
    user_scope = Scope(user_id="alice")
    engine.add(
        MemoryInput("User prefers Python examples", entities=("Python",)),
        user_scope,
        now=now,
    )
    engine.add(
        MemoryInput("Mem0 project uses Qdrant vector database", entities=("Mem0", "Qdrant")),
        user_scope,
        now=now,
    )
    engine.add(
        MemoryInput(
            "Current task is debugging hybrid retrieval",
            memory_type="working",
            entities=("Mem0",),
            expires_at=now + timedelta(hours=2),
        ),
        Scope(run_id="retrieval-debug"),
        now=now,
    )

    hits = engine.search(
        "Which vector database does Mem0 use? Qdrant",
        user_scope,
        query_entities=("Mem0", "Qdrant"),
        explain=True,
        now=now,
    )
    print("AI coding assistant memory demo")
    for hit in hits:
        details = hit.details
        assert details is not None
        print(
            f"{hit.record.id}: {hit.record.text} | final={hit.score:.3f} "
            f"semantic={details.semantic_score:.3f} "
            f"keyword={details.keyword_score:.3f} entity={details.entity_boost:.3f}"
        )


if __name__ == "__main__":
    run_demo()
