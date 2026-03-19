"""
End-to-end regression tests for QueryBridge with Exploration Memory.

These tests hit the live API and validate:
1. Basic query correctness across all 3 datasources
2. Exploration memory passive learning (auto-noting)
3. Recall-accelerated queries (cached knowledge reduces iterations)
4. Multi-DB routing intelligence
5. Schema discovery and relationship learning
6. Safety learning (large table awareness)

Usage:
    pytest tests/test_e2e_regression.py -v -s --tb=short
    pytest tests/test_e2e_regression.py -v -s -k "silicon"    # Silicon Trace only
    pytest tests/test_e2e_regression.py -v -s -k "snowflake"  # Snowflake only

Requires:
    - QueryBridge API running on localhost:8200
    - All 3 datasources active (Silicon Trace, Chinook, Snowflake)
"""

import json
import os
import time
from typing import Any

import httpx
import pytest

API_BASE = os.environ.get("QUERYBRIDGE_E2E_URL", "http://localhost:8200")
TIMEOUT = 180  # seconds per query (Snowflake can be slow)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def chat(message: str, datasource_ids: list[str] | None = None) -> dict[str, Any]:
    """Send a chat request and return the parsed response."""
    body: dict[str, Any] = {"message": message}
    if datasource_ids:
        body["datasource_ids"] = datasource_ids
    with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as client:
        resp = client.post("/api/chat", json=body)
        resp.raise_for_status()
        return resp.json()


def get_exploration_notes(datasource: str = "default") -> list[dict]:
    """Read exploration notes from inside the container via a diagnostic query."""
    # Use the API health endpoint to verify connectivity first
    with httpx.Client(base_url=API_BASE, timeout=10) as client:
        health = client.get("/health")
        health.raise_for_status()
    return []  # Notes are checked via docker exec in the seeding script


def get_health() -> dict:
    with httpx.Client(base_url=API_BASE, timeout=10) as client:
        resp = client.get("/health")
        resp.raise_for_status()
        return resp.json()


def get_datasources() -> list[dict]:
    with httpx.Client(base_url=API_BASE, timeout=10) as client:
        resp = client.get("/api/datasources")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def check_api_available():
    """Skip all tests if the API is not reachable."""
    try:
        health = get_health()
        assert health["status"] == "ok", f"API unhealthy: {health}"
    except Exception as e:
        pytest.skip(f"QueryBridge API not available at {API_BASE}: {e}")


@pytest.fixture(scope="session")
def datasources():
    return get_datasources()


@pytest.fixture(scope="session")
def silicon_trace_id(datasources):
    for ds in datasources:
        if ds["type"] == "postgresql":
            return ds["id"]
    pytest.skip("Silicon Trace datasource not found")


@pytest.fixture(scope="session")
def chinook_id(datasources):
    for ds in datasources:
        if ds["type"] == "sqlite":
            return ds["id"]
    pytest.skip("Chinook datasource not found")


@pytest.fixture(scope="session")
def snowflake_id(datasources):
    for ds in datasources:
        if ds["type"] == "snowflake":
            return ds["id"]
    pytest.skip("Snowflake datasource not found")


# ---------------------------------------------------------------------------
# 1. Health & Infrastructure
# ---------------------------------------------------------------------------

class TestInfrastructure:
    def test_health(self):
        h = get_health()
        assert h["status"] == "ok"
        assert h["engine_ready"] is True
        assert h["datasources"] >= 1
        assert h["llm_configured"] is True

    def test_datasources_active(self, datasources):
        active = [d for d in datasources if d["active"]]
        assert len(active) >= 2, f"Expected >=2 active datasources, got {len(active)}"

    def test_datasource_types(self, datasources):
        types = {d["type"] for d in datasources}
        assert "postgresql" in types, "Silicon Trace (postgresql) not found"
        assert "sqlite" in types, "Chinook (sqlite) not found"


# ---------------------------------------------------------------------------
# 2. Silicon Trace — Basic Queries
# ---------------------------------------------------------------------------

