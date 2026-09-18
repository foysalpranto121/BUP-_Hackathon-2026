import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
from schemas import EnergyScenario, OptimizeEnergyResponse

client = TestClient(app)

SAMPLE_CASES_PATH = Path(__file__).parent.parent / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def load_sample_cases():
    if not SAMPLE_CASES_PATH.exists():
        pytest.skip(f"Sample cases file not found at {SAMPLE_CASES_PATH}")
    with open(SAMPLE_CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


@pytest.mark.parametrize("case", load_sample_cases(), ids=lambda c: c["id"])
def test_sample_case_optimization(case):
    input_data = case["input"]
    expected_output = case["expected_output"]

    # Send POST request
    response = client.post("/optimize-energy", json=input_data)
    assert response.status_code == 200, f"Failed case {case['id']}: {response.text}"

    res_data = response.json()
    validated_res = OptimizeEnergyResponse(**res_data)

    # 1. Verify scenario_id echo
    assert validated_res.scenario_id == expected_output["scenario_id"]

    # 2. Verify directive_interpretation count and types
    expected_dirs = expected_output["directive_interpretation"]
    actual_dirs = validated_res.directive_interpretation

    assert len(actual_dirs) == len(expected_dirs)

    for actual, expected in zip(actual_dirs, expected_dirs):
        assert actual.note_index == expected["note_index"]
        assert actual.applies == expected["applies"]
        assert actual.directive_type == expected["directive_type"]

        if expected["directive_type"] == "no_op":
            assert actual.structured_adjustment is None
        else:
            assert actual.structured_adjustment is not None
            exp_adj = expected["structured_adjustment"]
            act_adj = actual.structured_adjustment
            if isinstance(act_adj, dict):
                act_hours = act_adj.get("hours", [])
            else:
                act_hours = getattr(act_adj, "hours", [])
            assert act_hours == exp_adj["hours"]

    # 3. Verify hourly plan constraints
    hourly_plan = validated_res.hourly_plan
    assert len(hourly_plan) == 24

    hours_input = input_data["hours"]
    battery_input = input_data["battery"]

    for h in range(24):
        plan_h = hourly_plan[h]
        in_h = hours_input[h]

        assert plan_h.hour == h

        # Determine battery charge/discharge magnitude
        c_kwh = plan_h.battery_kwh if plan_h.battery_action == "charge" else 0.0
        d_kwh = plan_h.battery_kwh if plan_h.battery_action == "discharge" else 0.0

        # Energy balance check: grid + solar_used + discharge = demand + charge
        left_side = plan_h.grid_kwh + plan_h.solar_used_kwh + d_kwh
        right_side = in_h["demand_kwh"] + c_kwh
        assert abs(left_side - right_side) < 0.01, f"Energy balance mismatch at hour {h}"

    # 4. End-of-day battery neutrality check
    assert abs(hourly_plan[23].battery_energy_after_kwh - battery_input["initial_energy_kwh"]) < 0.01

    # 5. Cost calculation verification
    recalculated_cost = sum(
        hourly_plan[h].grid_kwh * hours_input[h]["tariff_bdt_per_kwh"]
        for h in range(24)
    )
    assert abs(validated_res.total_cost_bdt - recalculated_cost) < 0.01
    assert validated_res.total_cost_bdt <= expected_output["total_cost_bdt"] + 0.1
