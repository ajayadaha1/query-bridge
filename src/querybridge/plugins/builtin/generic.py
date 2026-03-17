"""Generic (no-domain) plugin — default when no domain plugin is provided."""

from querybridge.plugins.base import DomainPlugin


class GenericPlugin(DomainPlugin):
    """Default no-domain plugin."""

    def get_name(self) -> str:
        return "generic"