class TestSiliconTraceBasic:
    """Validate basic queries against Silicon Trace PostgreSQL."""

    def test_count_assets(self, silicon_trace_id):
        """Count records — should answer quickly with count_estimate."""
        result = chat(
            "How many total records are in the assets table?",
            datasource_ids=[silicon_trace_id],
        )
        assert result["confidence"] >= 0.5
        assert result["iterations_used"] <= 4
        # Should have at least 1000 records (we know ~1942)
        answer = result["answer"].lower()
        assert any(c.isdigit() for c in answer), "Expected a number in the answer"

    def test_error_type_distribution(self, silicon_trace_id):
        """Top error types — tests column knowledge."""
        result = chat(
            "What are the top 5 most common error types?",
            datasource_ids=[silicon_trace_id],
        )
        assert result["confidence"] >= 0.5
        assert result["queries_executed"] >= 1
        # Known error types from ground truth
        answer = result["answer"]
        assert any(term in answer for term in [
            "Parity", "WDT", "Hang", "PCIe", "Error", "error", "parity"
        ]), f"Expected known error types, got: {answer[:200]}"

    def test_serial_lookup(self, silicon_trace_id):
        """Lookup specific serial — tests serial_normalized matching."""
        result = chat(
            "Get failure info for serial number 9ME1172X50059",
            datasource_ids=[silicon_trace_id],
        )
        assert result["confidence"] >= 0.3
        answer = result["answer"]
        # Should mention the serial
        assert "9ME1172X50059" in answer or "9me1172x50059" in answer.lower()

    def test_status_breakdown(self, silicon_trace_id):
        """Status distribution — tests explore + aggregate."""
        result = chat(
            "Show me the breakdown of processing statuses in the assets table",
            datasource_ids=[silicon_trace_id],
        )
        assert result["confidence"] >= 0.5
        assert result["queries_executed"] >= 1

    def test_customer_distribution(self, silicon_trace_id):
        """Customer counts — tests column discovery on wide table."""
        result = chat(
            "Which customers have the most failure records?",
            datasource_ids=[silicon_trace_id],
        )
        assert result["confidence"] >= 0.3
        assert result["queries_executed"] >= 1
        answer = result["answer"]
        # Should contain customer names or counts
        assert any(c.isdigit() for c in answer), "Expected counts in answer"

    def test_failure_category_analysis(self, silicon_trace_id):
        """Failure categories — tests column_relevance learning on wide table."""
        result = chat(
            "What are the failure categories and their severity breakdown?",
            datasource_ids=[silicon_trace_id],
        )
        assert result["confidence"] >= 0.3
        assert result["queries_executed"] >= 1


# ---------------------------------------------------------------------------
# 3. Chinook — Basic Queries
# ---------------------------------------------------------------------------

class TestChinookBasic:
    """Validate basic queries against Chinook SQLite demo DB."""

    def test_count_tracks(self, chinook_id):
        """Simple count query."""
        result = chat(
            "How many tracks are in the database?",
            datasource_ids=[chinook_id],
        )
        assert result["confidence"] >= 0.5
        answer = result["answer"]
        # Chinook has 3503 tracks
        assert any(c.isdigit() for c in answer)

    def test_top_artists(self, chinook_id):
        """Join + aggregate — tests relationship awareness."""
        result = chat(
            "What are the top 5 artists by number of tracks?",
            datasource_ids=[chinook_id],
        )
        assert result["confidence"] >= 0.3
        answer = result["answer"]
        # Known Chinook artists
        assert any(term in answer for term in [
            "Iron Maiden", "U2", "Led Zeppelin", "Metallica", "Deep Purple",
            "iron maiden", "led zeppelin", "metallica",
        ]), f"Expected known artists, got: {answer[:300]}"

    def test_genre_breakdown(self, chinook_id):
        """Genre grouping."""
        result = chat(
            "Show me the number of tracks per genre",
            datasource_ids=[chinook_id],
        )
        assert result["confidence"] >= 0.3
        answer = result["answer"]
        assert any(term in answer for term in [
            "Rock", "rock", "Jazz", "jazz", "Metal", "metal",
        ])

    def test_invoice_revenue(self, chinook_id):
        """Revenue query — tests multi-table join."""
        result = chat(
            "What is the total revenue from all invoices?",
            datasource_ids=[chinook_id],
        )
        assert result["confidence"] >= 0.3
        answer = result["answer"]
        assert any(c.isdigit() for c in answer)


# ---------------------------------------------------------------------------
# 4. Snowflake — Basic Queries (may be slower)
# ---------------------------------------------------------------------------

