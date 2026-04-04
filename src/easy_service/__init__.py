"""easy-service — cross-platform, no-admin service management."""

__all__ = [
    "__version__",
    "ServiceSpec",
    "ServiceStatus",
    "manager_for_platform",
]

__version__ = "0.1.0"

from easy_service.models import ServiceSpec, ServiceStatus
from easy_service.platforms import manager_for_platform

