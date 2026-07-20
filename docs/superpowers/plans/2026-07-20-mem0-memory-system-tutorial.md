# Mem0 Memory System Tutorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a detailed Chinese tutorial that teaches transferable memory-system design methods through a minimal Python implementation and precise comparisons with the current Mem0 Python OSS SDK.

**Architecture:** The tutorial follows one AI coding-assistant case from first principles through classification, write, retrieval, lifecycle, production trade-offs, evaluation, and interviews. A standard-library-only companion module provides deterministic behavior for the algorithms; the document labels conceptual pseudocode, teaching code, and real Mem0 source separately and treats live DeepSeek/Qdrant use as optional.

**Tech Stack:** Markdown, Mermaid, Python 3.10+, Python standard library, pytest, Ruff, current Mem0 Python OSS source.

## Global Constraints

- The default reader has backend system-design, RAG, vector-retrieval, LLM, and harness-engineering experience but no prior Mem0 knowledge.
- Explain every complex idea in the order: intuition, model, alternatives, selected design, data flow, teaching implementation, Mem0 source, trade-offs, exercises.
- Use Chinese prose; preserve source symbols and standard industry terms in English.
- Keep the Python OSS SDK as the source-code focus; use TypeScript, Server, OpenMemory, plugins, and Hosted Platform only to explain boundaries.
- Label every code block as `概念伪代码`, `教学实现`, or `Mem0 源码`.
- The companion demo must run on Python 3.10+ with the standard library only and must not require DeepSeek, Qdrant, network access, or an API key.
- Never include a real API key, credential, or personal sensitive value.
- Do not claim OSS support for `timestamp`, `reference_date`, full temporal reasoning, or decay; distinguish `expiration_date` from Platform-only capabilities.
- Accurately describe the current V3 `infer=True` path as ADD-only while retaining explicit `update()` and `delete()` APIs.
- Accurately describe the current retrieval restriction: semantic threshold gates before fusion, and BM25/entity signals boost semantic candidates rather than adding independent candidates.
- Target 30,000-50,000 Chinese characters for the main tutorial.
- Do not register this standalone `.md` tutorial in Mintlify navigation or modify `docs/docs.json`/`docs/llms.txt`.

## File Map

- Create `examples/memory_system_design_demo.py`: deterministic, standard-library teaching implementation and CLI demonstration.
- Create `tests/examples/test_memory_system_design_demo.py`: behavior tests for scope, deduplication, fusion, expiration, update/delete history, and CLI output.
- Create `docs/learning/mem0-memory-system-design.zh-CN.md`: complete Chinese tutorial with diagrams, source cross-references, exercises, and interview analysis.
- Reference without modifying `mem0/memory/main.py`, `mem0/memory/storage.py`, `mem0/configs/enums.py`, `mem0/configs/base.py`, `mem0/configs/prompts.py`, `mem0/utils/factory.py`, `mem0/utils/scoring.py`, `mem0/utils/entity_extraction.py`, `mem0/utils/lemmatization.py`, `mem0/vector_stores/base.py`, `mem0/llms/base.py`, and `mem0/embeddings/base.py`.

---

### Task 1: Build the deterministic teaching engine

**Files:**
- Create: `examples/memory_system_design_demo.py`
- Create: `tests/examples/test_memory_system_design_demo.py`

**Interfaces:**
- Consumes: Python 3.10+ standard library only.
- Produces: `Scope`, `MemoryInput`, `MemoryRecord`, `HistoryEvent`, `ScoreDetails`, `SearchHit`, `DeterministicEmbedder`, `MemoryEngine`, and `run_demo()`.
- `MemoryEngine.add(memory: MemoryInput, scope: Scope, *, now: datetime | None = None) -> MemoryRecord`
- `MemoryEngine.search(query: str, scope: Scope, *, top_k: int = 5, threshold: float = 0.0, query_entities: tuple[str, ...] = (), explain: bool = False, now: datetime | None = None) -> list[SearchHit]`
- `MemoryEngine.update(memory_id: str, *, text: str, entities: tuple[str, ...] | None = None, now: datetime | None = None) -> MemoryRecord`
- `MemoryEngine.delete(memory_id: str, *, now: datetime | None = None) -> None`
- `MemoryEngine.history(memory_id: str) -> list[HistoryEvent]`

