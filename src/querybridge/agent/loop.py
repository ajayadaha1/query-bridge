"""AgentLoop — The core agentic NL2SQL loop.

Orchestrates: LLM ↔ tool calls ↔ validation ↔ strategy tracking.
Database-agnostic. Plugin-extensible.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from querybridge.agent.builtin_tools import (
    handle_column_profile,
    handle_count_estimate,
    handle_cross_validate,
    handle_execute_sql,
    handle_explore_table,
    handle_get_distinct_values,
    handle_validate_filter_values,
)
from querybridge.agent.context import ContextWindowManager
from querybridge.agent.tools import BUILTIN_TOOLS, ToolRegistry
from querybridge.classifier.question_classifier import QuestionClassifier
from querybridge.connectors.base import DatabaseConnector
from querybridge.core.config import EngineConfig
from querybridge.core.models import QueryLogEntry, QueryRequest, QueryResponse
from querybridge.discovery.engine import DiscoveryEngine
from querybridge.llm.base import LLMProvider
from querybridge.memory.conversation import ConversationMemory
from querybridge.memory.store import MemoryStore
from querybridge.plugins.base import DomainPlugin
from querybridge.plugins.builtin.generic import GenericPlugin
from querybridge.prompts.few_shot import FewShotRegistry
from querybridge.prompts.system import build_system_prompt
from querybridge.safety.guard import SQLGuard
from querybridge.safety.validator import ResultValidator
from querybridge.schema.cache import SchemaCache
from querybridge.strategy.tracker import StrategyTracker

logger = logging.getLogger("querybridge.agent.loop")

MONOLOGUE_MAX_LEN = 4000


def _get_phase(iteration: int, phase_budgets: Dict[str, int]) -> str:
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


def _build_phase_guidance(phase: str, iteration: int, phase_budgets: Dict[str, int]) -> str:
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
    if result_validator.high_null_warnings > 0:
        score -= 0.1
    return max(0.1, min(1.0, round(score, 2)))


def _extract_last_sql(query_log: List[Dict[str, Any]]) -> Optional[str]:
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
        plugin: Optional[DomainPlugin] = None,
        schema_cache: Optional[SchemaCache] = None,
        memory_store: Optional[MemoryStore] = None,
        few_shot: Optional[FewShotRegistry] = None,
    ):
        self.connector = connector
        self.llm = llm
        self.config = config
        self.plugin = plugin or GenericPlugin()
        self.schema_cache = schema_cache or SchemaCache(connector, self.plugin)
        self.memory_store = memory_store or MemoryStore(
            max_sessions=100, session_ttl=config.session_ttl
        )
        self.few_shot = few_shot or FewShotRegistry()
        self.classifier = QuestionClassifier(plugin=self.plugin)
        self.guard = SQLGuard(dialect=connector.get_dialect_name())

        # Register plugin few-shot examples
        for ex in self.plugin.get_few_shot_examples():
            self.few_shot.add(
                question=ex["question"],
                sql=ex["sql"],
                explanation=ex.get("explanation", ""),
            )

        # Build tool registry
        self.tool_registry = ToolRegistry()
        for tool_def in BUILTIN_TOOLS:
            self.tool_registry.register(tool_def, self._dispatch_tool)

        # Register plugin custom tools
        for tool_def in self.plugin.get_custom_tools():
            self.tool_registry.register(tool_def, self._dispatch_tool)

    async def run(self, request: QueryRequest) -> QueryResponse:
        """Execute the full agentic loop for a query."""
        start_time = time.monotonic()
        chat_id = request.chat_id or str(uuid.uuid4())
        query_log: List[Dict[str, Any]] = []
        thinking_steps: List[Dict[str, Any]] = []
        all_validation_notes: List[str] = []

        strategy_tracker = StrategyTracker()
        result_validator = ResultValidator()
        context_manager = ContextWindowManager()
        memory = self.memory_store.get(chat_id)

        try:
            # Phase 0: Classification
            profile = self.classifier.classify(request.question)
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
                try:
                    discovery_engine = DiscoveryEngine(
                        self.connector, self.plugin
                    )
                    discovery_brief = await discovery_engine.run_discovery(
                        profile.implied_entities
                    )
                    discovery_text = discovery_engine.format_brief_for_prompt(
                        discovery_brief
                    )
                    if discovery_brief.total_row_estimate > 0:
                        result_validator.set_expectations(
                            expected_row_estimate=discovery_brief.total_row_estimate,
                        )
                    for vf in discovery_brief.verified_filters:
                        if vf.status == "exact_match":
                            memory.add_verified_filter(
                                f"{vf.column}={vf.value}", vf.row_count
                            )
                except Exception as e:
                    logger.warning(f"Pre-flight discovery failed: {e}")

            # Build system prompt
            schema_text = await self.schema_cache.get_schema_text()
            system_prompt = build_system_prompt(
                schema_text=schema_text,
                plugin=self.plugin,
                few_shot=self.few_shot,
                discovery_text=discovery_text,
                memory_text=memory.format_for_prompt(),
                strategy_text=strategy_tracker.get_escalation_context(),
            )

            # Build messages
            messages: List[Dict[str, Any]] = [
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
                    temperature=0.1,
                    max_tokens=16384,
                )

                content = llm_response.content
                tool_calls = llm_response.tool_calls

                # Capture thinking
                if content:
                    thinking_steps.append({
                        "iteration": iteration + 1,
                        "phase": current_phase if tool_calls else "final_answer",
                        "reasoning": content[:200],
                        "monologue": content[:MONOLOGUE_MAX_LEN],
                        "tools_called": [tc.name for tc in tool_calls] if tool_calls else [],
                    })

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
                    return QueryResponse(
                        success=True,
                        answer=final_answer,
                        chat_id=chat_id,
                        queries_executed=len(query_log),
                        query_log=[QueryLogEntry(**e) for e in query_log],
                        total_time_ms=elapsed_ms,
                        last_sql=_extract_last_sql(query_log),
                        thinking_steps=thinking_steps,
                        confidence_score=confidence,
                        validation_notes=all_validation_notes,
                    )

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

                    tool_result = await self._dispatch_tool_by_name(
                        tc.name, args, query_log, iteration + 1
                    )

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
            return QueryResponse(
                success=True,
                answer="I ran out of query iterations. Here's what I found so far.",
                chat_id=chat_id,
                queries_executed=len(query_log),
                query_log=[QueryLogEntry(**e) for e in query_log],
                total_time_ms=elapsed_ms,
                last_sql=_extract_last_sql(query_log),
                thinking_steps=thinking_steps,
                confidence_score=confidence,
                validation_notes=all_validation_notes,
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(f"AgentLoop error: {e}", exc_info=True)
            return QueryResponse(
                success=False,
                answer=f"Error: {str(e)}",
                chat_id=chat_id,
                queries_executed=len(query_log),
                query_log=[QueryLogEntry(**e) for e in query_log],
                total_time_ms=elapsed_ms,
                thinking_steps=thinking_steps,
                validation_notes=all_validation_notes,
                confidence_score=0.1,
            )

    async def _dispatch_tool_by_name(
        self,
        tool_name: str,
        args: Dict[str, Any],
        query_log: List[Dict[str, Any]],
        iteration: int,
    ) -> Dict[str, Any]:
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
        else:
            query_log.append({
                "iteration": iteration,
                "error": f"Unknown tool: {tool_name}",
            })
            return {"error": f"Unknown tool: {tool_name}"}
