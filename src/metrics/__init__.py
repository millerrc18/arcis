"""Server-side metric registry package — single source for console metrics."""
from src.metrics.registry import (
    REGISTRY,
    MetricDef,
    compute_all,
    compute_metric,
    register,
)

__all__ = [
    "REGISTRY",
    "MetricDef",
    "compute_all",
    "compute_metric",
    "register",
]