- [ ] **Step 1: Write behavior tests before the implementation**

Create `tests/examples/test_memory_system_design_demo.py` with these complete tests:

```python
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


def test_add_deduplicates_within_scope_but_not_across_users():
    engine = MemoryEngine()
    memory = MemoryInput("User prefers Python examples", entities=("Python",))

    first = engine.add(memory, Scope(user_id="alice"), now=NOW)
    duplicate = engine.add(memory, Scope(user_id="alice"), now=NOW)
    other_user = engine.add(memory, Scope(user_id="bob"), now=NOW)

    assert duplicate.id == first.id
    assert other_user.id != first.id
    assert len(engine.records) == 2


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
```

- [ ] **Step 2: Run the tests and confirm the missing module failure**

Run:

```bash
conda run -n mem0 python -m pytest tests/examples/test_memory_system_design_demo.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'examples.memory_system_design_demo'`.

- [ ] **Step 3: Implement the complete teaching engine**

Create `examples/memory_system_design_demo.py` with the following implementation. Keep the opening warning so readers do not confuse the demo with a production engine.

```python
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
            keyword = (
                len(query_keywords & record.keywords) / len(query_keywords)
                if query_keywords
                else 0.0
            )
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
                frozenset(normalize_text(entity) for entity in entities)
                if entities is not None
                else old.entities
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
```

- [ ] **Step 4: Run unit tests and the demo**

Run:

```bash
conda run -n mem0 python -m pytest tests/examples/test_memory_system_design_demo.py -q
conda run -n mem0 python examples/memory_system_design_demo.py
```

Expected: `7 passed`; demo output begins with `AI coding assistant memory demo` and prints semantic, keyword, and entity components.

- [ ] **Step 5: Run formatting and lint checks**

Run:

```bash
conda run -n mem0 ruff format --check examples/memory_system_design_demo.py tests/examples/test_memory_system_design_demo.py
conda run -n mem0 ruff check examples/memory_system_design_demo.py tests/examples/test_memory_system_design_demo.py
```

Expected: both commands exit 0. If format check fails, run `conda run -n mem0 ruff format` on the two exact files, then repeat both checks.

- [ ] **Step 6: Commit the teaching engine**

```bash
git add examples/memory_system_design_demo.py tests/examples/test_memory_system_design_demo.py
git commit -m "docs: add deterministic memory system demo"
```

---

### Task 2: Write the conceptual foundation and architecture chapters

**Files:**
- Create: `docs/learning/mem0-memory-system-design.zh-CN.md`
- Reference: `README.md`
- Reference: `AGENTS.md`
- Reference: `mem0/__init__.py`
- Reference: `mem0/configs/enums.py`
- Reference: `mem0/configs/base.py`
- Reference: `mem0/utils/factory.py`
- Reference: `mem0/vector_stores/base.py`
- Reference: `mem0/llms/base.py`
- Reference: `mem0/embeddings/base.py`

**Interfaces:**
- Consumes: the audience, teaching method, case, and scope from the approved design spec.
- Produces: Chapters 1-5 and stable anchors `#chapter-1` through `#chapter-5` for later chapters.

- [ ] **Step 1: Create the tutorial shell and Chapters 1-5**

Create `docs/learning/mem0-memory-system-design.zh-CN.md` with this exact top-level structure and complete prose under every listed subsection:

```markdown
# 从第一性原理到 Mem0 源码：长期记忆系统设计教程

> 本教程面向具备后端、RAG 与 Agent harness 基础的读者。运行项目不是学习终点；目标是掌握可迁移的记忆系统设计方法。

## 1. 导读：如何学习一个记忆系统 {#chapter-1}
### 1.1 学习目标与贯穿案例
### 1.2 三类代码标记
### 1.3 推荐阅读路线

## 2. 从第一性原理理解记忆 {#chapter-2}
### 2.1 为什么上下文窗口不是长期记忆
### 2.2 聊天记录、缓存、RAG、画像、事件日志与记忆
### 2.3 记忆系统的五个动作：选择、压缩、组织、召回、遗忘
### 2.4 从业务约束推导系统不变量
### 2.5 本章练习与面试思考

## 3. 记忆分类与设计选型 {#chapter-3}
### 3.1 按功能：工作、语义、情景与程序记忆
### 3.2 按归属：User、Agent、Run 与 Organization
### 3.3 按表示：事件、摘要、原子事实、实体关系与步骤
### 3.4 按生命周期：瞬时、TTL、长期、衰减与审计
### 3.5 按检索：精确、向量、关键词、实体、图与混合检索
### 3.6 选型矩阵与决策树
### 3.7 Mem0 理论分类与当前 API 能力的差异
### 3.8 本章练习与面试思考

## 4. Mem0 的宏观架构 {#chapter-4}
### 4.1 Monorepo 地图
### 4.2 OSS Library、Server、OpenMemory 与 Platform
### 4.3 Memory 的组件组合
### 4.4 Provider Factory 与依赖倒置
### 4.5 同步与异步接口
### 4.6 本章练习与面试思考

## 5. 核心数据模型与系统不变量 {#chapter-5}
### 5.1 Message、Memory、Entity 与 History
### 5.2 user_id、agent_id、run_id 与 actor_id
### 5.3 内容、hash、关键词、向量、时间与元数据
### 5.4 主集合、实体集合和 SQLite 辅助状态
### 5.5 多租户隔离与作用域不变量
### 5.6 本章练习与面试思考
```

Required content for these chapters:

- Use a boundary comparison table covering purpose, source of truth, write policy, retrieval, lifetime, and failure impact for context window, transcript, cache, RAG corpus, profile, event log, and long-term memory.
- State the five design questions: what is memorable, how represented, who owns it, how retrieved, when forgotten.
- Include a two-dimensional memory classification matrix and a decision tree in Mermaid.
- Explain `MemoryType.SEMANTIC`, `EPISODIC`, and `PROCEDURAL`, then cite the explicit procedural branch in `Memory.add()`.
- Include a Mermaid component diagram showing `Memory` composing LLM, Embedder, Vector Store, optional Reranker, SQLite history/recent messages, and lazy Entity Store.
- Include a repository boundary table for `mem0/`, `mem0-ts/`, `server/`, `openmemory/`, CLIs, integrations, and docs.
- Explain factory creation from `Memory.__init__()` and the contracts in the three base classes.
- Include an ownership table distinguishing scope IDs, `actor_id`, `role`, and `attributed_to`.
- Explain that vector memory, entity records, history, and recent messages are separate stores without a shared transaction.
- End every chapter with at least three exercises: one code-reading question, one design-decision question, and one interview question.

- [ ] **Step 2: Check structure and minimum depth**

Run:

```bash
rg -n '^## [1-5]\.' docs/learning/mem0-memory-system-design.zh-CN.md
rg -n 'MemoryType|user_id|agent_id|run_id|actor_id|Provider|VectorStoreBase|SQLiteManager' docs/learning/mem0-memory-system-design.zh-CN.md
wc -m docs/learning/mem0-memory-system-design.zh-CN.md
```

Expected: exactly five numbered top-level chapter matches; all required source terms appear; character count is at least 9,000 at this stage.

- [ ] **Step 3: Verify every source claim against the current files**

Run:

```bash
rg -n 'class MemoryType|class MemoryConfig' mem0/configs/enums.py mem0/configs/base.py
rg -n 'class (LlmFactory|EmbedderFactory|VectorStoreFactory|RerankerFactory)' mem0/utils/factory.py
rg -n '^class (LLMBase|EmbeddingBase|VectorStoreBase)' mem0/llms/base.py mem0/embeddings/base.py mem0/vector_stores/base.py
rg -n '^class Memory|def __init__|def entity_store' mem0/memory/main.py
```

