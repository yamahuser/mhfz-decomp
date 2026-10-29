"""Compare the switch cases of a matched pair: python mh2diag.py <mh2 name>"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mh2match as M
name = sys.argv[1]
mh2 = M.load_mh2()
m = {r["mh2_name"]: r["mhf_addr"] for r in csv.DictReader(open(M.OUT, encoding="utf-8"))}
a = m[name]
text = open(os.path.join(M.MHF, a + ".c"), encoding="utf-8", errors="replace").read()
import re
fcases = M.case_calls(text, lambda s: [c.lower() for c in re.findall(r"\bFUN_([0-9a-fA-F]{8})\s*\(", s)])
gcases = mh2[name]["case_calls"]
print(name, a, "MH2 cases", sorted(gcases)[:40], "\nMHF cases", sorted(fcases)[:40])
inv = {v: k for k, v in m.items()}
for lab in sorted(set(gcases) | set(fcases))[:30]:
    g = [c for c in gcases.get(lab, []) if c in mh2]
    f = fcases.get(lab, [])
    print(f"case {lab:4d}: MH2 {g[:4]}  MHF {[x + ('=' + inv[x] if x in inv else '') for x in f[:4]]}")
