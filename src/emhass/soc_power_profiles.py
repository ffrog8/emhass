"""SOC power-profile model-size accounting and benchmark-backed warnings.

This module converts validated profile shapes into the exact selector and
linear-row increase used by the optimizer. The retained benchmark envelope is
advisory: profiles above it remain valid and are still passed to CVXPY.
"""

from __future__ import annotations

import logging
from typing import Any

# Filled by the paired benchmark retained in benchmarks/soc_power_profiles.
# These are model-size boundaries, not battery-domain band-count limits or
# service-level memory/request protections.
BENCHMARK_MAX_SELECTORS = 1152
BENCHMARK_MAX_ADDED_ROWS = 2592


def model_size_increase(
    profiles: list[dict[str, Any]] | None, horizon: int
) -> dict[str, Any]:
    """Return exact added model structure for a validated profile list."""
    direction_presence: list[dict[str, bool]] = []
    band_counts: list[dict[str, int]] = []
    breakpoints = 0
    directions = 0

    for entry in profiles or []:
        present: dict[str, bool] = {}
        counts: dict[str, int] = {}
        for direction in ("charge", "discharge"):
            profile = entry.get(direction)
            present[direction] = profile is not None
            counts[direction] = len(profile["power_max"]) if profile is not None else 0
            if profile is not None:
                directions += 1
                breakpoints += len(profile["soc_breakpoints"])
        direction_presence.append(present)
        band_counts.append(counts)

    selectors = horizon * breakpoints
    added_rows = horizon * (2 * breakpoints + directions)
    return {
        "horizon": horizon,
        "battery_count": len(profiles or []),
        "direction_presence": direction_presence,
        "band_counts": band_counts,
        "breakpoint_count": breakpoints,
        "profile_direction_count": directions,
        "boolean_selectors": selectors,
        "added_linear_rows": added_rows,
    }


def log_model_size_increase(
    logger: logging.Logger,
    profiles: list[dict[str, Any]] | None,
    horizon: int,
) -> dict[str, Any]:
    """Log exact added structure and warn once above retained benchmark evidence."""
    model_size = model_size_increase(profiles, horizon)
    if model_size["profile_direction_count"] == 0:
        return model_size

    logger.info(
        "Battery SOC power profiles add %d Boolean selectors and %d linear rows "
        "for %d intervals.",
        model_size["boolean_selectors"],
        model_size["added_linear_rows"],
        horizon,
    )
    if (
        model_size["boolean_selectors"] > BENCHMARK_MAX_SELECTORS
        or model_size["added_linear_rows"] > BENCHMARK_MAX_ADDED_ROWS
    ):
        logger.warning(
            "Battery SOC power-profile model size (%d selectors, %d rows) exceeds "
            "the largest paired benchmark (%d selectors, %d rows). The profile "
            "remains accepted; benchmark this shape or simplify it before control "
            "use. This warning is not a memory or request-safety guarantee.",
            model_size["boolean_selectors"],
            model_size["added_linear_rows"],
            BENCHMARK_MAX_SELECTORS,
            BENCHMARK_MAX_ADDED_ROWS,
        )
    return model_size