Expected: every symbol referenced in Chapters 3-5 has a current source definition. Correct the prose immediately if a source symbol or behavior differs.

- [ ] **Step 4: Commit Chapters 1-5**

```bash
git add docs/learning/mem0-memory-system-design.zh-CN.md
git commit -m "docs: explain memory system foundations"
```

---

### Task 3: Write the complete memory lifecycle chapters

**Files:**
- Modify: `docs/learning/mem0-memory-system-design.zh-CN.md`
- Reference: `mem0/memory/main.py`
- Reference: `mem0/memory/storage.py`
- Reference: `mem0/configs/prompts.py`
- Reference: `mem0/utils/scoring.py`
- Reference: `mem0/utils/entity_extraction.py`
- Reference: `mem0/utils/lemmatization.py`
- Reference: `mem0/vector_stores/base.py`

**Interfaces:**
- Consumes: terminology, component boundaries, scope model, and case from Chapters 1-5.
- Produces: Chapters 6-8 with anchors `#chapter-6` through `#chapter-8`, exact write/retrieval formulas, and lifecycle state transitions used by Chapter 9.

- [ ] **Step 1: Add Chapter 6, the write lifecycle**

Append this section hierarchy and fully explain every item using the AI coding-assistant case:

```markdown
## 6. 写入生命周期：从对话到长期记忆 {#chapter-6}
### 6.1 写入前先定义不变量
### 6.2 Memory.add 的入口校验与三条分支
### 6.3 Phase 0-2：上下文、已有记忆与单次 LLM 抽取
### 6.4 Phase 3-6：批量 Embedding、hash 去重与持久化
### 6.5 Phase 7-8：实体关联、最近消息与返回值
### 6.6 ADD-only 与手动 UPDATE/DELETE 并不矛盾
### 6.7 部分失败、降级与一致性分析
### 6.8 教学伪代码与 Mem0 源码对照
### 6.9 本章练习与面试思考
```

Required source facts:

- Show the call chain `Memory.add()` → `_build_filters_and_metadata()` → `_add_to_vector_store()`.
- Explain `infer=False`, procedural memory, and V3 ADD-only branches separately.
- Explain the deterministic session-scope key and last-10-message SQLite window.
- Explain the existing-memory semantic lookup with `top_k=10` and UUID-to-small-integer mapping used to reduce LLM ID hallucination.
- Explain one-call JSON extraction, exception promotion to `LLMError`, parse fallback, and the distinction between no facts and provider failure.
- Explain batch Embedding, individual fallback, MD5 exact-text deduplication, BM25 lemmatized field, batch insert/history fallback, and best-effort entity indexing.
- Explicitly note that the prompt asks for `linked_memory_ids`, while the current persistence path builds a separate NLP-derived entity index and does not persist prompt-produced memory-to-memory links in the main memory payload.
- Include one Mermaid write sequence diagram and one partial-failure table.

- [ ] **Step 2: Add Chapter 7, the retrieval lifecycle**

Append:

```markdown
## 7. 检索生命周期：从查询到排序结果 {#chapter-7}
### 7.1 查询校验、作用域与高级过滤
### 7.2 查询预处理、Embedding 与过量召回
### 7.3 BM25 归一化
### 7.4 实体索引与关联记忆增益
### 7.5 融合公式、阈值和候选池限制
### 7.6 explain 与可选 reranker
### 7.7 真正多路召回与当前实现的对照
### 7.8 本章练习与面试思考
```

Derive the exact current formula in both prose and math:

```text
raw = semantic + normalized_bm25 + entity_boost
max_possible = 1.0 + (1.0 if BM25 active else 0.0) + (0.5 if entity active else 0.0)
final = min(raw / max_possible, 1.0)
```

