import urllib.request
import json

CASE_ID = "c6fe67e6-d2ba-415c-a718-07ab996e8b8e"
url = f"http://localhost:8000/v1/dashboard/case/{CASE_ID}"
req = urllib.request.Request(url, headers={"x-internal-key": "test_internal_key"})
try:
    r = urllib.request.urlopen(req)
    d = json.load(r)
    ex = d.get("execution", {})
    c = d.get("case", {})
    out = {
        "case_status": c.get("status"),
        "recovery_stage": c.get("recovery_stage"),
        "payment_link_url": ex.get("payment_link_url"),
        "provider_resource_id": ex.get("provider_resource_id"),
        "provider_reference": ex.get("provider_reference"),
        "action_type": ex.get("action_type"),
        "outcome": d.get("recovery", {}).get("outcome_status"),
        "activities_count": len(d.get("activities", [])),
    }
    print(json.dumps(out, indent=2))
except Exception as e:
    print(f"ERROR: {e}")
