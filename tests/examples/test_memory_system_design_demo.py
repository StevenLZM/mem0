from datetime import datetime, timedelta, timezone

import pytest

from examples.memory_system_design_demo import (
    MemoryEngine,
    MemoryInput,
    Scope,
    run_demo,
)


NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def test_scope_requires_at_least_one_owner():
    with pytest.raises(ValueError, match="at least one"):
        Scope()


def test_scope_rejects_whitespace_only_owner():
    with pytest.raises(ValueError, match="whitespace-only"):
        Scope(user_id="   ")


def test_scope_normalizes_surrounding_whitespace():
    scope = Scope(user_id=" alice ", agent_id=" coding-agent ")

    assert scope.user_id == "alice"
    assert scope.agent_id == "coding-agent"


def test_scope_rejects_internal_whitespace_like_mem0():
    with pytest.raises(ValueError, match="cannot contain whitespace"):
        Scope(user_id="alice smith")


def test_add_deduplicates_within_scope_but_not_across_users():
    engine = MemoryEngine()
    memory = MemoryInput("User prefers Python examples", entities=("Python",))

    first = engine.add(memory, Scope(user_id="alice"), now=NOW)
    duplicate = engine.add(memory, Scope(user_id="alice"), now=NOW)
    other_user = engine.add(memory, Scope(user_id="bob"), now=NOW)

    assert duplicate.id == first.id
    assert other_user.id != first.id
    assert len(engine.records) == 2


def test_add_recreates_same_text_after_existing_memory_expires():
    engine = MemoryEngine()
    scope = Scope(user_id="alice")
    original = engine.add(
        MemoryInput("Temporary debugging context", expires_at=NOW + timedelta(hours=1)),
        scope,
        now=NOW,
    )
    readded_at = NOW + timedelta(hours=2)
    replacement_expires_at = readded_at + timedelta(hours=3)

    replacement = engine.add(
        MemoryInput("Temporary debugging context", expires_at=replacement_expires_at),
        scope,
        now=readded_at,
    )

    assert replacement.id != original.id
    assert replacement.expires_at == replacement_expires_at
    assert [hit.record.id for hit in engine.search("debugging context", scope, now=readded_at)] == [replacement.id]
    assert [event.event for event in engine.history(replacement.id)] == ["ADD"]
    assert engine.search("debugging context", scope, now=replacement_expires_at + timedelta(seconds=1)) == []


def test_add_deduplicates_when_expiration_equals_now():
    engine = MemoryEngine()
    scope = Scope(user_id="alice")
    expires_at = NOW + timedelta(hours=1)
    original = engine.add(
        MemoryInput("Boundary debugging context", expires_at=expires_at),
        scope,
        now=NOW,
    )

    duplicate = engine.add(
        MemoryInput("Boundary debugging context", expires_at=expires_at + timedelta(hours=2)),
        scope,
        now=expires_at,
    )

    assert duplicate.id == original.id
    assert duplicate.expires_at == expires_at


def test_search_combines_semantic_keyword_and_entity_signals():
    engine = MemoryEngine()
    scope = Scope(user_id="alice")
    engine.add(
        MemoryInput("Project uses Qdrant vector database", entities=("Qdrant", "Mem0")),
        scope,
        now=NOW,
    )
    engine.add(MemoryInput("User prefers concise explanations", entities=("Alice",)), scope, now=NOW)

    hits = engine.search(
        "Which vector database does the project use? Qdrant",
        scope,
        query_entities=("Qdrant",),
        explain=True,
        now=NOW,
    )

    assert hits[0].record.text == "Project uses Qdrant vector database"
    assert hits[0].details is not None
    assert hits[0].details.semantic_score > 0
    assert hits[0].details.keyword_score > 0
    assert hits[0].details.entity_boost == pytest.approx(0.5)


def test_search_isolates_results_across_users():
    engine = MemoryEngine()
    alice = engine.add(MemoryInput("Private Python preference"), Scope(user_id="alice"), now=NOW)
    bob = engine.add(MemoryInput("Private Python preference"), Scope(user_id="bob"), now=NOW)

    alice_hits = engine.search("Private Python preference", Scope(user_id="alice"), now=NOW)

    assert [hit.record.id for hit in alice_hits] == [alice.id]
    assert bob.id not in {hit.record.id for hit in alice_hits}


def test_semantic_threshold_runs_before_keyword_boost():
    class OrthogonalEmbedder:
        def embed(self, text: str) -> tuple[float, ...]:
            return (1.0, 0.0) if text == "python" else (0.0, 1.0)

    engine = MemoryEngine(embedder=OrthogonalEmbedder())
    scope = Scope(user_id="alice")
    engine.add(MemoryInput("python"), scope, now=NOW)

    assert engine.search("python", scope, threshold=0.1, now=NOW)
    assert engine.search("different query", scope, threshold=0.1, now=NOW) == []


def test_expired_memories_are_hidden():
    engine = MemoryEngine()
    scope = Scope(run_id="debug-session")
    engine.add(
        MemoryInput("Temporary debugging context", expires_at=NOW + timedelta(hours=1)),
        scope,
        now=NOW,
    )

    assert engine.search("debugging context", scope, now=NOW)
    assert engine.search("debugging context", scope, now=NOW + timedelta(hours=2)) == []


def test_update_and_delete_append_history():
    engine = MemoryEngine()
    scope = Scope(user_id="alice")
    record = engine.add(MemoryInput("Project uses Redis", entities=("Redis",)), scope, now=NOW)

    updated = engine.update(
        record.id,
        text="New project uses pgvector",
        entities=("pgvector",),
        now=NOW + timedelta(minutes=1),
    )
    engine.delete(record.id, now=NOW + timedelta(minutes=2))

    assert updated.created_at == NOW
    assert [event.event for event in engine.history(record.id)] == ["ADD", "UPDATE", "DELETE"]
    assert record.id not in engine.records


def test_demo_output_explains_ranking(capsys):
    run_demo()
    output = capsys.readouterr().out

    assert "AI coding assistant memory demo" in output
    assert "semantic=" in output
    assert "keyword=" in output
    assert "entity=" in output
