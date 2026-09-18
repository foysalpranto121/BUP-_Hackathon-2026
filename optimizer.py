import logging
from typing import List, Dict, Tuple, Any
from schemas import EnergyScenario, DirectiveInterpretation, HourlyPlanEntry, OptimizeEnergyResponse

logger = logging.getLogger("optimizer")

def solve_energy_optimization(
    scenario: EnergyScenario,
    directives: List[DirectiveInterpretation]
) -> OptimizeEnergyResponse:
    """
    Formulates and solves the 24-hour campus energy schedule as a Linear Program (LP).
    Returns the validated response object containing directive interpretations, hourly plan,
    total grid kWh, total cost BDT, peak grid kWh, and plan summary.
    """
    hours = scenario.hours
    battery = scenario.battery
    num_hours = 24

    # 1. Pre-process directive effects per hour
    effective_solar = [h.solar_kwh for h in hours]
    active_reserve = [battery.minimum_energy_kwh for _ in range(num_hours)]
    max_charge = [battery.max_charge_kwh_per_hour for _ in range(num_hours)]
    max_discharge = [battery.max_discharge_kwh_per_hour for _ in range(num_hours)]
    max_grid = [float('inf') for _ in range(num_hours)]

    for d in directives:
        if not d.applies or not d.structured_adjustment:
            continue
        
        dtype = d.directive_type
        adj = d.structured_adjustment
        
        # Helper to get hours list regardless of schema model or dict
        h_list = adj.get("hours", []) if isinstance(adj, dict) else getattr(adj, "hours", [])
        
        if dtype == "solar_reduction":
            factor = adj.get("factor", 1.0) if isinstance(adj, dict) else getattr(adj, "factor", 1.0)
            for h in h_list:
                if 0 <= h < num_hours:
                    effective_solar[h] = hours[h].solar_kwh * factor

        elif dtype == "minimum_battery_reserve":
            req_reserve = adj.get("minimum_energy_kwh", 0.0) if isinstance(adj, dict) else getattr(adj, "minimum_energy_kwh", 0.0)
            for h in h_list:
                if 0 <= h < num_hours:
                    active_reserve[h] = max(active_reserve[h], req_reserve)

        elif dtype == "no_charge_window":
            for h in h_list:
                if 0 <= h < num_hours:
                    max_charge[h] = 0.0

        elif dtype == "no_discharge_window":
            for h in h_list:
                if 0 <= h < num_hours:
                    max_discharge[h] = 0.0

        elif dtype == "max_grid_window":
            grid_cap = adj.get("max_grid_kwh", float('inf')) if isinstance(adj, dict) else getattr(adj, "max_grid_kwh", float('inf'))
            for h in h_list:
                if 0 <= h < num_hours:
                    max_grid[h] = min(max_grid[h], grid_cap)

    # 2. Try solving using PuLP (Linear Programming)
    try:
        import pulp
        
        prob = pulp.LpProblem("Campus_Energy_Optimization", pulp.LpMinimize)
        
        grid_vars = [pulp.LpVariable(f"grid_{h}", lowBound=0, upBound=max_grid[h] if max_grid[h] != float('inf') else None) for h in range(num_hours)]
        solar_vars = [pulp.LpVariable(f"solar_{h}", lowBound=0, upBound=effective_solar[h]) for h in range(num_hours)]
        charge_vars = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=max_charge[h]) for h in range(num_hours)]
        discharge_vars = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=max_discharge[h]) for h in range(num_hours)]
        soc_vars = [pulp.LpVariable(f"soc_{h}", lowBound=active_reserve[h], upBound=battery.capacity_kwh) for h in range(num_hours)]
        
        # Objective: minimize total cost
        prob += pulp.lpSum([grid_vars[h] * hours[h].tariff_bdt_per_kwh for h in range(num_hours)])
        
        # Constraints per hour
        for h in range(num_hours):
            # Energy balance: grid + solar_used + discharge = demand + charge
            prob += (grid_vars[h] + solar_vars[h] + discharge_vars[h] == hours[h].demand_kwh + charge_vars[h], f"balance_{h}")
            
            # SOC continuity
            if h == 0:
                prob += (soc_vars[0] == battery.initial_energy_kwh + charge_vars[0] - discharge_vars[0], f"soc_cont_{h}")
            else:
                prob += (soc_vars[h] == soc_vars[h-1] + charge_vars[h] - discharge_vars[h], f"soc_cont_{h}")
                
        # End of day neutrality: SOC[23] == initial_energy_kwh
        prob += (soc_vars[23] == battery.initial_energy_kwh, "end_of_day_neutrality")
        
        solver = pulp.PULP_CBC_CMD(msg=False)
        status = prob.solve(solver)
        
        if pulp.LpStatus[status] == "Optimal":
            plan_entries: List[HourlyPlanEntry] = []
            for h in range(num_hours):
                g_val = round(float(pulp.value(grid_vars[h])), 4)
                s_val = round(float(pulp.value(solar_vars[h])), 4)
                c_val = round(float(pulp.value(charge_vars[h])), 4)
                d_val = round(float(pulp.value(discharge_vars[h])), 4)
                soc_val = round(float(pulp.value(soc_vars[h])), 4)
                
                action = "idle"
                b_kwh = 0.0
                if c_val > 1e-4:
                    action = "charge"
                    b_kwh = c_val
                elif d_val > 1e-4:
                    action = "discharge"
                    b_kwh = d_val
                
                plan_entries.append(HourlyPlanEntry(
                    hour=h,
                    grid_kwh=g_val,
                    solar_used_kwh=s_val,
                    battery_action=action, # type: ignore
                    battery_kwh=b_kwh,
                    battery_energy_after_kwh=soc_val
                ))
            
            return assemble_response(scenario, directives, plan_entries, hours)

    except Exception as e:
        logger.warning(f"PuLP optimization failed or not available: {e}. Trying SciPy linprog fallback.")

    # 3. Fallback: SciPy linprog
    return solve_scipy_fallback(scenario, directives, effective_solar, active_reserve, max_charge, max_discharge, max_grid)


