"""
Unit Tests for Step 6 Material Mapping.

Conforms to PROJECT.md Code Layout and Tier 1 / Tier 2 specifications.
"""

from tests.test_tier1_features import TestStep06MaterialMappingFeatureCoverage
from tests.test_tier2_boundaries import (
    TestSurfaceBodyMissingThicknessBoundaries,
    TestToleranceThresholdBoundaries,
    TestUnmappedBodiesBoundaries,
)

__all__ = [
    "TestStep06MaterialMappingFeatureCoverage",
    "TestSurfaceBodyMissingThicknessBoundaries",
    "TestToleranceThresholdBoundaries",
    "TestUnmappedBodiesBoundaries",
]
