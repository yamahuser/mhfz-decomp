r"""Write analysis/ghidra_names.csv (addr,name,confidence,source) for ghidra/scripts/ApplyNames.java.
Rules: Codex-reviewed names win; otherwise small-model names with confidence >= MIN_CONF; never 'unknown_*'.
Names get an 'ai_' prefix so suggestions are visibly distinct from verified names in Ghidra.
Usage: python orchestrator\export_names.py [min_conf=0.6]
"""
import csv, json, re, sys
from pathlib import Path
B = Path(__file__).parent.parent
MIN_CONF = float(sys.argv[1]) if len(sys.argv) > 1 else 0.6
best = {}
def clean(n):
    n = re.sub(r"[^A-Za-z0-9_]", "_", str(n)).strip("_")
    return n[:60]
for l in (B / "analysis" / "names.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        o = json.loads(l)
    except Exception:
        continue
    n, c = clean(o.get("name", "")), float(o.get("confidence") or 0)
    if n and not n.startswith("unknown") and c >= MIN_CONF:
        best[o["addr"]] = (n, c, "small-model")
for l in (B / "analysis" / "reviews.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        o = json.loads(l)
    except Exception:
        continue
    n = clean(o.get("name", ""))
    if n and o.get("verdict") in ("agree", "revise") and not n.startswith("unknown"):
        best[o["addr"]] = (n, float(o.get("confidence") or 0.7), "codex-reviewed")
used, rows = {}, []
for addr, (n, c, src) in sorted(best.items()):
    name = "ai_" + n
    k = used.get(name, 0); used[name] = k + 1
    rows.append((addr, name if k == 0 else f"{name}_{addr}", f"{c:.2f}", src))   # keep names unique
with open(B / "analysis" / "ghidra_names.csv", "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows([("addr", "name", "confidence", "source")] + rows)
print(f"wrote {len(rows)} names (min_conf {MIN_CONF}); reviewed: {sum(1 for r in rows if r[3]=='codex-reviewed')}")
