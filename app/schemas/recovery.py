from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List, Dict, Any

class RecoveryCaseResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    domain: str
    case_type: str
    status: str
    amount: Optional[int] = None
    currency: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class RecoveryOutcomeResponse(BaseModel):
    id: UUID
    case_id: UUID
    tenant_id: UUID
    action_id: Optional[UUID] = None
    outcome_status: str
    recovered_amount: int
    currency: str
    recovered_at: Optional[str] = None
    provider_reference: Optional[str] = None
    time_to_recovery: Optional[float] = None
    recovery_source: str
    attribution_source: Optional[str] = None
    attribution_decision: Optional[str] = None
    attribution_provenance: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

class RecoveryMeasurementResponse(BaseModel):
    id: UUID
    outcome_id: UUID
    measurement_at: str
    estimated_control_recovery: Optional[int] = None
    treatment_recovery: int
    control_recovery: Optional[int] = 0
    incremental_recovery: int
    incremental_recovery_estimate: Optional[int] = None
    cost_of_recovery: Optional[int] = None
    attribution_window_seconds: int
    experiment_id: Optional[UUID] = None
    experiment_variant: Optional[str] = None
    baseline_policy_version: Optional[str] = None
    baseline_method: Optional[str] = "deterministic_heuristic"
    baseline_expected_recovery: Optional[int] = None
    is_counterfactual_estimate: bool = True
    provenance: Optional[str] = None

    class Config:
        from_attributes = True

class RecoveryMetricsResponse(BaseModel):
    total_incremental_recovery: int
    incremental_recovery_estimate: Optional[int] = None
    observed_treatment_recovery: Optional[int] = 0
    observed_control_recovery: Optional[int] = 0
    estimated_counterfactual_recovery: Optional[int] = 0
    baseline_method: Optional[str] = "deterministic_heuristic"
    is_estimate: bool = True
    label: str = "ESTIMATE"

class ExperimentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    status: str
    allocation_percentage: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
