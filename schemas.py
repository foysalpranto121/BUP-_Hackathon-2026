from typing import List, Optional, Literal, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# Allowed Enums & Types
DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]

BatteryAction = Literal["charge", "discharge", "idle"]


# --- Request Schemas ---

class HourEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    demand_kwh: float = Field(..., ge=0, description="Campus energy demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Base solar generation available in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid electricity price in BDT per kWh")


class BatteryConfig(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Maximum energy battery can store")
    initial_energy_kwh: float = Field(..., ge=0, description="Energy in battery at start of hour 0")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base minimum reserve level")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Max energy added in 1 hour")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Max energy removed in 1 hour")

    @model_validator(mode="after")
    def validate_battery_levels(self):
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        return self


class EnergyScenario(BaseModel):
    scenario_id: str = Field(..., description="Unique scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1-3 natural language notes")
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24, description="Exactly 24 hourly entries")
    battery: BatteryConfig

    @field_validator("hours")
    @classmethod
    def validate_hours_sequence(cls, v: List[HourEntry]) -> List[HourEntry]:
        if len(v) != 24:
            raise ValueError("hours array must contain exactly 24 entries")
        hours_seen = [h.hour for h in v]
        if sorted(hours_seen) != list(range(24)):
            raise ValueError("hours must contain exactly unique integers from 0 through 23")
        return v


# --- Structured Adjustment Shapes ---

class SolarReductionAdjustment(BaseModel):
    hours: List[int]
    factor: float = Field(..., ge=0.0, le=1.0)


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int]
    minimum_energy_kwh: float = Field(..., ge=0.0)


class NoChargeWindowAdjustment(BaseModel):
    hours: List[int]


class NoDischargeWindowAdjustment(BaseModel):
    hours: List[int]


class MaxGridWindowAdjustment(BaseModel):
    hours: List[int]
    max_grid_kwh: float = Field(..., ge=0.0)


# --- Response Schemas ---

class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Zero-based index matching operator_notes")
    applies: bool = Field(..., description="true for active directives, false for no_op")
    directive_type: DirectiveType
    structured_adjustment: Optional[Union[
        SolarReductionAdjustment,
        MinimumBatteryReserveAdjustment,
        NoChargeWindowAdjustment,
        NoDischargeWindowAdjustment,
        MaxGridWindowAdjustment,
        Dict[str, Any]
    ]] = Field(default=None, description="Exact machine-checkable object or null for no_op")
    explanation: str = Field(..., description="Short explanation of the interpretation")


class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0.0)
    solar_used_kwh: float = Field(..., ge=0.0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0.0)
    battery_energy_after_kwh: float = Field(..., ge=0.0)


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str


# --- Health Response ---

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
