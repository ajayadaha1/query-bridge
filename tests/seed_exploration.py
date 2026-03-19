#!/usr/bin/env python3
"""
Exploration Memory Seeding Script

Runs a series of targeted queries against QueryBridge to seed the
exploration memory with foundational knowledge about all datasources.

After running this, the agent will have cached knowledge about:
- Table structures and column profiles
- Row counts and large-table warnings
- Schema topology (especially Snowflake COMMON schema)
- Routing preferences (which DB answers what)
- Key relationships between tables

Usage:
    python tests/seed_exploration.py
    python tests/seed_exploration.py --check   # Just show current memory state
    python tests/seed_exploration.py --clear   # Clear and re-seed
"""

import argparse
import json
import subprocess
import sys
import time
from typing import Any

import httpx

API_BASE = "http://localhost:8200"
TIMEOUT = 180


def chat(message: str, datasource_ids: list[str] | None = None) -> dict[str, Any]:
    """Send a chat request and return the parsed response."""
    body: dict[str, Any] = {"message": message}
    if datasource_ids:
        body["datasource_ids"] = datasource_ids
    with httpx.Client(base_url=API_BASE, timeout=TIMEOUT) as client:
        resp = client.post("/api/chat", json=body)
        resp.raise_for_status()
        return resp.json()


def check_memory() -> dict[str, Any]:
    """Check exploration memory state via docker exec."""
    cmd = [
        "docker", "exec", "querybridge_api", "python3", "-c",
        """
import json
from querybridge.memory.exploration import ExplorationMemory

results = {}
for ds in ['default', 'demo', 'snowflake']:
    em = ExplorationMemory(datasource=ds)
    with em._connect() as conn:
        rows = conn.execute(
            'SELECT note_type, subject, confidence, times_used, content '
            'FROM exploration_notes WHERE datasource = ? '
            'ORDER BY note_type, subject',
            (ds,)
        ).fetchall()
        results[ds] = [
            {'type': r[0], 'subject': r[1], 'confidence': r[2],
             'times_used': r[3], 'content': r[4][:150]}
            for r in rows
        ]

print(json.dumps(results, indent=2))
"""
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"Error checking memory: {result.stderr}")
        return {}
    return json.loads(result.stdout)


def clear_memory():
    """Clear all exploration memory."""
    cmd = [
        "docker", "exec", "querybridge_api", "python3", "-c",
        """
import os, glob
for f in glob.glob('/tmp/querybridge_cache/exploration_memory*.db'):
    os.remove(f)
    print(f'Removed {f}')
print('Memory cleared.')
"""
    ]
    subprocess.run(cmd, timeout=10)


