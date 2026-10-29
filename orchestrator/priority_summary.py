"""Compact view of Codex reviews for analysis/priority.txt functions, most camera-relevant first."""
import json, re
from pathlib import Path
B = Path(__file__).parent.parent
prio = set((B / "analysis" / "priority.txt").read_text().split())
rev = {}
for l in (B / "analysis" / "reviews.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(l); rev[r["addr"]] = r
def score(r):
    t = (r.get("name", "") + r.get("purpose", "") + str(r.get("notes", ""))).lower()
    return sum(t.count(k) for k in ("camera", "view", "matrix", "interpol", "lerp", "slerp", "yaw", "pitch", "smooth"))
rows = sorted((rev[a] for a in prio if a in rev), key=score, reverse=True)
for r in rows[:14]:
    print(f"{r['addr']} {r.get('name')} (conf {r.get('confidence')}, score {score(r)}): {r.get('purpose','')[:220]}")
    for h in (r.get("struct_hints") or [])[:2]: print("    -", str(h)[:160])
