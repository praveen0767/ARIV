"""
app/infrastructure/adapters/__init__.py
"""

from typing import Optional
from app.infrastructure.adapters.razorpay import (
    RazorpayConfig,
    RazorpaySandboxAdapter,
)

def get_razorpay_adapter() -> Optional[RazorpaySandboxAdapter]:
    """Helper to construct a configured Razorpay sandbox adapter from current settings."""
    from app.core.config import settings
    from app.domain.provider import ProviderEnvironment

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return None
    try:
        config = RazorpayConfig(
            key_id=settings.RAZORPAY_KEY_ID,
            key_secret=settings.RAZORPAY_KEY_SECRET,
            base_url=settings.RAZORPAY_BASE_URL,
            environment=ProviderEnvironment.SANDBOX,
        )
        return RazorpaySandboxAdapter(config)
    except Exception:
        return None

__all__ = [
    "RazorpayConfig",
    "RazorpaySandboxAdapter",
    "get_razorpay_adapter",
]