def solve_scipy_fallback(
    scenario: EnergyScenario,
    directives: List[DirectiveInterpretation],
    effective_solar: List[float],
    active_reserve: List[float],
    max_charge: List[float],
    max_discharge: List[float],
    max_grid: List[float]
) -> OptimizeEnergyResponse:
    """SciPy linprog implementation for Linear Programming optimization."""
    from scipy.optimize import linprog
    import numpy as np

    hours = scenario.hours
    battery = scenario.battery
    num_hours = 24

    # Variables order for each hour h (5 variables per hour, total 120 variables):
    # 0: grid[h], 1: solar[h], 2: charge[h], 3: discharge[h], 4: soc[h]
    n_vars = num_hours * 5

    c = np.zeros(n_vars)
    bounds = []

    for h in range(num_hours):
        idx = h * 5
        c[idx] = hours[h].tariff_bdt_per_kwh  # grid cost
        
        g_max = max_grid[h] if max_grid[h] != float('inf') else None
        bounds.append((0, g_max))                           # grid
        bounds.append((0, effective_solar[h]))              # solar
        bounds.append((0, max_charge[h]))                   # charge
        bounds.append((0, max_discharge[h]))                # discharge
        bounds.append((active_reserve[h], battery.capacity_kwh)) # soc

    # Equality constraints (A_eq * x = b_eq)
    # 1. Balance per hour (24 equations): grid + solar + discharge - charge = demand
    # 2. SOC continuity per hour (24 equations):
    #    h=0: soc[0] - charge[0] + discharge[0] = initial
    #    h>0: soc[h] - soc[h-1] - charge[h] + discharge[h] = 0
    # 3. End-of-day neutrality (1 equation): soc[23] = initial

    A_eq = []
    b_eq = []

    for h in range(num_hours):
        idx = h * 5
        # Balance equation
        row_b = np.zeros(n_vars)
        row_b[idx + 0] = 1.0   # grid
        row_b[idx + 1] = 1.0   # solar
        row_b[idx + 3] = 1.0   # discharge
        row_b[idx + 2] = -1.0  # charge
        A_eq.append(row_b)
        b_eq.append(hours[h].demand_kwh)

        # SOC continuity
        row_s = np.zeros(n_vars)
        row_s[idx + 4] = 1.0   # soc[h]
        row_s[idx + 2] = -1.0  # charge[h]
        row_s[idx + 3] = 1.0   # discharge[h]
        if h > 0:
            row_s[(h-1)*5 + 4] = -1.0 # -soc[h-1]
            b_eq.append(0.0)
        else:
            b_eq.append(battery.initial_energy_kwh)
        A_eq.append(row_s)

    # End of day neutrality
    row_e = np.zeros(n_vars)
    row_e[23*5 + 4] = 1.0
    A_eq.append(row_e)
    b_eq.append(battery.initial_energy_kwh)

    res = linprog(c, A_eq=np.array(A_eq), b_eq=np.array(b_eq), bounds=bounds, method='highs')

    if not res.success:
        raise RuntimeError(f"Optimization failed: {res.message}")

    x = res.x
    plan_entries: List[HourlyPlanEntry] = []
    for h in range(num_hours):
        idx = h * 5
        g_val = round(float(x[idx + 0]), 4)
        s_val = round(float(x[idx + 1]), 4)
        c_val = round(float(x[idx + 2]), 4)
        d_val = round(float(x[idx + 3]), 4)
        soc_val = round(float(x[idx + 4]), 4)

        action = "idle"
        b_kwh = 0.0
        if c_val > 1e-4:
            action = "charge"
            b_kwh = c_val
        elif d_val > 1e-4:
            action = "discharge"
            b_kwh = d_val

        plan_entries.append(HourlyPlanEntry(
            hour=h,
            grid_kwh=g_val,
            solar_used_kwh=s_val,
            battery_action=action, # type: ignore
            battery_kwh=b_kwh,
            battery_energy_after_kwh=soc_val
        ))

    return assemble_response(scenario, directives, plan_entries, hours)


def assemble_response(
    scenario: EnergyScenario,
    directives: List[DirectiveInterpretation],
    hourly_plan: List[HourlyPlanEntry],
    hours: List[Any]
) -> OptimizeEnergyResponse:
    """Recalculates totals and constructs the canonical response object."""
    total_grid_kwh = sum(entry.grid_kwh for entry in hourly_plan)
    total_cost_bdt = sum(entry.grid_kwh * hours[entry.hour].tariff_bdt_per_kwh for entry in hourly_plan)
    peak_grid_kwh = max(entry.grid_kwh for entry in hourly_plan)

    active_count = sum(1 for d in directives if d.applies)
    summary = (
        f"Optimized 24-hour campus energy schedule. Applied {active_count} active operator directive(s). "
        f"Achieved minimum grid cost of {total_cost_bdt:.2f} BDT with peak grid import of {peak_grid_kwh:.2f} kWh."
    )

    return OptimizeEnergyResponse(
        scenario_id=scenario.scenario_id,
        directive_interpretation=directives,
        hourly_plan=hourly_plan,
        total_grid_kwh=round(total_grid_kwh, 4),
        total_cost_bdt=round(total_cost_bdt, 4),
        peak_grid_kwh=round(peak_grid_kwh, 4),
        plan_summary=summary
    )
