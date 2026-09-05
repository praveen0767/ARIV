import math
import pytest
from app.services.economic_optimizer import EconomicOptimizer

@pytest.mark.parametrize(
    "prob, amount, op_cost, risk, expected",
    [
        (0.0, 1000, 0, 0, 0.0),
        (1.0, 1000, 0, 0, 1000.0),
        (0.5, 2000, 100, 0, 0.5 * 2000 - 100),
        (0.8, 5000, 200, 300, 0.8 * 5000 - 200 - 300),
        (1.2, 1000, 0, 0, 1000.0),  # probability capped at 1
        (-0.5, 1000, 0, 0, 0.0),   # probability floored at 0
    ],
)
def test_compute_expected_net_recovery(prob, amount, op_cost, risk, expected):
    result = EconomicOptimizer.compute_expected_net_recovery(
        probability=prob,
        recoverable_amount=amount,
        operational_cost=op_cost,
        risk_penalty=risk,
    )
    assert math.isclose(result, expected, rel_tol=1e-9)