Required source facts:

- `internal_limit = max(top_k * 4, 60)`.
- BM25 uses query-length-dependent sigmoid midpoint and steepness.
- Entity extraction is capped and deduplicated; entity match below `0.5` is ignored; boost weight is `0.5` and is reduced for highly connected entities.
- Expiration filtering happens before scoring.
- `semantic_score < threshold` excludes the candidate before other signals are added.
- Final candidates come from semantic results; keyword/entity results only provide keyed scores/boosts.
- Reranker failure falls back to original results.
- `explain=True` exposes signal components.
- Include a Mermaid retrieval flow, a numeric worked example, and a comparison table between weighted addition, RRF, learned-to-rank, and reranker-only designs.

- [ ] **Step 3: Add Chapter 8, update, forgetting, expiration, and history**

Append:

```markdown
## 8. 更新、遗忘、过期和历史 {#chapter-8}
### 8.1 新事实、冲突事实与显式更新
### 8.2 update 的重算范围
### 8.3 delete、delete_all 与 reset
### 8.4 expiration_date 与查询时过滤
### 8.5 历史审计与物理删除的冲突
### 8.6 OSS 与 Platform 时间能力边界
### 8.7 生命周期状态图
### 8.8 本章练习与面试思考
```

Required content:

- Explain recomputation of vector, hash, lemmatized text, `updated_at`, history, and entity links on text update.
- Explain immutable `actor_id` behavior.
- Explain entity cleanup on update/delete and why it is best-effort.
- Contrast scoped `delete_all()` with global `reset()`.
- State exactly that OSS rejects `timestamp` and `reference_date`, while supporting date-only `expiration_date` filtering; do not imply full temporal reasoning or decay.
- Include a state diagram with Active, Superseded, Expired, and Deleted conceptual states, clearly marking which are teaching concepts versus explicit current storage flags.
- Discuss GDPR-style deletion versus audit retention as a policy decision, not a behavior guaranteed by Mem0.

- [ ] **Step 4: Verify lifecycle claims and document depth**

Run:

```bash
rg -n '^## [6-8]\.' docs/learning/mem0-memory-system-design.zh-CN.md
rg -n 'V3 PHASED BATCH PIPELINE|internal_limit =|semantic_score < threshold|ENTITY_BOOST_WEIGHT|expiration_date|reference_date|timestamp' mem0/memory/main.py mem0/utils/scoring.py
rg -n 'ADD-only|linked_memory_ids|语义候选|部分失败|最终一致性' docs/learning/mem0-memory-system-design.zh-CN.md
wc -m docs/learning/mem0-memory-system-design.zh-CN.md
```

Expected: exactly three lifecycle chapter matches; every named implementation fact is present in source and tutorial; total document length is at least 20,000 characters.

- [ ] **Step 5: Commit lifecycle chapters**

```bash
git add docs/learning/mem0-memory-system-design.zh-CN.md
git commit -m "docs: trace mem0 memory lifecycle"
```

---

### Task 4: Teach the design by rebuilding it in five versions

**Files:**
- Modify: `docs/learning/mem0-memory-system-design.zh-CN.md`
- Reference: `examples/memory_system_design_demo.py`
- Reference: `tests/examples/test_memory_system_design_demo.py`

**Interfaces:**
- Consumes: `MemoryEngine` public interfaces from Task 1 and concepts from Chapters 1-8.
- Produces: Chapter 9 anchor `#chapter-9`, V0-V4 evolution, runnable commands, and a symbol crosswalk from teaching code to Mem0.

- [ ] **Step 1: Add the V0-V4 implementation chapter**

Append:

```markdown
## 9. 从零实现一个最小记忆系统 {#chapter-9}
### 9.1 V0：保存全部消息
### 9.2 V1：抽取原子事实
### 9.3 V2：作用域、Embedding 与语义检索
### 9.4 V3：关键词、实体与融合评分
### 9.5 V4：历史、更新、过期与冲突
### 9.6 教学实现与 Mem0 的符号对照
### 9.7 运行确定性演示
### 9.8 可选实验：替换为 DeepSeek 与 Qdrant
### 9.9 本章练习与面试思考
```

