"""Custom Domain Plugin — Teach QueryBridge about your domain.

This example creates a plugin for an e-commerce database
that injects domain knowledge for higher accuracy.
"""

import asyncio
from querybridge import QueryBridgeEngine, EngineConfig
from querybridge.connectors.postgresql import PostgreSQLConnector
from querybridge.llm.openai_provider import OpenAIProvider
from querybridge.plugins.base import DomainPlugin


class EcommercePlugin(DomainPlugin):
    """Domain plugin for an e-commerce database."""

    def get_name(self) -> str:
        return "ecommerce"

    def get_entity_patterns(self):
        """Regex patterns to extract entities from user questions."""
        return {
            "order_id": [r"ORD-\d+", r"order\s+#?\d+"],
            "sku": [r"SKU-[A-Z0-9]+"],
            "customer_email": [r"[\w.+-]+@[\w-]+\.[\w.]+"],
        }

    def get_entity_column_map(self):
        """Map entity types to database columns for verification."""
        return {
            "order_id": ["orders.order_id", "returns.order_id"],
            "sku": ["products.sku", "order_items.sku"],
            "customer_email": ["customers.email"],
        }

    def get_column_annotations(self):
        """Describe columns to help the LLM understand the data."""
        return {
            "orders.status": "Values: pending, processing, shipped, delivered, cancelled, refunded",
            "orders.total": "Order total in USD, includes tax and shipping",
            "products.price": "Base price in USD before discounts",
            "customers.tier": "Values: bronze, silver, gold, platinum — based on lifetime spend",
        }

    def get_system_prompt_context(self):
        """Extra context injected into the system prompt."""
        return (
            "This is an e-commerce database for an online retail store. "
            "Key business rules: "
            "- Revenue = SUM(order_items.quantity * order_items.unit_price) "
            "- Active customers = ordered in last 90 days "
            "- Churn = no orders in 180+ days"
        )

    def get_few_shot_examples(self):
        """Teach the LLM common query patterns for this domain."""
        return [
            {
                "question": "What are the top selling products this month?",
                "sql": (
                    "SELECT p.name, SUM(oi.quantity) as units_sold, "
                    "SUM(oi.quantity * oi.unit_price) as revenue "
                    "FROM order_items oi "
                    "JOIN products p ON oi.product_id = p.id "
                    "JOIN orders o ON oi.order_id = o.id "
                    "WHERE o.created_at >= DATE_TRUNC('month', CURRENT_DATE) "
                    "GROUP BY p.name ORDER BY revenue DESC LIMIT 10"
                ),
                "explanation": "Join orders → items → products, filter to current month",
            },
            {
                "question": "Customer churn rate",
                "sql": (
                    "SELECT COUNT(*) FILTER (WHERE last_order < NOW() - INTERVAL '180 days') * 100.0 / "
                    "COUNT(*) as churn_rate FROM customers WHERE first_order IS NOT NULL"
                ),
                "explanation": "Churn = no order in 180+ days, as percentage of all customers",
            },
        ]

    def get_column_hierarchy(self):
        """Column escalation paths for strategy tracker."""
        return [
            ["products.sku", "products.name", "products.category"],
            ["orders.status", "orders.total"],
        ]


async def main():
    async with QueryBridgeEngine(
        connector=PostgreSQLConnector("postgresql://user:pass@localhost/ecommerce"),
        llm=OpenAIProvider(api_key="sk-..."),
        plugin=EcommercePlugin(),
    ) as engine:
        response = await engine.query("What's our revenue trend this quarter?")
        print(response.answer)


if __name__ == "__main__":
    asyncio.run(main())
