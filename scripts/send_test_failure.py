import os, hmac, hashlib, json, sys, importlib, uuid

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root in sys.path:
    sys.path.remove(project_root)
httpx = importlib.import_module('httpx')

# Resolve webhook secret: check environment variable first, then .env file
secret = os.getenv('RAZORPAY_WEBHOOK_SECRET')
if not secret or secret == 'test_secret':
    for candidate in [os.path.join(project_root, ".env"), "/app/.env", ".env"]:
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("RAZORPAY_WEBHOOK_SECRET="):
                            parsed = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if parsed:
                                secret = parsed
                                break
            except Exception:
                pass
        if secret and secret != 'test_secret':
            break

if not secret:
    secret = 'test_secret'

event_uid = uuid.uuid4().hex[:8]
event_id = f"ev_test_failure_{event_uid}"
payment_id = f"pay_test_{event_uid}"

payload = {
    "event": "payment.failed",
    "account_id": "sandbox_account",
    "payload": {
        "payment": {
            "entity": {
                "id": payment_id,
                "amount": 10000,
                "currency": "INR",
                "email": "customer@example.com",
                "contact": "9876543210",
                "error_code": "BAD_REQUEST_ERROR",
                "error_reason": "Insufficient balance",
                "notes": {"case_id": "", "action_id": ""}
            }
        }
    }
}

payload_bytes = json.dumps(payload).encode('utf-8')
signature = hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()

headers = {
    "Content-Type": "application/json",
    "x-razorpay-signature": signature,
    "x-razorpay-event-id": event_id,
}

url = "http://localhost:8000/webhooks/razorpay"
resp = httpx.post(url, content=payload_bytes, headers=headers, timeout=10)
print(f"Sent event_id={event_id}, payment_id={payment_id}")
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")

