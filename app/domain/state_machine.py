import logging
from app.domain.recovery_case import RecoveryCase, CaseStatus

logger = logging.getLogger("ariv.domain.state_machine")

class StateTransitionError(Exception):
    pass

class CaseStateMachine:
    
    ALLOWED_TRANSITIONS = {
        CaseStatus.OPEN: [CaseStatus.RISK_ASSESSED, CaseStatus.RECOVERED, CaseStatus.CLOSED],
        CaseStatus.RISK_ASSESSED: [CaseStatus.PENDING_APPROVAL, CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED],
        CaseStatus.PENDING_APPROVAL: [CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.CLOSED],
        # Terminal states
        CaseStatus.RECOVERED: [],
        CaseStatus.FAILED: [],
        CaseStatus.CLOSED: []
    }

    @classmethod
    def transition_to(cls, case: RecoveryCase, new_status: CaseStatus, expected_version: int = None):
        """
        Safely transition a case to a new status.
        Enforces optimistic locking and allowed transitions.
        """
        if expected_version is not None and case.version != expected_version:
            raise StateTransitionError(
                f"Version mismatch for case {case.id}. Expected {expected_version}, got {case.version}."
            )
            
        if new_status not in cls.ALLOWED_TRANSITIONS[case.status]:
            if case.status in (CaseStatus.RECOVERED, CaseStatus.CLOSED) and new_status == CaseStatus.FAILED:
                # Late failure arriving after success -> Reject silently
                logger.warning(f"Ignoring late failure for case {case.id} which is already {case.status.value}")
                raise StateTransitionError("Cannot regress from terminal success state to failure.")
            raise StateTransitionError(f"Invalid transition from {case.status.value} to {new_status.value}")

        logger.info(f"Transitioning case {case.id} from {case.status.value} to {new_status.value}")
        case.status = new_status
        case.version += 1
