"""ManufacturingPlugin — Domain knowledge for semiconductor/datacenter manufacturing data.

Supports both:
- Silicon Trace (PostgreSQL) with analysis_facts as primary query surface
- Snowflake MFG_PROD with datacenter health tables

Provides:
- Serial number entity detection + column hierarchy escalation
- Customer resolution patterns (suffix-based, normalized names)
- Join hints for complex multi-table relationships
- Few-shot examples for common manufacturing queries
"""

from __future__ import annotations

from querybridge.plugins.base import DomainPlugin


class ManufacturingPlugin(DomainPlugin):
    """Domain plugin for semiconductor manufacturing / datacenter health data."""

    def get_name(self) -> str:
        return "manufacturing"

    def get_entity_patterns(self) -> dict[str, list[str]]:
        return {
            "serial_number": [
                r"\b\d[A-Z0-9]{2,4}\d{3}[A-Z]\d{4,6}\b",  # e.g. 9AMA377P50091
                r"\b\d[A-Z0-9]{2,4}\d{3}[A-Z]\d{4,6}_\d{3}-\d{9}\b",  # full with suffix
                r"\bserial\s+(?:number\s+)?[\w-]+",
            ],
            "customer": [
                r"\b(?:ALIBABA|TENCENT|MICROSOFT|GOOGLE|META|AMAZON|ORACLE|BYTEDANCE)\b",
            ],
            "error_category": [
                r"\b(?:IFPO|AFHC|DRAM|ECC|MCE|MCA|PCIE|NVMe|BMC|SEL)\b",
            ],
            "tier": [
                r"\btier[_\s]*(?:l?\d+|afhc)\b",
            ],
        }

    def get_entity_column_map(self) -> dict[str, list[str]]:
        return {
            "serial_number": [
                "serial_number",
                "serial_normalized",
                "internal_serial_number",
                "system_serial_number",
                "baseboard_serial",
                "wafer_lot_id",
            ],
            "customer": [
                "customer_normalized",
                "customer_category",
                "customer_name",
                "customer",
            ],
            "error_category": [
                "error_category",
                "error_type_normalized",
                "error_type",
                "failure_category",
            ],
            "tier": [
                "tier_l0",
                "tier_l1",
                "tier_l2",
                "tier_afhc",
            ],
        }

    def get_column_annotations(self) -> dict[str, str]:
        return {
            "serial_number": "Full serial with customer suffix (e.g. 9AMA377P50091_100-000001359)",
            "serial_normalized": "Base serial without suffix — cross-file matching key",
            "internal_serial_number": "Internal manufacturing serial, different from external",
            "customer_normalized": "Canonical customer name (uppercase: ALIBABA, TENCENT, etc.)",
            "customer_category": "Same as customer_normalized in some schemas",
            "error_category": "High-level error type (IFPO, AFHC, DRAM, ECC, etc.)",
            "error_type_normalized": "Normalized error description",
            "tier_l0": "Test tier level 0 result (PASS/FAIL)",
            "tier_l1": "Test tier level 1 result (PASS/FAIL)",
            "tier_l2": "Test tier level 2 result (PASS/FAIL)",
            "tier_afhc": "AFHC (Automatic Failure Hardware Check) result",
            "severity": "Failure severity level",
            "failure_category": "Broad failure classification",
            "failure_subcategory": "Specific failure classification",
            "fa_conclusion": "Failure analysis conclusion (often high NULL rate)",
            "ccd": "Compute Complex Die identifier",
            "ccx": "Compute Complex identifier within CCD",
            "bank": "Memory bank identifier",
            "failed_core": "Core that failed (for CPU-level failures)",
            "upload_id": "References uploads table (source file tracking)",
            "asset_id": "References assets table (unique asset record)",
        }

    def get_column_hierarchy(self) -> list[list[str]]:
        return [
            # Serial number escalation: most specific → least specific
            ["serial_number", "serial_normalized", "internal_serial_number", "system_serial_number", "baseboard_serial", "wafer_lot_id"],
            # Customer resolution chain
            ["customer_normalized", "customer_category", "customer_name", "customer"],
            # Error type escalation
            ["error_type_normalized", "error_category", "failure_subcategory", "failure_category"],
            # Tier test results (not a hierarchy, but useful for escalation)
            ["tier_l0", "tier_l1", "tier_l2", "tier_afhc"],
        ]

    def get_system_prompt_context(self) -> str:
        return """## Manufacturing Domain Knowledge

### Serial Number Resolution
- `serial_number`: Full serial with customer suffix (e.g., 9AMA377P50091_100-000001359)
- `serial_normalized`: Base serial without suffix — the primary cross-file matching key
- The last 4 digits of the suffix map to a customer via `customer_master.serial_suffixes`
- Multiple serials may exist: internal_serial_number, system_serial_number, baseboard_serial

### Customer Resolution
- Always use `customer_normalized` (or `customer_category`) for customer filtering
- Values are UPPERCASE: 'ALIBABA', 'TENCENT', 'MICROSOFT', etc.
- Use ILIKE for case-insensitive matching

### Key Join Patterns
- `analysis_facts` is the primary query surface (flattened materialized view)
  - Join: `analysis_facts.asset_id → assets.id`
  - Join: `analysis_facts.upload_id → uploads.id`
- `processed_assets` contains AI-extracted golden columns
- `source_contributions` contains per-file raw data layers
- For customer resolution: check `customer_master` table if present

### Test Tiers
- Tiers represent test stage results: tier_l0 (earliest) → tier_afhc (final AFHC test)
- Values are typically PASS/FAIL or specific result codes
- fa_conclusion has high NULL rate (~70%) — handle with COALESCE or IS NOT NULL filters

### Common Gotchas
- `customer` column may not exist — use `customer_normalized` or `customer_category`
- Serial numbers are case-sensitive in some tables
- Date columns: check for `created_at`, `upload_date`, `test_date`, `processed_at`
- Large result sets: always use GROUP BY with aggregates, avoid SELECT *"""

    def get_few_shot_examples(self) -> list[dict[str, str]]:
        return [
            {
                "question": "How many assets are there per customer?",
                "sql": "SELECT customer_normalized, COUNT(*) AS asset_count FROM analysis_facts GROUP BY customer_normalized ORDER BY asset_count DESC",
                "explanation": "Use customer_normalized for grouping, analysis_facts as primary table",
            },
            {
                "question": "Show me the failure rate by error category",
                "sql": "SELECT error_category, COUNT(*) AS total, ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS pct FROM analysis_facts WHERE error_category IS NOT NULL GROUP BY error_category ORDER BY total DESC",
                "explanation": "Filter out NULLs, use window function for percentage",
            },
            {
                "question": "What are the top 10 serial numbers with the most failures?",
                "sql": "SELECT serial_normalized, COUNT(*) AS failure_count FROM analysis_facts WHERE failure_category IS NOT NULL GROUP BY serial_normalized ORDER BY failure_count DESC LIMIT 10",
                "explanation": "Use serial_normalized for grouping, filter to actual failures",
            },
            {
                "question": "Show tier progression for a specific serial number",
                "sql": "SELECT serial_normalized, tier_l0, tier_l1, tier_l2, tier_afhc, error_category, severity FROM analysis_facts WHERE serial_normalized ILIKE '%ABC123%' ORDER BY created_at",
                "explanation": "Show all tier results to trace the test progression",
            },
            {
                "question": "Which customers have the highest failure rates?",
                "sql": "SELECT customer_normalized, COUNT(*) AS total_assets, SUM(CASE WHEN failure_category IS NOT NULL THEN 1 ELSE 0 END) AS failures, ROUND(SUM(CASE WHEN failure_category IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS failure_rate_pct FROM analysis_facts GROUP BY customer_normalized HAVING COUNT(*) >= 10 ORDER BY failure_rate_pct DESC",
                "explanation": "Calculate failure rate per customer, require minimum sample size",
            },
        ]

    def get_question_type_patterns(self) -> dict[str, list[str]]:
        return {
            "failure_analysis": [
                r"\bfailur(?:e|es)\b.*\b(?:rate|count|analysis)\b",
                r"\bfailed?\b.*\b(?:serial|asset|component)\b",
            ],
            "tier_progression": [
                r"\btier\b.*\b(?:progress|result|pass|fail)\b",
            ],
            "customer_analysis": [
                r"\bcustomer\b.*\b(?:error|failure|breakdown|distribution)\b",
            ],
            "serial_lookup": [
                r"\bserial\b.*\b(?:look|find|show|detail|info)\b",
                r"\b\d[A-Z0-9]{2,4}\d{3}[A-Z]\d{4,6}\b",
            ],
        }

    def get_response_formatting_rules(self) -> str:
        return """## Manufacturing Response Formatting
- Serial numbers: Display in monospace (`serial_here`)
- Failure rates: Show as percentage with 2 decimal places
- Customer names: Use canonical uppercase form
- Tier results: Show in order L0 → L1 → L2 → AFHC
- Always note if fa_conclusion has high NULL rate in the results"""

    def get_primary_table(self) -> str | None:
        return "analysis_facts"
