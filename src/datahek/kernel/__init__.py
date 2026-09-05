"""DataHek kernel — foundational primitives and contracts."""

from datahek.kernel.capabilities import Capabilities
from datahek.kernel.config import Config, config_from_env, dump_safe
from datahek.kernel.context import RequestContext, TenantScope
from datahek.kernel.di import Container, NotResolvable
from datahek.kernel.entitlements import EntitlementProvider, ResourceLimits
from datahek.kernel.errors import DatahekError, ErrorCode
from datahek.kernel.events import DomainEvent, EventStore
from datahek.kernel.registry import AlreadyRegistered, ExtensionRegistry

__all__ = [
    "Capabilities", "Config", "config_from_env", "dump_safe",
    "RequestContext", "TenantScope", "Container", "NotResolvable",
    "EntitlementProvider", "ResourceLimits", "DatahekError", "ErrorCode",
    "DomainEvent", "EventStore", "AlreadyRegistered", "ExtensionRegistry",
]