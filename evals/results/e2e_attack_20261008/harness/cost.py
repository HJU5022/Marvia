import json, os, sys, httpx, datetime
env = {}
for l in open("/Users/jeong-un/Documents/Projects/Main_2_projects/proj2-5/.env"):
    if "=" in l and not l.startswith("#"):
        k, v = l.rstrip("\n").split("=", 1); env[k] = v.strip().strip('"').strip("'")
host = env["LANGFUSE_HOST"].rstrip("/")
now = datetime.datetime.now(datetime.timezone.utc)
q = {"view": "observations", "fromTimestamp": (now - datetime.timedelta(hours=12)).isoformat(), "toTimestamp": (now + datetime.timedelta(minutes=5)).isoformat(),
     "dimensions": [], "metrics": [{"measure": "count", "aggregation": "count"}, {"measure": "inputTokens", "aggregation": "sum"}, {"measure": "outputTokens", "aggregation": "sum"}],
     "filters": [{"column": "environment", "operator": "=", "value": "e2e-attack", "type": "string"}, {"column": "type", "operator": "=", "value": "GENERATION", "type": "string"}]}
r = httpx.get(host + "/api/public/v2/metrics", params={"query": json.dumps(q)}, auth=(env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"]), timeout=60)
if r.status_code != 200: print("ERR", r.status_code, r.text[:200]); sys.exit()
d = r.json().get("data", [])
print(d)
if d:
    row = d[0]; pi = float(row.get("sum_inputTokens", 0)); po = float(row.get("sum_outputTokens", 0))
    print("gens", row.get("count_count"), "KRW_upper", round(pi*0.00085 + po*0.0040))
