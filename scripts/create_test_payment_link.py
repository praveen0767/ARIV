#!/usr/bin/env python3
"""
scripts/create_test_payment_link.py

ARIV LOCAL DEMO — create a fresh Razorpay Test-Mode payment link using the
credentials already configured in the repository .env file.

No manual credential entry is required. RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET
are loaded from the existing ARIV configuration (.env) and used internally by
the existing Razorpay adapter (Basic Auth inside the provider call). The secret
is never printed.

Usage:
    python scripts/create_test_payment_link.py --amount 10000
    python scripts/create_test_payment_link.py --amount 100 --expire-hours 6

Exit code is 0 on success and non-zero on failure.
"""

import argparse
import asyncio
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_settings():
    from app.core.config import Settings

    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        return Settings(_env_file=str(env_file))
    return Settings()


def format_rupees(paise: int) -> str:
    rupees = Decimal(paise) / Decimal(100)
    if rupees == rupees.to_integral_value():
        return f"\u20b9{int(rupees)}"
    return f"\u20b9{rupees.quantize(Decimal('0.01'))}"


def parse_amount(value: str) -> int:
    try:
        rupees = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid amount: {value!r} (must be a positive number in rupees)")
    if not rupees.is_finite() or rupees <= 0:
        raise argparse.ArgumentTypeError(f"invalid amount: {value!r} (must be a positive number in rupees)")
    scaled = rupees * Decimal(100)
    if scaled != scaled.to_integral_value():
        raise argparse.ArgumentTypeError(f"invalid amount: {value!r} (must have at most two decimal places)")
    paise = int(scaled)
    if paise < 100:
        raise argparse.ArgumentTypeError("minimum amount is \u20b91 (100 paise)")
    return paise


def parse_expire_hours(value: str) -> int:
    try:
        hours = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid expire-hours: {value!r} (must be a positive whole number)")
    if hours <= 0:
        raise argparse.ArgumentTypeError(f"invalid expire-hours: {value!r} (must be a positive whole number)")
    return hours


async def create_link(amount_minor: int, description: str, expire_hours) -> int:
    from app.domain.provider import (
        CreatePaymentLinkRequest,
        ProviderEnvironment,
        ProviderOutcomeStatus,
    )
    from app.infrastructure.adapters.razorpay import RazorpayConfig, RazorpaySandboxAdapter

    settings = load_settings()

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        print(
            f"ERROR: Razorpay credentials are not configured for the ARIV local demo.",
            file=sys.stderr,
        )
        print(
            "       Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in the repository .env file.",
            file=sys.stderr,
        )
        return 1

    try:
        config = RazorpayConfig(
            key_id=settings.RAZORPAY_KEY_ID,
            key_secret=settings.RAZORPAY_KEY_SECRET,
            base_url=settings.RAZORPAY_BASE_URL,
            environment=ProviderEnvironment.SANDBOX,
        )
    except Exception as exc:
        print(f"ERROR: invalid Razorpay configuration: {exc}", file=sys.stderr)
        return 1

    adapter = RazorpaySandboxAdapter(config)

    expire_by = None
    if expire_hours:
        expire_by = int(time.time()) + expire_hours * 3600

    request = CreatePaymentLinkRequest(
        amount=amount_minor,
        currency="INR",
        description=description,
        idempotency_key=f"ariv:cli:{uuid.uuid4().hex}",
        notes={"source": "ariv-local-demo", "tool": "create_test_payment_link"},
        expire_by=expire_by,
    )

    print("Creating Razorpay Test-Mode payment link...")
    result = await adapter.create_payment_link(request)

    if result.status == ProviderOutcomeStatus.SUCCEEDED:
        short_url = (result.raw_metadata or {}).get("short_url")
        print(f"Amount: {format_rupees(amount_minor)}")
        print(f"Payment Link: {short_url or 'N/A'}")
        print(f"Payment Link ID: {result.provider_resource_id or 'N/A'}")
        return 0

    print(f"ERROR: Razorpay could not create the payment link.", file=sys.stderr)
    if result.error_code:
        print(f"Error: {result.error_code}", file=sys.stderr)
    if result.error_reason:
        print(f"Reason: {result.error_reason}", file=sys.stderr)
    if result.status == ProviderOutcomeStatus.UNKNOWN:
        print(
            "The provider state is unknown. Do not retry blindly; use a new run "
            "(new idempotency key is generated automatically).",
            file=sys.stderr,
        )
    return 1


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        prog="create_test_payment_link",
        description="Create a fresh Razorpay Test-Mode payment link using the credentials in .env.",
    )
    parser.add_argument(
        "--amount",
        type=parse_amount,
        required=True,
        help="Amount in rupees (e.g. 100 = \u20b9100).",
    )
    parser.add_argument(
        "--description",
        default="ARIV Test Recovery",
        help="Payment link description (default: 'ARIV Test Recovery').",
    )
    parser.add_argument(
        "--expire-hours",
        type=parse_expire_hours,
        default=None,
        help="Optional link expiry in hours from now.",
    )
    args = parser.parse_args()

    return asyncio.run(create_link(args.amount, args.description, args.expire_hours))


if __name__ == "__main__":
    sys.exit(main())