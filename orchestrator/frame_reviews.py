"""Print Codex reviews for the direct callees of the frame function 1000a4c0 and the tick 108e3f00 (and their callees)."""
import json, re
from pathlib import Path
B = Path(__file__).parent.parent
def calls(a):
    p = B / "decomp" / f"{a}.c"
    return [c for c in p.read_text(errors="replace").splitlines()[1].replace("// calls:", "").split() if len(c) == 8 and not c.startswith("EXTERNAL")] if p.exists() else []
rev = {}
for l in (B / "analysis" / "reviews.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(l); rev[r["addr"]] = r
seen, todo = set(), ["1000a4c0", "108e3f00"]
while todo:
    a = todo.pop(0)
    if a in seen: continue
    seen.add(a); todo += calls(a)
    if a in rev and a not in ("1000a4c0", "108e3f00"):
        r = rev[a]
        print(f"{a} {r.get('name')} [{r.get('verdict')}] {r.get('purpose','')[:300]}")
        for h in r.get("struct_hints", [])[:4]: print("    -", str(h)[:200])
        if r.get("notes"): print("    notes:", str(r["notes"])[:300])
print(f"\n{len([a for a in seen if a in rev])} reviewed of {len(seen)} reachable-from-frame functions seen")
