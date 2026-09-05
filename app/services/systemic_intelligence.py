"""
app/services/systemic_intelligence.py

Systemic / Route-Level Payment Failure Intelligence for ARIV.
Detects route-level failure clusters and degradation across payment corridors
(provider + payment method + domain/corridor) using rolling windows.

Provides:
1. Real-time corridor degradation scoring
2. Route status: OPERATIONAL | DEGRADED | CRITICAL
3. Context injection into AgentRuntime & PolicyEngine
4. Operator visibility into systemic failure spikes
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from uuid import UUID

from app.domain.recovery_case import RecoveryCase, RecoveryDomain
from app.domain.classification import FailureCategory

logger = logging.getLogger("ariv.services.systemic")


class SystemicIntelligenceService:
    """Service detecting route degradation and failure clusters."""

    BASELINE_FAILURE_RATE = 0.08  # 8% baseline failure rate across corridors
    ROLLING_WINDOW_MINUTES = 60

    # In-memory sliding window buffer for high-performance correlation: (timestamp, tenant_id, corridor, category, amount, is_failure)
    _event_buffer: List[Dict[str, Any]] = []

    @classmethod
    def detect_corridor(cls, case: RecoveryCase) -> str:
        """Extract canonical payment corridor from RecoveryCase."""
        provider = getattr(case, "provider", None) or "razorpay"
        context = getattr(case, "context", {}) or {}
        method = context.get("method") or "card"
        domain = getattr(case, "domain", None)
        domain_str = domain.value.lower() if hasattr(domain, "value") else str(domain or "b2c").lower()
        return f"{provider.lower()}:{method.lower()}:{domain_str}"

    @classmethod
    def record_signal(
        cls,
        corridor: str,
        tenant_id: str,
        is_failure: bool = True,
        category: Optional[str] = None,
        amount: float = 0.0,
        timestamp: Optional[datetime] = None,
    ):
        """Record an observed payment outcome signal into the systemic buffer."""
        ts = timestamp or datetime.now(timezone.utc)
        cls._event_buffer.append({
            "timestamp": ts,
            "tenant_id": str(tenant_id),
            "corridor": corridor,
            "category": category or "UNKNOWN",
            "amount": amount,
            "is_failure": is_failure,
        })
        # Evict signals older than rolling window * 2
        cutoff = ts - timedelta(minutes=cls.ROLLING_WINDOW_MINUTES * 2)
        cls._event_buffer = [e for e in cls._event_buffer if e["timestamp"] >= cutoff]

    @classmethod
    def analyze_route_health(
        cls,
        corridor: str,
        tenant_id: Optional[str] = None,
        lookback_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Calculate deterministic route health score and degradation status."""
        window = lookback_minutes or cls.ROLLING_WINDOW_MINUTES
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=window)

        # Filter events in window
        matching = [
            e for e in cls._event_buffer
            if e["corridor"] == corridor
            and e["timestamp"] >= cutoff
            and (tenant_id is None or e["tenant_id"] == str(tenant_id))
        ]

        sample_count = len(matching)
        failures = [e for e in matching if e["is_failure"]]
        failure_count = len(failures)
        amount_at_risk = sum(e.get("amount", 0.0) for e in failures)

        if sample_count == 0:
            failure_rate = 0.0
            degradation_score = 0.0
            status = "OPERATIONAL"
            mitigation = "Corridor is operating normally with zero recent failure signals."
        else:
            failure_rate = round(failure_count / sample_count, 4)
            degradation_score = round(failure_rate / cls.BASELINE_FAILURE_RATE, 2)

            if sample_count >= 5 and (failure_rate >= 0.60 or degradation_score >= 4.0):
                status = "CRITICAL"
                mitigation = "Critical systemic failure spike: suppress automated immediate retries; route to payment links or escalate."
            elif sample_count >= 3 and (failure_rate >= 0.30 or degradation_score >= 2.0):
                status = "DEGRADED"
                mitigation = "Corridor degraded: avoid aggressive immediate retries; prefer delayed retry or customer payment link."
            else:
                status = "OPERATIONAL"
                mitigation = "Corridor within expected baseline failure thresholds."

        summary = (
            f"Corridor '{corridor}': {status} "
            f"({failure_count}/{sample_count} failures in {window}m, "
            f"failure rate: {failure_rate*100:.1f}%, {degradation_score}x baseline)"
        )

        return {
            "corridor": corridor,
            "status": status,
            "sample_count": sample_count,
            "failure_count": failure_count,
            "failure_rate": failure_rate,
            "baseline_rate": cls.BASELINE_FAILURE_RATE,
            "degradation_score": degradation_score,
            "amount_at_risk_inr": round(amount_at_risk, 2),
            "recommended_mitigation": mitigation,
            "summary": summary,
            "lookback_minutes": window,
            "timestamp": now.isoformat(),
        }

    @classmethod
    def get_all_corridors(cls, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return health evaluation for all observed corridors."""
        corridors = set(e["corridor"] for e in cls._event_buffer)
        if not corridors:
            # Provide standard baseline corridors for operator visibility
            corridors = {"razorpay:card:b2c", "razorpay:upi:b2c", "razorpay:netbanking:b2b"}

        results = []
        for c in sorted(corridors):
            results.append(cls.analyze_route_health(corridor=c, tenant_id=tenant_id))
        return results

    @classmethod
    def clear_buffer(cls):
        """Reset buffer (used for test isolation)."""
        cls._event_buffer.clear()
