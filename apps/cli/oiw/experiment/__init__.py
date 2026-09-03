"""B2 — Experiment Engine: automate the METHOD itself."""

from .engine import (
    VERDICT_GREEN,
    VERDICT_RED,
    VERDICT_SKIPPED,
    ExperimentRecord,
    LawCandidate,
    Rung,
    derive_laws,
    execution_order,
    generate_ladder,
    materialize_variant,
)
from .registry import (
    LawRecord,
    LawRegistry,
    load_registry,
)
from .runner import (
    DEFAULT_COOLDOWN_S,
    ExperimentBudget,
    ExperimentRunner,
    load_record,
    save_record,
    verdict_from_calibration,
)

__all__ = [
    "DEFAULT_COOLDOWN_S",
    "ExperimentBudget",
    "ExperimentRecord",
    "ExperimentRunner",
    "LawCandidate",
    "LawRecord",
    "LawRegistry",
    "Rung",
    "VERDICT_GREEN",
    "VERDICT_RED",
    "VERDICT_SKIPPED",
    "derive_laws",
    "execution_order",
    "generate_ladder",
    "load_record",
    "load_registry",
    "materialize_variant",
    "save_record",
    "verdict_from_calibration",
]