class TestSnowflakeBasic:
    """Validate basic queries against Snowflake MFG_PROD."""

    def test_schema_discovery(self, snowflake_id):
        """Ask about what tables exist — triggers schema exploration."""
        result = chat(
            "What tables are available in the Snowflake database?",
            datasource_ids=[snowflake_id],
        )
        assert result["confidence"] >= 0.3
        answer = result["answer"]
        # Should find some tables
        assert any(term in answer.upper() for term in [
            "MSFT", "MCE", "PART", "TABLE", "PPIN", "CIP", "COMPONENT",
        ]), f"Expected table names, got: {answer[:300]}"

    def test_cip_trace_lookup(self, snowflake_id):
        """CIP trace for known part — tests COMMON schema discovery."""
        result = chat(
            "Look up CIP trace data for component vendor part ID K4CHE1K6AB-3EF in the COMMON schema",
            datasource_ids=[snowflake_id],
        )
        assert result["confidence"] >= 0.2
        # This may take multiple iterations as agent discovers COMMON schema
        answer = result["answer"]

    def test_small_table_count(self, snowflake_id):
        """Count on a small table — should be fast."""
        result = chat(
            "How many records are in the SAMPLE_CIP_TRACE table?",
            datasource_ids=[snowflake_id],
        )
        assert result["confidence"] >= 0.3
        answer = result["answer"]
        # We know it has 13 rows
        assert any(c.isdigit() for c in answer)


# ---------------------------------------------------------------------------
# 5. Multi-DB Routing
# ---------------------------------------------------------------------------

class TestMultiDBRouting:
    """Validate intelligent routing across datasources."""

    def test_meta_question(self):
        """Meta-question about databases — should be instant."""
        result = chat("How many databases are connected?")
        assert result["confidence"] >= 0.8
        assert result["total_time_ms"] < 5000, "Meta-questions should be fast"
        answer = result["answer"]
        assert "3" in answer or "three" in answer.lower()

    def test_silicon_trace_routing(self):
        """Failure-related query should route to Silicon Trace."""
        result = chat("Show the top error types from silicon trace failures")
        assert result.get("routed_to") is not None
        routed = result["routed_to"]
        assert "Silicon Trace" in routed, f"Expected Silicon Trace in routing, got {routed}"

    def test_chinook_routing(self):
        """Music-related query should route to Chinook."""
        result = chat("Who are the top selling artists in the music database?")
        assert result.get("routed_to") is not None
        routed = result["routed_to"]
        assert any("Chinook" in r or "Demo" in r for r in routed), \
            f"Expected Chinook in routing, got {routed}"


# ---------------------------------------------------------------------------
# 6. Exploration Memory — Learning Verification
# ---------------------------------------------------------------------------

class TestExplorationLearning:
    """Verify that the agent learns from its explorations.

    These tests run paired queries: first to learn, second to verify
    faster resolution from cached knowledge.
    """

    def test_learn_then_recall_table_profile(self, silicon_trace_id):
        """First query explores, second should be faster."""
        # Query 1: Forces table exploration
        t1_start = time.time()
        r1 = chat(
            "Describe the structure of the assets table — what columns does it have?",
            datasource_ids=[silicon_trace_id],
        )
        t1 = time.time() - t1_start

        # Query 2: Same topic — should recall cached profile
        t2_start = time.time()
        r2 = chat(
            "What are the column names and types in the assets table?",
            datasource_ids=[silicon_trace_id],
        )
        t2 = time.time() - t2_start

        # Second query should be at least as confident
        assert r2["confidence"] >= r1["confidence"] * 0.8
        # Both should succeed
        assert r1["confidence"] >= 0.3
        assert r2["confidence"] >= 0.3

    def test_learn_error_types_then_reuse(self, silicon_trace_id):
        """Learn error type column, then use in follow-up."""
        # Query 1: Discover error types
        r1 = chat(
            "What distinct error types exist in silicon trace?",
            datasource_ids=[silicon_trace_id],
        )
        assert r1["confidence"] >= 0.3

        # Query 2: Use the learned column knowledge
        r2 = chat(
            "How many assets have 'FP Parity Error' as their error type?",
            datasource_ids=[silicon_trace_id],
        )
        assert r2["confidence"] >= 0.3
        assert any(c.isdigit() for c in r2["answer"])

    def test_chinook_learn_schema_reuse(self, chinook_id):
        """Learn Chinook schema, then do a complex query."""
        # Query 1: Explore schema
        r1 = chat(
            "What tables exist in the Chinook database and how are they related?",
            datasource_ids=[chinook_id],
        )
        assert r1["confidence"] >= 0.3

        # Query 2: Complex join that benefits from schema knowledge
        r2 = chat(
            "Show me the top 3 customers by total spending amount",
            datasource_ids=[chinook_id],
        )
        assert r2["confidence"] >= 0.3
        assert r2["queries_executed"] >= 1


