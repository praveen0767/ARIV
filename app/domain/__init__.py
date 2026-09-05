from app.domain.base import Base
# Optional import of Tenant for environments without SQLAlchemy
try:
    from app.domain.tenant import Tenant
except Exception as e:
    import logging
    logging.getLogger("ariv.domain").warning("Tenant import failed (%s); proceeding without Tenant model.", e)
    Tenant = None
from app.domain.recovery_case import RecoveryDomain, RecoveryCase
from app.domain.events import ProviderEvent, RiskEvent, AuditEvent
from app.domain.classification import RecoveryClassification
from app.domain.decision import DecisionRecord, RecoveryAction, AutonomyLevel, PolicyStatus
from app.domain.system_settings import SystemSetting
from app.domain.action import (
    Action,
    ActionStatus,
    ExecutionAttempt,
    ExecutionStatus,
    ExecutionOutbox,
    OutboxStatus,
)
from app.domain.recovery.recovery_outcome import RecoveryOutcome, RecoveryOutcomeStatus, RecoverySource
from app.domain.recovery.recovery_measurement import RecoveryMeasurement
from app.domain.recovery.experiment import Experiment, ExperimentStatus
from app.domain.recovery.baseline_decision import BaselineDecision
