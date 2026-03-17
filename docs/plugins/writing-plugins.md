# Writing Plugins

Plugins inject domain-specific knowledge into QueryBridge to improve accuracy.

## Basic Plugin

```python
from querybridge.plugins.base import DomainPlugin

class MyPlugin(DomainPlugin):
    def get_name(self) -> str:
        return "my-domain"

    def get_system_prompt_context(self) -> str:
        return "This database contains customer support tickets."
```

## Full Plugin API

See the [Plugin API Reference](api.md) for all available methods.

| Method | Purpose |
|--------|---------|
| `get_name()` | Plugin identifier |
| `get_entity_patterns()` | Regex patterns for entity extraction |
| `get_entity_column_map()` | Map entity types → database columns |
| `get_column_annotations()` | Human-readable column descriptions |
| `get_column_hierarchy()` | Column escalation paths |
| `get_system_prompt_context()` | Additional system prompt text |
| `get_few_shot_examples()` | Example question→SQL pairs |
| `get_question_type_patterns()` | Custom question classifiers |
| `get_custom_tools()` | Domain-specific LLM tools |
| `get_response_formatting_rules()` | Output formatting instructions |

## Registration

### Direct

```python
engine = QueryBridgeEngine(
    connector=..., llm=...,
    plugin=MyPlugin(),
)
```

### Entry Point (auto-discovery)

In your `pyproject.toml`:

```toml
[project.entry-points."querybridge.plugins"]
my-domain = "my_package.plugin:MyPlugin"
```

Then QueryBridge can discover it:

```python
from querybridge.plugins.registry import PluginRegistry

registry = PluginRegistry()
registry.discover_entry_points()
plugin = registry.get("my-domain")
```
