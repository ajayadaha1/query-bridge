"""AgentLoop — The core agentic NL2SQL loop.

Orchestrates: LLM ↔ tool calls ↔ validation ↔ strategy tracking.
Database-agnostic. Plugin-extensible.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from querybridge.agent.builtin_tools import (
    handle_column_profile,
    handle_count_estimate,
    handle_cross_validate,
    handle_execute_sql,
    handle_explore_table,
    handle_get_distinct_values,
    handle_note_exploration,
    handle_note_query_path,
    handle_note_relationship,
    handle_recall_explorations,
    handle_search_schema,
    handle_validate_filter_values,
)
from querybridge.agent.context import ContextWindowManager
from querybridge.agent.tools import (
    BUILTIN_TOOLS,
    EXPLORATION_TOOLS,
    SEARCH_SCHEMA,
    ToolRegistry,
)
from querybridge.classifier.question_classifier import QuestionClassifier
from querybridge.core.models import QueryLogEntry, QueryRequest, QueryResponse
from querybridge.discovery.engine import DiscoveryEngine
from querybridge.memory.persistent import PersistentQueryMemory
from querybridge.memory.store import MemoryStore
from querybridge.plugins.builtin.generic import GenericPlugin
from querybridge.prompts.few_shot import FewShotRegistry
from querybridge.prompts.system import build_system_prompt
from querybridge.safety.guard import SQLGuard
from querybridge.safety.validator import ResultValidator
from querybridge.schema.cache import SchemaCache
from querybridge.strategy.column_hierarchy import ColumnHierarchy
from querybridge.strategy.tracker import StrategyTracker

if TYPE_CHECKING:
    from querybridge.connectors.base import DatabaseConnector
    from querybridge.core.config import EngineConfig
    from querybridge.llm.base import LLMProvider
    from querybridge.plugins.base import DomainPlugin

logger = logging.getLogger("querybridge.agent.loop")

MONOLOGUE_MAX_LEN = 4000


class _ToolCall:
    """Lightweight wrapper for tool call dicts from LLM responses."""
    __slots__ = ("id", "name", "arguments")

    def __init__(self, d: dict[str, Any]):
        self.id = d.get("id", "")
        func = d.get("function", {})
        self.name = func.get("name", "")
        self.arguments = func.get("arguments", "{}")


def _get_phase(iteration: int, phase_budgets: dict[str, int]) -> str:
    """Determine current investigation phase from iteration count."""
    explore_end = phase_budgets.get("explore", 2)
    execute_end = explore_end + phase_budgets.get("execute", 5)
    validate_end = execute_end + phase_budgets.get("validate", 2)
    if iteration < explore_end:
        return "explore"
    elif iteration < execute_end:
        return "execute"
    elif iteration < validate_end:
        return "validate"
    return "refine"


def _build_phase_guidance(phase: str, iteration: int, phase_budgets: dict[str, int]) -> str:
    """Build phase-specific guidance for injection into messages."""
    budget = phase_budgets.get(phase, 3)

    if phase == "explore":
        return (
            f"[Phase: EXPLORE — iteration {iteration + 1}, budget {budget}]\n"
            "Goal: Verify your understanding of the data before writing the main query.\n"
            "- Use get_distinct_values and validate_filter_values to check filter values\n"
            "- Use column_profile to check NULL rates and data quality\n"
            "- Do NOT write the main query yet"
        )
    elif phase == "execute":
        return (
            f"[Phase: EXECUTE — iteration {iteration + 1}, budget {budget}]\n"
            "Goal: Write and run the SQL query to answer the user's question.\n"
            "- Use the verified filter values from discovery\n"
            "- If a query returns 0 rows, check the strategy tracker"
        )
    elif phase == "validate":
        return (
            f"[Phase: VALIDATE — iteration {iteration + 1}, budget {budget}]\n"
            "Goal: Verify the results make sense.\n"
            "- Use cross_validate to check from a different angle\n"
            "- Use count_estimate to verify row counts"
        )
    else:
        return (
            f"[Phase: REFINE — iteration {iteration + 1}, budget {budget}]\n"
            "Goal: Address anomalies and prepare your answer.\n"
            "- Follow up on validation discrepancies\n"
            "- Present tabular results as markdown tables"
        )


def _compute_confidence(
    strategy_tracker: StrategyTracker,
    result_validator: ResultValidator,
    total_iterations: int,
    max_iterations: int,
) -> float:
    """Compute 0.0-1.0 confidence score."""
    score = 1.0
    if strategy_tracker.error_count > 0:
        score -= 0.15 * min(strategy_tracker.error_count, 3)
    if result_validator.zero_row_events > 0:
        score -= 0.2
    if total_iterations > max_iterations * 0.8:
        score -= 0.1
    if getattr(result_validator, 'high_null_warnings', 0) > 0:
        score -= 0.1
    return max(0.1, min(1.0, round(score, 2)))


def _extract_last_sql(query_log: list[dict[str, Any]]) -> str | None:
    """Extract the last successful execute_sql query from the log."""
    for entry in reversed(query_log):
        if (
            entry.get("sql")
            and not entry.get("blocked")
            and not entry.get("error")
            and entry.get("row_count", 0) > 0
        ):
            return entry["sql"]
    return None


class AgentLoop:
    """The core agentic NL2SQL loop.

    Accepts a user question, runs classification → discovery → LLM agentic loop
    with tool calls, and returns a structured response.
    """

    def __init__(
        self,
        connector: DatabaseConnector,
        llm: LLMProvider,
        config: EngineConfig,
        plugin: DomainPlugin | None = None,
        schema_cache: SchemaCache | None = None,
        memory_store: MemoryStore | None = None,
        few_shot: FewShotRegistry | None = None,
        persistent_memory: PersistentQueryMemory | None = None,
        rag_sync: Any = None,
        exploration_memory: Any = None,
    ):
        self.connector = connector
        self.llm = llm
        self.config = config
        self.plugin = plugin or GenericPlugin()
        self.schema_cache = schema_cache or SchemaCache(
            connector, self.plugin, cache_dir="/tmp/querybridge_cache"
        )
        self.memory_store = memory_store or MemoryStore(
            max_sessions=100, ttl_seconds=config.session_ttl_seconds
        )
        self.few_shot = few_shot or FewShotRegistry()
        self.persistent_memory = persistent_memory
        self.rag_sync = rag_sync
        self.exploration_memory = exploration_memory
        self.classifier = QuestionClassifier(
            entity_patterns=self.plugin.get_entity_patterns(),
            entity_column_map=self.plugin.get_entity_column_map(),
            extra_question_patterns=self.plugin.get_question_type_patterns(),
        )
        self.guard = SQLGuard(dialect=connector.get_dialect_name())

        # Register plugin few-shot examples
        for ex in self.plugin.get_few_shot_examples():
            self.few_shot.add_example(
                question=ex["question"],
                sql=ex["sql"],
                explanation=ex.get("explanation", ""),
            )

        # Build tool registry (dispatch happens via _dispatch_tool_by_name)
        self.tool_registry = ToolRegistry()
        for tool_def in BUILTIN_TOOLS:
            self.tool_registry.register(tool_def, self._dispatch_tool_by_name)

        # Register plugin custom tools
        for tool_def in self.plugin.get_custom_tools():
            self.tool_registry.register(tool_def, self._dispatch_tool_by_name)

        # Register exploration memory tools if available
        if self.exploration_memory:
            for tool_def in EXPLORATION_TOOLS:
                self.tool_registry.register(tool_def, self._dispatch_tool_by_name)

        # Lazy schema mode: register search_schema tool if cache is in lazy mode
        self._lazy_schema = False

    async def run(self, request: QueryRequest) -> QueryResponse:
        """Execute the full agentic loop for a query."""
        response: QueryResponse | None = None
        async for event in self.run_streaming(request):
            if event.get("type") == "complete":
                response = event["response"]
        return response or QueryResponse(
            answer="No response generated.", chat_id=request.chat_id or "",
        )

    async def run_streaming(self, request: QueryRequest):
        """Execute the agentic loop, yielding progress events as an async generator.

        Event types:
          - {"type": "status", "step": str, "detail": str}
          - {"type": "thinking", "iteration": int, "phase": str, "reasoning": str}
          - {"type": "tool_call", "iteration": int, "tool": str, "args": dict}
          - {"type": "tool_result", "iteration": int, "tool": str, "summary": str}
          - {"type": "complete", "response": QueryResponse}
        """
        start_time = time.monotonic()
        self._current_question = request.question
        chat_id = request.chat_id or str(uuid.uuid4())
        query_log: list[dict[str, Any]] = []
        thinking_steps: list[dict[str, Any]] = []
        all_validation_notes: list[str] = []

        strategy_tracker = StrategyTracker(
            column_hierarchy=ColumnHierarchy(self.plugin.get_column_hierarchy())
        )
        result_validator = ResultValidator()
        context_manager = ContextWindowManager()
        memory = self.memory_store.get(chat_id)

        try:
            # Phase 0: Classification
            yield {"type": "status", "step": "classification", "detail": "Analyzing question type..."}
            profile = self.classifier.classify(request.question)

            # LLM-enhanced classification for low-confidence results
            if profile.confidence < 0.5:
                try:
                    llm_profile = await self._llm_classify(request.question, profile)
                    if llm_profile:
                        profile = llm_profile
                except Exception as e:
                    logger.debug(f"LLM classification failed (using regex): {e}")

            phase_budgets = profile.phase_budgets

            thinking_steps.append({
                "iteration": 0,
                "phase": "classification",
                "reasoning": (
                    f"type='{profile.question_type}', "
                    f"shape='{profile.expected_shape}', "
                    f"complexity='{profile.complexity}', "
                    f"entities={profile.implied_entities}"
                ),
            })

            # Phase 0b: Pre-flight discovery
            discovery_text = ""
            if profile.needs_discovery and profile.implied_entities:
                yield {"type": "status", "step": "discovery", "detail": f"Verifying entities: {', '.join(profile.implied_entities[:3])}..."}
                try:
                    discovery_engine = DiscoveryEngine(
                        self.connector,
                        entity_column_map=self.plugin.get_entity_column_map(),
                        primary_table=self.plugin.get_primary_table(),
                    )
                    discovery_brief = await discovery_engine.run_discovery(
                        profile.implied_entities
                    )
                    discovery_text = discovery_engine.format_brief_for_prompt(
                        discovery_brief
                    )
                    if discovery_brief.total_row_estimate > 0:
                        result_validator.set_expectations(
                            expected=discovery_brief.total_row_estimate,
                        )
                    for vf in discovery_brief.verified_filters:
                        if vf.status == "exact_match":
                            memory.add_verified_filter(
                                f"{vf.column}={vf.value}", vf.row_count
                            )
                except Exception as e:
                    logger.warning(f"Pre-flight discovery failed: {e}")

            # Initialize schema cache (auto-selects full vs lazy mode)
            if not self.schema_cache._mode:
                yield {"type": "status", "step": "schema", "detail": "Discovering database schema..."}
                mode = await self.schema_cache.initialize()
                if mode == "lazy":
                    self._lazy_schema = True
                    if "search_schema" not in self.tool_registry.names:
                        self.tool_registry.register(
                            SEARCH_SCHEMA, self._dispatch_tool_by_name
                        )

            # Build system prompt
            schema_text = await self.schema_cache.get_schema_context()

            # Recall exploration notes (persistent knowledge from past sessions)
            exploration_context = ""
            _recalled_note_ids: list[str] = []
            if self.exploration_memory:
                try:
                    exploration_notes = self.exploration_memory.recall(
                        topic=request.question,
                        limit=10,
                    )
                    if exploration_notes:
                        exploration_context = self.exploration_memory.format_for_prompt(
                            exploration_notes
                        )
                        _recalled_note_ids = [n.id for n in exploration_notes]
                        logger.debug(
                            "Recalled %d exploration notes for: %s",
                            len(exploration_notes), request.question[:60],
                        )
                except Exception as e:
                    logger.debug("Exploration recall failed: %s", e)

            # Recall similar past queries from persistent memory
            all_few_shot = list(self.few_shot.get_examples())
            if self.persistent_memory:
                recalled = self.persistent_memory.recall(request.question, limit=3)
                if recalled:
                    all_few_shot.extend(self.persistent_memory.format_as_few_shot(recalled))

            # Also recall from shared RAG memory (Silicon Trace pgvector)
            if self.rag_sync:
                try:
                    rag_matches = await self.rag_sync.recall(request.question, limit=2)
                    for m in rag_matches:
                        for sq in m.sql_queries:
                            if sq.get("sql"):
                                all_few_shot.append({
                                    "question": m.question,
                                    "sql": sq["sql"],
                                    "explanation": f"RAG memory (quality: {m.quality_score:.0%})",
                                })
                except Exception as e:
                    logger.debug("RAG sync recall failed: %s", e)

            system_prompt = build_system_prompt(
                schema_context=schema_text,
                dialect=self.connector.get_dialect_name(),
                plugin_context=self.plugin.get_system_prompt_context(),
                few_shot_examples=all_few_shot,
                discovery_context=discovery_text,
                memory_context=memory.format_for_prompt(),
                strategy_context=strategy_tracker.get_status_summary(),
                response_formatting=self.plugin.get_response_formatting_rules(),
                lazy_schema=self._lazy_schema,
                exploration_context=exploration_context,
            )

            # Build messages
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt}
            ]
            context_manager.track_message(messages[0])

            if request.history:
                for msg in request.history:
                    if msg.get("role") in ("user", "assistant"):
                        m = {"role": msg["role"], "content": msg.get("content", "")}
                        messages.append(m)
                        context_manager.track_message(m)

            user_msg = {"role": "user", "content": request.question}
            messages.append(user_msg)
            context_manager.track_message(user_msg)

            # Pre-loop compression
            if context_manager.should_compress():
                messages = context_manager.compress_history(messages)
            messages = context_manager.truncate_to_budget(messages)

            # Agentic loop
            tools_openai = self.tool_registry.get_openai_tools()

            for iteration in range(self.config.max_iterations):
                # Phase guidance
                current_phase = _get_phase(iteration, phase_budgets)
                phase_guidance = _build_phase_guidance(
                    current_phase, iteration, phase_budgets
                )
                # Remove stale phase guidance
                messages = [
                    m for m in messages
                    if not (
                        m.get("role") == "system"
                        and isinstance(m.get("content", ""), str)
                        and m["content"].startswith("[Phase:")
                    )
                ]
                messages.append({"role": "system", "content": phase_guidance})

                # Inject strategy tracker state
                if strategy_tracker.entries:
                    tracker_summary = strategy_tracker.get_status_summary()
                    if strategy_tracker.should_escalate():
                        tracker_summary += f"\n\nSuggestion: {strategy_tracker.suggest_next()}"
                    messages = [
                        m for m in messages
                        if not (
                            m.get("role") == "system"
                            and isinstance(m.get("content", ""), str)
                            and m["content"].startswith("[Strategy Tracker]")
                        )
                    ]
                    messages.append({
                        "role": "system",
                        "content": f"[Strategy Tracker]\n{tracker_summary}",
                    })

                # Context window management
                if context_manager.should_compress():
                    messages = context_manager.compress_history(messages)
                    messages = context_manager.truncate_to_budget(messages)

                # LLM call
                llm_response = await self.llm.chat(
                    messages=messages,
                    tools=tools_openai,
                    temperature=self.config.temperature,
                    max_tokens=16384,
                )

                content = llm_response.content
                tool_calls = [_ToolCall(tc) for tc in llm_response.tool_calls]

                # Capture thinking
                if content:
                    step = {
                        "iteration": iteration + 1,
                        "phase": current_phase if tool_calls else "final_answer",
                        "reasoning": content[:200],
                        "monologue": content[:MONOLOGUE_MAX_LEN],
                        "tools_called": [tc.name for tc in tool_calls] if tool_calls else [],
                    }
                    thinking_steps.append(step)
                    yield {
                        "type": "thinking",
                        "iteration": step["iteration"],
                        "phase": step["phase"],
                        "reasoning": step["reasoning"],
                    }

                # Final answer — no tool calls
                if not tool_calls:
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    final_answer = content or "No answer generated."
                    confidence = _compute_confidence(
                        strategy_tracker, result_validator,
                        iteration + 1, self.config.max_iterations,
                    )
                    memory.add_successful_pattern(
                        profile.question_type,
                        f"Answered in {iteration + 1} iterations",
                    )
                    last_sql = _extract_last_sql(query_log)
                    resp = QueryResponse(
                        answer=final_answer,
                        chat_id=chat_id,
                        query_log=query_log,
                        total_time_ms=elapsed_ms,
                        last_sql=last_sql,
                        thinking_steps=thinking_steps,
                        confidence=confidence,
                        iterations_used=iteration + 1,
                    )

                    # Store in persistent memory if quality is sufficient
                    if self.persistent_memory and last_sql and confidence >= 0.5:
                        self.persistent_memory.store(
                            question=request.question,
                            sql=last_sql,
                            question_type=profile.question_type,
                            confidence=confidence,
                            row_count=query_log[-1].get("row_count", 0) if query_log else 0,
                        )

                    # Sync to Silicon Trace rag_query_memory if available
                    if self.rag_sync and last_sql and confidence >= 0.5:
                        try:
                            await self.rag_sync.push(
                                question=request.question,
                                sql=last_sql,
                                answer_summary=final_answer[:500] if final_answer else "",
                                quality_score=confidence,
                                iterations_used=iteration + 1,
                                row_count=query_log[-1].get("row_count", 0) if query_log else 0,
                                had_errors=any(q.get("error") for q in query_log),
                            )
                        except Exception as e:
                            logger.debug("RAG sync push failed: %s", e)

                    # Auto-extract exploration notes from this session
                    if self.exploration_memory and confidence >= 0.5:
                        try:
                            self._auto_extract_exploration(
                                request.question, query_log, last_sql,
                                iteration + 1, _recalled_note_ids, confidence,
                            )
                        except Exception as e:
                            logger.debug("Exploration auto-extract failed: %s", e)

                    yield {"type": "complete", "response": resp}
                    return

                # Process tool calls
                assistant_msg = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(assistant_msg)

                for tc in tool_calls:
                    try:
                        args = json.loads(tc.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    yield {
                        "type": "tool_call",
                        "iteration": iteration + 1,
                        "tool": tc.name,
                        "args": {k: str(v)[:100] for k, v in args.items()},
                    }

                    tool_result = await self._dispatch_tool_by_name(
                        tc.name, args, query_log, iteration + 1
                    )

                    # Summarize result for streaming
                    _summary = ""
                    if "error" in tool_result:
                        _summary = f"Error: {tool_result['error'][:100]}"
                    elif tc.name == "execute_sql":
                        _summary = f"{tool_result.get('row_count', 0)} rows"
                    elif tc.name == "search_schema":
                        _summary = f"{tool_result.get('match_count', 0)} tables matched"
                    elif tc.name == "explore_table":
                        _summary = f"{tool_result.get('row_count', '?')} rows, {len(tool_result.get('columns', []))} columns"
                    yield {
                        "type": "tool_result",
                        "iteration": iteration + 1,
                        "tool": tc.name,
                        "summary": _summary,
                    }

                    # Result validation for execute_sql
                    if tc.name == "execute_sql" and "error" not in tool_result:
                        sql = args.get("sql", "")
                        validation = result_validator.validate(tool_result, sql)
                        if validation.has_issues():
                            summary = validation.get_summary()
                            all_validation_notes.append(summary)
                            tool_result["_validation_notes"] = summary

                        strategy_tracker.record_attempt(
                            iteration=iteration + 1,
                            approach=args.get("reason", f"Query at iteration {iteration + 1}"),
                            sql=sql,
                            result_count=tool_result.get("row_count", 0),
                            success=tool_result.get("row_count", 0) > 0,
                        )

                    # Auto-note on execute_sql timeout/error (passive safety learning)
                    if (
                        tc.name == "execute_sql"
                        and "error" in tool_result
                        and self.exploration_memory
                    ):
                        err = str(tool_result["error"]).lower()
                        if "timeout" in err or "cancel" in err or "timed out" in err:
                            sql = args.get("sql", "")
                            table = _extract_table_from_sql(sql)
                            if table:
                                self.exploration_memory.auto_note_safety_warning(
                                    table, tool_result["error"], sql
                                )

                    # Auto-note table profiles from explore_table (passive learning)
                    if (
                        tc.name == "explore_table"
                        and "error" not in tool_result
                        and self.exploration_memory
                    ):
                        self.exploration_memory.auto_note_table_profile(
                            tool_result, args.get("table_name", "")
                        )

                    # Auto-note large tables from count_estimate (passive learning)
                    if (
                        tc.name == "count_estimate"
                        and "error" not in tool_result
                        and self.exploration_memory
                    ):
                        self.exploration_memory.auto_note_row_count(tool_result)

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result, default=str),
                    }
                    messages.append(tool_msg)
                    context_manager.track_message(tool_msg)

            # Exhausted iterations
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            confidence = _compute_confidence(
                strategy_tracker, result_validator,
                self.config.max_iterations, self.config.max_iterations,
            )
            resp = QueryResponse(
                answer="I ran out of query iterations. Here's what I found so far.",
                chat_id=chat_id,
                query_log=query_log,
                total_time_ms=elapsed_ms,
                last_sql=_extract_last_sql(query_log),
                thinking_steps=thinking_steps,
                confidence=confidence,
                iterations_used=self.config.max_iterations,
            )
            yield {"type": "complete", "response": resp}
            return

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(f"AgentLoop error: {e}", exc_info=True)
            resp = QueryResponse(
                answer=f"Error: {str(e)}",
                chat_id=chat_id,
                query_log=query_log,
                total_time_ms=elapsed_ms,
                thinking_steps=thinking_steps,
                confidence=0.1,
            )
            yield {"type": "complete", "response": resp}

    async def _dispatch_tool_by_name(
        self,
        tool_name: str,
        args: dict[str, Any],
        query_log: list[dict[str, Any]],
        iteration: int,
    ) -> dict[str, Any]:
        """Route a tool call to the appropriate handler."""
        if tool_name == "execute_sql":
            return await handle_execute_sql(
                self.connector, self.guard, args, query_log, iteration
            )
        elif tool_name == "explore_table":
            return await handle_explore_table(
                self.connector, args, query_log, iteration
            )
        elif tool_name == "get_distinct_values":
            return await handle_get_distinct_values(
                self.connector, args, query_log, iteration
            )
        elif tool_name == "validate_filter_values":
            return await handle_validate_filter_values(
                self.connector, args, query_log, iteration
            )
        elif tool_name == "column_profile":
            return await handle_column_profile(
                self.connector, args, query_log, iteration
            )
        elif tool_name == "count_estimate":
            return await handle_count_estimate(
                self.connector, args, query_log, iteration
            )
        elif tool_name == "cross_validate":
            return await handle_cross_validate(
                self.connector, self.guard, args, query_log, iteration
            )
        elif tool_name == "search_schema":
            index = self.schema_cache.schema_index
            if not index:
                return {"error": "Schema index not available"}
            return await handle_search_schema(
                index.tables, index.column_types, args, query_log, iteration
            )
        # Exploration memory tools
        elif tool_name == "recall_explorations":
            if not self.exploration_memory:
                return {"error": "Exploration memory not available", "notes": []}
            return await handle_recall_explorations(
                self.exploration_memory, args, query_log, iteration
            )
        elif tool_name == "note_exploration":
            if not self.exploration_memory:
                return {"error": "Exploration memory not available"}
            return await handle_note_exploration(
                self.exploration_memory, args, query_log, iteration,
                source_question=self._current_question,
            )
        elif tool_name == "note_relationship":
            if not self.exploration_memory:
                return {"error": "Exploration memory not available"}
            return await handle_note_relationship(
                self.exploration_memory, args, query_log, iteration
            )
        elif tool_name == "note_query_path":
            if not self.exploration_memory:
                return {"error": "Exploration memory not available"}
            return await handle_note_query_path(
                self.exploration_memory, args, query_log, iteration
            )
        else:
            # Try plugin-registered tools via the registry
            handler = self.tool_registry.get_handler(tool_name)
            if handler and handler is not self._dispatch_tool_by_name:
                return await handler(args)
            query_log.append({
                "iteration": iteration,
                "error": f"Unknown tool: {tool_name}",
            })
            return {"error": f"Unknown tool: {tool_name}"}

    async def _llm_classify(
        self,
        question: str,
        regex_profile: Any,
    ) -> Any:
        """Use LLM to re-classify a question when regex confidence is low.

        Returns an updated QuestionProfile or None if classification fails.
        """
        from querybridge.classifier.question_classifier import QuestionProfile

        prompt = (
            "Classify this database question. Return a JSON object with:\n"
            '- "question_type": one of count, comparison, trend, drill_down, audit, search, failure_analysis, tier_progression, customer_analysis, serial_lookup\n'
            '- "expected_shape": one of scalar, grouped, time_series, table\n'
            '- "complexity": one of simple, moderate, complex\n\n'
            f"Question: {question}\n\n"
            "Return ONLY the JSON object, no explanation."
        )

        resp = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        data = json.loads(text)
        valid_types = {
            "count", "comparison", "trend", "drill_down", "audit", "search",
            "failure_analysis", "tier_progression", "customer_analysis", "serial_lookup",
        }
        qtype = data.get("question_type", "drill_down")
        if qtype not in valid_types:
            qtype = "drill_down"

        return QuestionProfile(
            question_type=qtype,
            expected_shape=data.get("expected_shape", regex_profile.expected_shape),
            implied_entities=regex_profile.implied_entities,
            implied_columns=regex_profile.implied_columns,
            complexity=data.get("complexity", regex_profile.complexity),
            needs_discovery=regex_profile.needs_discovery,
            confidence=0.8,  # LLM classification is high confidence
        )

    def _auto_extract_exploration(
        self,
        question: str,
        query_log: list[dict[str, Any]],
        last_sql: str | None,
        iterations_used: int,
        recalled_note_ids: list[str],
        confidence: float,
    ) -> None:
        """Auto-extract exploration insights after a successful query.

        Passive learning: captures table profiles, large-table warnings,
        multi-step query paths, and boosts recalled notes that led to success.
        """
        if not self.exploration_memory:
            return

        # 1. Auto-note query path if it took many iterations (complex multi-step)
        if iterations_used > 3 and last_sql:
            self.exploration_memory.auto_note_query_path(
                question=question,
                query_log=query_log,
                final_sql=last_sql,
            )

        # 2. Boost recalled notes that contributed to a successful answer
        if confidence >= 0.6:
            for note_id in recalled_note_ids:
                self.exploration_memory.boost(note_id)

        # 3. Prune stale notes occasionally (every ~50 queries, probabilistic)
        import random
        if random.random() < 0.02:
            self.exploration_memory.prune_stale()


def _extract_table_from_sql(sql: str) -> str:
    """Best-effort extraction of the main table name from a SQL statement."""
    import re
    # Match FROM <table> or JOIN <table>
    m = re.search(r'\bFROM\s+([^\s,()+]+)', sql, re.IGNORECASE)
    if m:
        return m.group(1).strip('"\'`')
    return ""