Required content:

- For every version, show the data model delta, a compact `教学实现` snippet, the solved problem, the remaining failure mode, and the corresponding Mem0 symbol.
- Explain why `DeterministicEmbedder` is lexical and deterministic rather than semantically strong.
- Walk through `Scope.contains`, hash deduplication, semantic threshold, keyword overlap, entity boost, score normalization, expiration, history, update, and delete.
- Include this exact runnable command: `conda run -n mem0 python examples/memory_system_design_demo.py`.
- Include a crosswalk table mapping `Scope` to Mem0 filters, `MemoryRecord` to vector payload/`MemoryItem`, `MemoryEngine.events` to `SQLiteManager.history`, and teaching scoring to `score_and_rank()`.
- Include a clearly marked optional DeepSeek/Qdrant configuration block that reads `DEEPSEEK_API_KEY` from the environment and never contains a key literal.
- Explain at least five missing production features in the demo: LLM extraction quality controls, robust tokenizer/BM25, durable stores, transactions/compensation, concurrency/idempotency, provider failures, and evaluation.

- [ ] **Step 2: Validate code references and execute the companion**

Run:

```bash
conda run -n mem0 python -m pytest tests/examples/test_memory_system_design_demo.py -q
conda run -n mem0 python examples/memory_system_design_demo.py
rg -n '^class (Scope|MemoryInput|MemoryRecord|HistoryEvent|ScoreDetails|SearchHit|DeterministicEmbedder|MemoryEngine)|^def run_demo' examples/memory_system_design_demo.py
rg -n 'Scope|MemoryRecord|MemoryEngine|DeterministicEmbedder|DEEPSEEK_API_KEY' docs/learning/mem0-memory-system-design.zh-CN.md
```

Expected: all demo tests pass, the demo exits 0, and every teaching symbol referenced in Chapter 9 exists.

- [ ] **Step 3: Commit the implementation chapter**

```bash
git add docs/learning/mem0-memory-system-design.zh-CN.md
git commit -m "docs: teach memory design through a minimal engine"
```

---

### Task 5: Add production design, evaluation, review, and interview chapters

**Files:**
- Modify: `docs/learning/mem0-memory-system-design.zh-CN.md`
- Reference: `mem0/memory/main.py`
- Reference: `mem0/memory/storage.py`
- Reference: `tests/test_memory.py`
- Reference: `tests/memory/test_main.py`
- Reference: `tests/utils/test_scoring.py`
- Reference: `docs/open-source/overview.mdx`
- Reference: `docs/open-source/configuration.mdx`

**Interfaces:**
- Consumes: all terms, lifecycle flows, and teaching implementation from Chapters 1-9.
- Produces: Chapters 10-14, final design method, evaluation framework, interview question bank, glossary, and source-reading map.

- [ ] **Step 1: Add production engineering and evaluation chapters**

Append:

```markdown
## 10. 工程化与生产设计 {#chapter-10}
### 10.1 幂等、并发与重复写入
### 10.2 原子性、补偿与最终一致性
### 10.3 批处理、重试、降级和背压
### 10.4 成本、延迟与容量规划
### 10.5 多租户、分片与索引迁移
### 10.6 隐私、安全与可观测性
### 10.7 同步 SDK、异步 SDK 与服务化
### 10.8 本章练习与面试思考

## 11. 如何评估记忆系统 {#chapter-11}
### 11.1 写入质量：准确、遗漏、误记、归属与去重
### 11.2 检索质量：Recall、MRR 与 NDCG
### 11.3 时间一致性、冲突率与陈旧度
### 11.4 端到端任务收益
### 11.5 离线集、在线反馈与回归测试
### 11.6 成本和延迟护栏
### 11.7 本章练习与面试思考
```

Required production analysis:

