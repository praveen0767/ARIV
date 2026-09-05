import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.events import RiskEvent
from app.domain.classification import RecoveryClassification, FailureCategory, Retryability, Recoverability

logger = logging.getLogger("ariv.services.classification")

class ClassificationService:
    TAXONOMY_VERSION = "1.0"

    @classmethod
    async def classify(cls, session: AsyncSession, risk_event: RiskEvent) -> RecoveryClassification:
        """
        Deterministically classifies a RiskEvent into a RecoveryClassification.
        """
        payload = risk_event.canonical_payload
        
        # Razorpay specific mapping for Phase 2
        error_code = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("error_code", "UNKNOWN")
        error_reason = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("error_reason", "UNKNOWN")
        
        category = FailureCategory.UNKNOWN
        retryability = Retryability.BLOCKED
        recoverability = Recoverability.UNKNOWN

        # Deterministic Rules Engine
        if error_code in ("BAD_REQUEST_ERROR", "GATEWAY_ERROR"):
            reason_lower = error_reason.lower()
            if "timeout" in reason_lower or "declined by bank" in reason_lower:
                category = FailureCategory.TRANSIENT_TECHNICAL
                retryability = Retryability.IMMEDIATE_RETRY_POSSIBLE
                recoverability = Recoverability.HIGH
            elif "expired" in reason_lower:
                category = FailureCategory.NON_RETRIABLE
                retryability = Retryability.BLOCKED
                recoverability = Recoverability.LOW
            elif "authentication" in reason_lower:
                # Authentication failed → customer must re-authenticate or use new method
                category = FailureCategory.CUSTOMER_ACTION_REQUIRED
                retryability = Retryability.REQUIRES_NEW_METHOD
                recoverability = Recoverability.HIGH
            elif "insufficient" in reason_lower or "balance" in reason_lower:
                # Insufficient balance → customer must fund account or use new method
                category = FailureCategory.CUSTOMER_ACTION_REQUIRED
                retryability = Retryability.REQUIRES_NEW_METHOD
                recoverability = Recoverability.MEDIUM
            else:
                category = FailureCategory.UNKNOWN
                retryability = Retryability.LATER_RETRY_POSSIBLE
                recoverability = Recoverability.LOW

        elif "authentication_failed" in error_code.lower() or "authentication failed" in error_reason.lower():
            category = FailureCategory.CUSTOMER_ACTION_REQUIRED
            retryability = Retryability.REQUIRES_NEW_METHOD
            recoverability = Recoverability.HIGH

        elif error_code == "NON_RETRIABLE" or "expired" in error_reason.lower():
            category = FailureCategory.NON_RETRIABLE
            retryability = Retryability.BLOCKED
            recoverability = Recoverability.LOW

        classification = RecoveryClassification(
            case_id=risk_event.case_id,
            failure_category=category,
            retryability=retryability,
            recoverability=recoverability,
            taxonomy_version=cls.TAXONOMY_VERSION
        )
        
        session.add(classification)
        await session.flush()
        
        logger.info(f"Classified Case {risk_event.case_id}: {category.value} - {retryability.value}")
        return classification
