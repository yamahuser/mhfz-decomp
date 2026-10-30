"""Sanity checks for analysis\wiiu_matches.csv: source-order agreement per method + random samples vs merged names.
usage: python -I tools\wiiuaudit.py [n_samples]"""
import csv, collections, os, random, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, "analysis")
rows = sorted(csv.DictReader(open(os.path.join(A, "wiiu_matches.csv"), encoding="utf-8")), key=lambda r: int(r["pc_addr"], 16))
old = {r["addr"]: r for r in csv.DictReader(open(os.path.join(A, "merged_names.csv"), encoding="utf-8"))}
agree, tot = collections.Counter(), collections.Counter()
for i, r in enumerate(rows):
    nb = [rows[j] for j in (i - 1, i + 1) if 0 <= j < len(rows)]
    w = int(r["wiiu_addr"], 16)
    ok = 0
    for j, n in zip((i - 1, i + 1), nb):
        wn = int(n["wiiu_addr"], 16)
        d = wn - w if j > i else w - wn
        ok += 0 < d < 0x40000          # neighbour lands just after/before on the Wii U side too
    tot[r["method"]] += 1
    agree[r["method"]] += ok >= 1
for m in tot:
    print(f"{m:7} {tot[m]:6}  order-consistent with a neighbour: {agree[m] / tot[m]:.1%}")
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
for r in random.sample(rows, int(sys.argv[1]) if len(sys.argv) > 1 else 25):
    o = old.get(r["pc_addr"], {})
    print(f'{r["pc_addr"]} {r["method"]:6} {r["name"][:45]:45} | was: {o.get("name", "")[:40]} [{o.get("tier", "")}]')

# callee agreement: of p's matched callees, how many map into w's callee set (independent of layout order)
import pickle
W, P = pickle.load(open(os.path.join(ROOT, "wiiu", "features.pkl"), "rb"))
p2w = {int(r["pc_addr"], 16): int(r["wiiu_addr"], 16) for r in rows}
meth = {int(r["pc_addr"], 16): r["method"] for r in rows}
good, seen = collections.Counter(), collections.Counter()
for p, w in p2w.items():
    wc = set(W["calls"].get(w, ()))
    for c in set(P["calls"].get(p, ())):
        if c in p2w:
            seen[meth[p]] += 1
            good[meth[p]] += p2w[c] in wc
for m in seen:
    print(f"{m:7} callee edges checked {seen[m]:6}  agree {good[m] / seen[m]:.1%}")