- Give an explicit failure matrix for LLM, batch Embedding, main vector insert, history insert, entity insert, and reranker.
- For each failure, state current behavior, user-visible effect, consistency risk, retry safety, and a stronger production alternative.
- Show an idempotency-key design based on tenant/scope/source-event/extractor-version rather than only content hash.
- Compare local SDK, shared memory service, and event-driven pipeline deployments.
- Provide back-of-the-envelope formulas for storage, embedding calls, extraction calls, candidate retrieval, and p95 latency budget.
- Explain secret handling without printing environment values.
- Provide formulas and one numerical example for precision/recall, MRR, and NDCG.
- Separate component metrics from end-to-end task success and personalization lift.

- [ ] **Step 2: Add design review, interview framework, and appendices**

Append:

```markdown
## 12. 设计复盘与适用边界 {#chapter-12}
### 12.1 Mem0 当前设计的主要优点
### 12.2 ADD-only 的收益与代价
### 12.3 混合评分与实体增强的边界
### 12.4 什么时候不该使用长期记忆系统
### 12.5 可演进方向

## 13. 系统设计面试题与参考分析 {#chapter-13}
### 13.1 概念题
### 13.2 源码阅读题
### 13.3 故障分析题
### 13.4 百万用户扩展题
### 13.5 完整系统设计题
### 13.6 回答框架与自检清单

## 14. 附录 {#chapter-14}
### 14.1 核心源码地图
### 14.2 术语表
### 14.3 推荐阅读顺序
### 14.4 进一步实验
```

Required interview content:

- At least 30 total questions: 6 concept, 6 source, 6 failure, 6 scaling, and 6 complete-design prompts.
- Provide reference analysis for every question. Use the sequence: clarify requirements, define invariants, data model, write path, retrieval, consistency, scale, security, evaluation.
- Include the highlighted questions: vector DB versus memory system; preventing one anomalous conversation from overwriting preferences; temporal past/present/future; write and retrieval evaluation; million-user isolation/sharding; LLM extraction failure policy; right-to-forget versus audit.
- Include a source map for all files listed in the File Map and state what question the reader should answer when opening each file.
- Include a glossary covering at least memory type, scope, actor, atomic fact, ADD-only, semantic search, BM25, entity boost, reranker, TTL, decay, idempotency, compensation, MRR, and NDCG.

- [ ] **Step 3: Verify final chapter structure, question count, and target length**

Run:

```bash
rg -n '^## ([1-9]|1[0-4])\.' docs/learning/mem0-memory-system-design.zh-CN.md
rg -c '^#### (问题|Q)[0-9]+' docs/learning/mem0-memory-system-design.zh-CN.md
wc -m docs/learning/mem0-memory-system-design.zh-CN.md
```

Expected: exactly 14 numbered top-level chapters; at least 30 explicitly numbered interview questions; total character count is between 30,000 and 50,000.

- [ ] **Step 4: Commit final content chapters**

```bash
git add docs/learning/mem0-memory-system-design.zh-CN.md
git commit -m "docs: add production and interview memory design guide"
```

---

### Task 6: Perform source, code, diagram, and security verification

**Files:**
- Modify if verification finds issues: `docs/learning/mem0-memory-system-design.zh-CN.md`
- Modify if verification finds issues: `examples/memory_system_design_demo.py`
- Modify if verification finds issues: `tests/examples/test_memory_system_design_demo.py`
- Reference: `docs/superpowers/specs/2026-07-20-mem0-memory-system-tutorial-design.md`

**Interfaces:**
- Consumes: all completed artifacts and the approved spec.
- Produces: verified final tutorial and demo with no unresolved placeholders or unsupported claims.

- [ ] **Step 1: Run the complete focused test and lint suite**

Run:

```bash
conda run -n mem0 python -m pytest tests/examples/test_memory_system_design_demo.py tests/utils/test_scoring.py tests/llms/test_deepseek.py -q
conda run -n mem0 ruff format --check examples/memory_system_design_demo.py tests/examples/test_memory_system_design_demo.py
conda run -n mem0 ruff check examples/memory_system_design_demo.py tests/examples/test_memory_system_design_demo.py
conda run -n mem0 python -m pip check
```

