"""Per-monster coverage of the MH2 match list."""
import collections, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mh2match as M
mh2 = M.load_mh2()
tot = collections.Counter(g["file"] for g in mh2.values())
got = collections.Counter(mh2[r["mh2_name"]]["file"] for r in csv.DictReader(open(M.OUT, encoding="utf-8")))
print("  ".join(f"{os.path.basename(f)[3:-2]}={got[f]}/{tot[f]}" for f in sorted(tot, key=lambda f: -tot[f]) if os.path.basename(f).startswith("em_")))
