"""
End-to-End Integration and Real-World Application Scenario Tests.

Conforms to PROJECT.md Code Layout and Tier 3 / Tier 4 specifications.
"""

from tests.test_tier3_combinations import (
    TestMultiFailureDiagnosticAggregation,
    TestPostCheckFaultInjectionAndDiagnostics,
    TestStep06LifecycleIntegration,
)
from tests.test_tier4_scenarios import (
    TestAerospaceAssemblyNominalWorkflow,
    TestEngineeringChangeOrderTroubleshootingAndRecovery,
)

__all__ = [
    "TestAerospaceAssemblyNominalWorkflow",
    "TestEngineeringChangeOrderTroubleshootingAndRecovery",
    "TestMultiFailureDiagnosticAggregation",
    "TestPostCheckFaultInjectionAndDiagnostics",
    "TestStep06LifecycleIntegration",
]
