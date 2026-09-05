import urllib.request
import json

CASE_ID = "c6fe67e6-d2ba-415c-a718-07ab996e8b8e"

# Test health
r = urllib.request.urlopen("http://localhost:8000/health")
health = json.load(r)
print("Health:", json.dumps(health))

# Test dashboard
import hmac, hashlib
account_id = "acc_demo_123"
api_key = "test_internal_key"
sig = hmac.new(api_key.encode(), account_id.encode(), hashlib.sha256).hexdigest()

req = urllib.request.Request(
    "http://localhost:8000/v1/recovery/dashboard",
    headers={"X-Account-ID": account_id, "X-Signature": sig}
)
r2 = urllib.request.urlopen(req)
d = json.load(r2)
print("Dashboard recent_activity count:", len(d.get("recent_activity", [])))
print("Dashboard recent_cases count:", len(d.get("recent_cases", [])))

# Test case detail  
req3 = urllib.request.Request(
    f"http://localhost:8000/v1/recovery/cases/{CASE_ID}/full",
    headers={"X-Account-ID": account_id, "X-Signature": sig}
)
try:
    r3 = urllib.request.urlopen(req3)
    d3 = json.load(r3)
    ex = d3.get("execution", {})
    c = d3.get("case", {})
    print("Case detail:")
    print("  case_status:", c.get("status"))
    print("  recovery_stage:", c.get("recovery_stage"))
    print("  payment_link_url:", ex.get("payment_link_url"))
    print("  provider_resource_id:", ex.get("provider_resource_id"))
    print("  action_type:", ex.get("action_type"))
    print("  action_status:", ex.get("status"))
    print("  outcome:", d3.get("recovery", {}).get("outcome_status"))
    print("  activities:", len(d3.get("activities", [])))
except Exception as e:
    print("Case detail error:", e)

# Test activity endpoint
req4 = urllib.request.Request(
    "http://localhost:8000/v1/recovery/activity?limit=5",
    headers={"X-Account-ID": account_id, "X-Signature": sig}
)
try:
    r4 = urllib.request.urlopen(req4)
    acts = json.load(r4)
    print("Activity count:", len(acts))
    if acts:
        print("Latest activity:", acts[0].get("event_type"), acts[0].get("human_readable_message", "")[:80])
except Exception as e:
    print("Activity error:", e)
