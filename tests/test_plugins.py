"""Tests for the plugin system."""

from querybridge.plugins.base import DomainPlugin
from querybridge.plugins.builtin.generic import GenericPlugin
from querybridge.plugins.builtin.manufacturing import ManufacturingPlugin
from querybridge.plugins.registry import PluginRegistry


class TestGenericPlugin:
    def test_name(self):
        plugin = GenericPlugin()
        assert plugin.get_name() == "generic"

    def test_defaults_empty(self):
        plugin = GenericPlugin()
        assert plugin.get_entity_patterns() == {}
        assert plugin.get_entity_column_map() == {}
        assert plugin.get_column_annotations() == {}
        assert plugin.get_column_hierarchy() == []
        assert plugin.get_system_prompt_context() == ""
        assert plugin.get_few_shot_examples() == []
        assert plugin.get_question_type_patterns() == {}
        assert plugin.get_custom_tools() == []
        assert plugin.get_response_formatting_rules() == ""
        assert plugin.get_primary_table() is None


class TestCustomPlugin:
    def test_custom_plugin(self):
        class MyPlugin(DomainPlugin):
            def get_name(self):
                return "my-domain"

            def get_entity_patterns(self):
                return {"product_id": [r"PROD-\d+"]}

            def get_system_prompt_context(self):
                return "This is an e-commerce database."

        plugin = MyPlugin()
        assert plugin.get_name() == "my-domain"
        assert "product_id" in plugin.get_entity_patterns()
        assert "e-commerce" in plugin.get_system_prompt_context()


class TestPluginRegistry:
    def test_builtin_generic(self):
        registry = PluginRegistry()
        assert "generic" in registry.available
        plugin = registry.get("generic")
        assert plugin is not None
        assert plugin.get_name() == "generic"

    def test_register_custom(self):
        registry = PluginRegistry()

        class TestPlugin(DomainPlugin):
            def get_name(self):
                return "test"

        registry.register(TestPlugin())
        assert "test" in registry.available
        assert registry.get("test") is not None

    def test_get_nonexistent(self):
        registry = PluginRegistry()
        assert registry.get("nonexistent") is None

    def test_manufacturing_registered(self):
        registry = PluginRegistry()
        assert "manufacturing" in registry.available
        plugin = registry.get("manufacturing")
        assert plugin is not None
        assert plugin.get_name() == "manufacturing"


class TestManufacturingPlugin:
    def test_name(self):
        plugin = ManufacturingPlugin()
        assert plugin.get_name() == "manufacturing"

    def test_entity_patterns(self):
        plugin = ManufacturingPlugin()
        patterns = plugin.get_entity_patterns()
        assert "serial_number" in patterns
        assert "customer" in patterns
        assert "error_category" in patterns

    def test_entity_column_map(self):
        plugin = ManufacturingPlugin()
        ecm = plugin.get_entity_column_map()
        assert "serial_normalized" in ecm["serial_number"]
        assert "customer_normalized" in ecm["customer"]

    def test_column_hierarchy(self):
        plugin = ManufacturingPlugin()
        hierarchies = plugin.get_column_hierarchy()
        assert len(hierarchies) >= 3
        # Serial number hierarchy should start with most specific
        assert hierarchies[0][0] == "serial_number"
        assert "wafer_lot_id" in hierarchies[0]

    def test_few_shot_examples(self):
        plugin = ManufacturingPlugin()
        examples = plugin.get_few_shot_examples()
        assert len(examples) >= 3
        for ex in examples:
            assert "question" in ex
            assert "sql" in ex

    def test_system_prompt_context(self):
        plugin = ManufacturingPlugin()
        ctx = plugin.get_system_prompt_context()
        assert "Serial Number Resolution" in ctx
        assert "Customer Resolution" in ctx
        assert "analysis_facts" in ctx

    def test_primary_table(self):
        plugin = ManufacturingPlugin()
        assert plugin.get_primary_table() == "analysis_facts"

    def test_column_annotations(self):
        plugin = ManufacturingPlugin()
        annotations = plugin.get_column_annotations()
        assert "serial_normalized" in annotations
        assert "customer_normalized" in annotations