Expected: all focused tests pass; format/lint exit 0; pip reports `No broken requirements found`.

- [ ] **Step 2: Run document completeness and secret scans**

Run:

```bash
test "$(rg -c '^## ([1-9]|1[0-4])\.' docs/learning/mem0-memory-system-design.zh-CN.md)" -eq 14
test "$(rg -c '^#### (问题|Q)[0-9]+' docs/learning/mem0-memory-system-design.zh-CN.md)" -ge 30
test "$(wc -m < docs/learning/mem0-memory-system-design.zh-CN.md)" -ge 30000
test "$(wc -m < docs/learning/mem0-memory-system-design.zh-CN.md)" -le 50000
! rg -n 'T[B]D|T[O]DO|待[补]|稍后[补]充|实现细节待[定]' docs/learning/mem0-memory-system-design.zh-CN.md examples/memory_system_design_demo.py
! rg -n 'sk-[A-Za-z0-9]{16,}|deepseek-[A-Za-z0-9]{16,}' docs/learning/mem0-memory-system-design.zh-CN.md examples/memory_system_design_demo.py
git diff --check
```

Expected: every command exits 0 and the secret scan returns no matches.

- [ ] **Step 3: Audit all required diagrams and code labels**

Run:

```bash
rg -c '^```mermaid$' docs/learning/mem0-memory-system-design.zh-CN.md
rg -n '概念伪代码|教学实现|Mem0 源码' docs/learning/mem0-memory-system-design.zh-CN.md
```

Expected: at least 10 Mermaid blocks and all three code labels are used. Inspect every Mermaid block for balanced fences, unique node IDs, and text consistent with surrounding prose.

- [ ] **Step 4: Audit source claims symbol by symbol**

Use these commands as the source index:

```bash
rg -n '^class Memory|^class AsyncMemory|def (add|_add_to_vector_store|search|_search_vector_store|update|delete|delete_all|history|reset)' mem0/memory/main.py
rg -n '^class SQLiteManager|def (save_messages|get_last_messages|add_history|batch_add_history|get_history)' mem0/memory/storage.py
rg -n 'ADDITIVE_EXTRACTION_PROMPT|generate_additive_extraction_prompt|PROCEDURAL_MEMORY_SYSTEM_PROMPT' mem0/configs/prompts.py
rg -n 'def (get_bm25_params|normalize_bm25|score_and_rank)|ENTITY_BOOST_WEIGHT' mem0/utils/scoring.py
rg -n '^class (LlmFactory|EmbedderFactory|VectorStoreFactory|RerankerFactory)' mem0/utils/factory.py
```

For every tutorial paragraph that names a concrete default, threshold, weight, limit, fallback, or unsupported parameter, compare it with the indexed source and correct any mismatch before continuing.

- [ ] **Step 5: Run the demo one final time and inspect output**

Run:

```bash
conda run -n mem0 python examples/memory_system_design_demo.py
```

Expected: deterministic ranked output with `Mem0 project uses Qdrant vector database` first for the Qdrant query and visible semantic, keyword, and entity values.

- [ ] **Step 6: Review the final diff against the approved spec**

Run:

```bash
git diff --stat 7aa461d4..HEAD
git status --short
```

Review the approved spec sections 1-12 and map every learning outcome and acceptance criterion to a tutorial chapter, demo test, or verification command. If any requirement is missing, add it to the correct chapter and repeat Steps 1-5.

- [ ] **Step 7: Commit verification corrections if any exist**

If verification changed files:

```bash
git add docs/learning/mem0-memory-system-design.zh-CN.md examples/memory_system_design_demo.py tests/examples/test_memory_system_design_demo.py
git commit -m "docs: verify memory system tutorial"
```

If verification made no changes, do not create an empty commit.