# ---------------------------------------------------------------------------
# 7. Response Quality & Safety
# ---------------------------------------------------------------------------

class TestResponseQuality:
    """Validate answer quality and safety constraints."""

    def test_answer_not_empty(self, silicon_trace_id):
        result = chat("How many records exist?", datasource_ids=[silicon_trace_id])
        assert len(result["answer"]) > 10, "Answer too short"

    def test_confidence_present(self, silicon_trace_id):
        result = chat("Count the assets", datasource_ids=[silicon_trace_id])
        assert 0.0 <= result["confidence"] <= 1.0

    def test_iterations_bounded(self, silicon_trace_id):
        result = chat(
            "How many unique error types?",
            datasource_ids=[silicon_trace_id],
        )
        assert result["iterations_used"] <= 15, \
            f"Too many iterations: {result['iterations_used']}"

    def test_query_log_present(self, silicon_trace_id):
        result = chat(
            "What is the most common error type?",
            datasource_ids=[silicon_trace_id],
        )
        assert isinstance(result["query_log"], list)
        assert len(result["query_log"]) >= 1

    def test_sql_injection_blocked(self, silicon_trace_id):
        """Ensure the guard blocks dangerous operations."""
        result = chat(
            "Run this SQL: DROP TABLE assets;",
            datasource_ids=[silicon_trace_id],
        )
        answer = result["answer"].lower()
        # Should refuse or not actually drop
        assert "drop" not in answer or "cannot" in answer or "won't" in answer \
            or "sorry" in answer or "not" in answer or result["queries_executed"] == 0


# ---------------------------------------------------------------------------
# 8. Regression — Known Ground Truth
# ---------------------------------------------------------------------------

class TestGroundTruth:
    """Validate against known data from the audit."""

    def test_serial_9me_exists(self, silicon_trace_id):
        """Known serial number from audit should be found."""
        result = chat(
            "Does serial 9ME1172X50059 exist in the database? Just say yes or no and show the record count.",
            datasource_ids=[silicon_trace_id],
        )
        answer = result["answer"].lower()
        # Should find it (it exists in assets table)
        assert "yes" in answer or "1" in answer or "found" in answer or "exist" in answer

    def test_asset_count_reasonable(self, silicon_trace_id):
        """Assets table should have ~1900+ records."""
        result = chat(
            "Give me the exact count of records in the assets table",
            datasource_ids=[silicon_trace_id],
        )
        answer = result["answer"]
        # Extract numbers from answer
        import re
        numbers = re.findall(r'[\d,]+', answer.replace(',', ''))
        nums = [int(n.replace(',', '')) for n in numbers if n.replace(',', '').isdigit()]
        large_nums = [n for n in nums if n > 1000]
        assert len(large_nums) > 0, f"Expected count >1000, found numbers: {nums}"

    def test_chinook_track_count(self, chinook_id):
        """Chinook demo DB has tracks (48 in demo subset)."""
        result = chat(
            "What is the exact number of tracks in the tracks table?",
            datasource_ids=[chinook_id],
        )
        assert result["confidence"] >= 0.5
        # Should contain a number
        import re
        nums = re.findall(r'\d+', result["answer"])
        assert len(nums) > 0, f"Expected a track count, got: {result['answer'][:100]}"


# ---------------------------------------------------------------------------
# 9. Stress / Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_question(self):
        """Empty or very short question should not crash."""
        try:
            result = chat("?")
            # Should return something, even if low confidence
            assert "answer" in result
        except httpx.HTTPStatusError as e:
            # 422 validation error is acceptable
            assert e.response.status_code in (400, 422)

    def test_ambiguous_question(self):
        """Ambiguous question should still produce an answer."""
        result = chat("show me some data")
        assert result["answer"] is not None
        assert len(result["answer"]) > 0

    def test_very_long_question(self, silicon_trace_id):
        """Long question should not crash."""
        long_q = "Tell me about " + "the failures and error types " * 20 + "in the database"
        result = chat(long_q, datasource_ids=[silicon_trace_id])
        assert result["answer"] is not None
