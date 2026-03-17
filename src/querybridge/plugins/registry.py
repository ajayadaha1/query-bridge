"""PluginRegistry — Discovers and loads domain plugins."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from querybridge.plugins.base import DomainPlugin
from querybridge.plugins.builtin.generic import GenericPlugin

logger = logging.getLogger("querybridge.plugins.registry")


class PluginRegistry:
    """Discovers and loads domain plugins."""

    def __init__(self):
        self._plugins: dict[str, DomainPlugin] = {}
        self._register_builtin()

    def _register_builtin(self):
        self._plugins["generic"] = GenericPlugin()

    def register(self, plugin: DomainPlugin):
        """Register a plugin instance."""
        self._plugins[plugin.get_name()] = plugin
        logger.info(f"Registered plugin: {plugin.get_name()}")

    def get(self, name: str) -> DomainPlugin | None:
        """Get a registered plugin by name."""
        return self._plugins.get(name)

    def discover_entry_points(self):
        """Discover plugins from installed packages via entry points."""
        try:
            eps = entry_points()
            qb_eps: list = eps.get("querybridge.plugins", [])
            for ep in qb_eps:
                try:
                    plugin_cls = ep.load()
                    if isinstance(plugin_cls, type) and issubclass(plugin_cls, DomainPlugin):
                        self.register(plugin_cls())
                    elif isinstance(plugin_cls, DomainPlugin):
                        self.register(plugin_cls)
                except Exception as e:
                    logger.warning(f"Failed to load plugin {ep.name}: {e}")
        except Exception as e:
            logger.debug(f"Entry point discovery failed: {e}")

    @property
    def available(self) -> list[str]:
        return list(self._plugins.keys())