def run_query(label: str, message: str, datasource_ids: list[str] | None = None):
    """Run a query and print summary."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  Q: {message[:80]}{'...' if len(message) > 80 else ''}")
    print(f"{'='*70}")

    t0 = time.time()
    try:
        result = chat(message, datasource_ids)
        elapsed = time.time() - t0
        print(f"  Answer: {result['answer'][:120]}...")
        print(f"  Confidence: {result['confidence']:.2f}")
        print(f"  Iterations: {result['iterations_used']}")
        print(f"  Queries: {result['queries_executed']}")
        print(f"  Time: {elapsed:.1f}s ({result['total_time_ms']}ms API)")
        if result.get("routed_to"):
            print(f"  Routed to: {result['routed_to']}")
        return result
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR after {elapsed:.1f}s: {e}")
        return None


def seed_silicon_trace():
    """Seed Silicon Trace exploration memory."""
    ds = ["default"]
    print("\n" + "=" * 70)
    print("  PHASE 1: SILICON TRACE (PostgreSQL)")
    print("=" * 70)

    # 1. Table structure discovery
    run_query(
        "ST-1: Assets table structure",
        "Describe the structure of the assets table — list all columns and their types",
        datasource_ids=ds,
    )

    # 2. Row count
    run_query(
        "ST-2: Record count",
        "How many total records are in the assets table?",
        datasource_ids=ds,
    )

    # 3. Error type distribution (teaches column relevance)
    run_query(
        "ST-3: Error type distribution",
        "What are the top 10 most common error types and their counts?",
        datasource_ids=ds,
    )

    # 4. Customer distribution
    run_query(
        "ST-4: Customer distribution",
        "Show the distribution of customers (original_customer or customer_category) with counts",
        datasource_ids=ds,
    )

    # 5. Status breakdown
    run_query(
        "ST-5: Status categories",
        "What are all the distinct status categories and their counts?",
        datasource_ids=ds,
    )

    # 6. Failure analysis columns (teaches column relevance on wide table)
    run_query(
        "ST-6: Failure category analysis",
        "Show me failure_category, severity, and tier results (tier_l0, tier_l1, tier_l2) for the first 5 records",
        datasource_ids=ds,
    )

    # 7. Serial number lookup (teaches specific query pattern)
    run_query(
        "ST-7: Serial lookup",
        "Get all information for serial number 9ME1172X50059",
        datasource_ids=ds,
    )


def seed_chinook():
    """Seed Chinook exploration memory."""
    ds = ["demo"]
    print("\n" + "=" * 70)
    print("  PHASE 2: CHINOOK (SQLite Demo)")
    print("=" * 70)

    # 1. Schema discovery
    run_query(
        "CH-1: Schema overview",
        "What tables exist in the Chinook database? List them all.",
        datasource_ids=ds,
    )

    # 2. Track count
    run_query(
        "CH-2: Track count",
        "How many tracks are in the tracks table?",
        datasource_ids=ds,
    )

    # 3. Artist-Album-Track relationship
    run_query(
        "CH-3: Top artists by tracks",
        "Who are the top 5 artists with the most tracks? Show artist name and track count.",
        datasource_ids=ds,
    )

    # 4. Revenue query (multi-table join)
    run_query(
        "CH-4: Revenue by country",
        "What are the top 5 countries by total invoice revenue?",
        datasource_ids=ds,
    )

    # 5. Genre breakdown
    run_query(
        "CH-5: Genre distribution",
        "Show number of tracks per genre, sorted by count descending",
        datasource_ids=ds,
    )


def seed_snowflake():
    """Seed Snowflake exploration memory."""
    ds = ["snowflake"]
    print("\n" + "=" * 70)
    print("  PHASE 3: SNOWFLAKE (MFG_PROD)")
    print("=" * 70)

    # 1. Schema discovery (critical — teaches COMMON schema)
    run_query(
        "SF-1: Available schemas",
        "What schemas exist in the Snowflake MFG_PROD database? List all schemas and their tables.",
        datasource_ids=ds,
    )

    # 2. COMMON schema tables
    run_query(
        "SF-2: COMMON schema tables",
        "What tables exist in the COMMON schema of MFG_PROD?",
        datasource_ids=ds,
    )

    # 3. CIP trace table (small, safe to explore)
    run_query(
        "SF-3: CIP trace structure",
        "Describe the COMMON.SAMPLE_CIP_TRACE table — show all columns and row count",
        datasource_ids=ds,
    )

    # 4. Component trace table
    run_query(
        "SF-4: Component trace structure",
        "Show the structure of COMMON.SAMPLE_COMPONENT_TRACE — all columns and row count",
        datasource_ids=ds,
    )

    # 5. CIP trace data
    run_query(
        "SF-5: CIP trace data",
        "Show all records from COMMON.SAMPLE_CIP_TRACE for component vendor part K4CHE1K6AB-3EF",
        datasource_ids=ds,
    )

    # 6. DATACENTER_HEALTH table sizes (teaches large table warnings)
    run_query(
        "SF-6: Table sizes",
        "What are the row counts for tables in DATACENTER_HEALTH schema? Use count estimate, not exact counts.",
        datasource_ids=ds,
    )


def seed_routing():
    """Seed multi-DB routing knowledge."""
    print("\n" + "=" * 70)
    print("  PHASE 4: ROUTING LEARNING")
    print("=" * 70)

    # 1. Silicon Trace specific question (should learn to route here)
    run_query(
        "RT-1: Failure query routing",
        "What are the most common failure types in silicon trace?",
    )

    # 2. Chinook specific question
    run_query(
        "RT-2: Music query routing",
        "Who are the best selling artists in the music store?",
    )

    # 3. Snowflake specific question
    run_query(
        "RT-3: Manufacturing query routing",
        "Show me CIP trace test results from the manufacturing database",
    )

    # 4. Meta question
    run_query(
        "RT-4: Meta question",
        "Which databases are connected and what types of data do they contain?",
    )


def print_memory_summary():
    """Print a summary of the exploration memory state."""
    print("\n" + "=" * 70)
    print("  EXPLORATION MEMORY STATE")
    print("=" * 70)

    memory = check_memory()
    if not memory:
        print("  Could not read memory state.")
        return

    total = 0
    for ds, notes in memory.items():
        if notes:
            print(f"\n  [{ds}] — {len(notes)} notes:")
            for n in notes:
                print(f"    [{n['type']}] {n['subject']} "
                      f"(conf={n['confidence']:.2f}, used={n['times_used']})")
                print(f"      {n['content'][:100]}...")
            total += len(notes)
        else:
            print(f"\n  [{ds}] — no notes")

    print(f"\n  TOTAL: {total} exploration notes across {len(memory)} datasources")


def main():
    parser = argparse.ArgumentParser(description="Seed QueryBridge Exploration Memory")
    parser.add_argument("--check", action="store_true", help="Just show current memory state")
    parser.add_argument("--clear", action="store_true", help="Clear memory before seeding")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4],
                        help="Run specific phase only (1=ST, 2=CH, 3=SF, 4=routing)")
    args = parser.parse_args()

    # Verify API is up
    try:
        health = httpx.get(f"{API_BASE}/health", timeout=10).json()
        print(f"API Status: {health['status']}, Datasources: {health['datasources']}")
    except Exception as e:
        print(f"ERROR: API not available at {API_BASE}: {e}")
        sys.exit(1)

    if args.check:
        print_memory_summary()
        return

    if args.clear:
        print("Clearing exploration memory...")
        clear_memory()
        # Restart container to re-initialize
        print("Restarting API container...")
        subprocess.run(["docker", "compose", "-f",
                         "/home/ajayad/FailSafeDashboard/query-bridge/docker-compose.yml",
                         "restart", "api"], timeout=30)
        time.sleep(5)

    start = time.time()

    if args.phase is None or args.phase == 1:
        seed_silicon_trace()
    if args.phase is None or args.phase == 2:
        seed_chinook()
    if args.phase is None or args.phase == 3:
        seed_snowflake()
    if args.phase is None or args.phase == 4:
        seed_routing()

    elapsed = time.time() - start
    print(f"\n{'='*70}")
    print(f"  SEEDING COMPLETE — {elapsed:.0f}s total")
    print(f"{'='*70}")

    print_memory_summary()


if __name__ == "__main__":
    main()
