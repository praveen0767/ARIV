import hmac
import hashlib
import logging
from fastapi import Request, HTTPException
from app.core.config import settings

logger = logging.getLogger("ariv.security")

async def verify_razorpay_signature(request: Request) -> bytes:
    """
    Verifies Razorpay webhook signature and returns the raw body.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature")
    
    if not signature:
        logger.warning("Missing x-razorpay-signature header")
        raise HTTPException(status_code=400, detail="Missing signature")
    
    expected_signature = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature):
        logger.warning("Invalid x-razorpay-signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
        
    return raw_body
