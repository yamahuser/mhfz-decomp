"""Print a side-by-side feature summary for a random sample of matches of one method, for manual precision checks."""
import csv, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mh2match as M
method = sys.argv[1] if len(sys.argv) > 1 else "layout"
k = int(sys.argv[2]) if len(sys.argv) > 2 else 8
mh2 = M.load_mh2()
rows = [r for r in csv.DictReader(open(M.OUT)) if r["method"].startswith(method)]
random.seed(7)
for r in random.sample(rows, min(k, len(rows))):
    g = mh2[r["mh2_name"]]
    text = open(os.path.join(M.MHF, r["mhf_addr"] + ".c"), encoding="utf-8", errors="replace").read()
    head = text.split("\n", 1)[0]
    f = M.load_mhf.__globals__  # noqa
    _, _, shape_f = M.features(text)
    consts_f, cases_f, _ = M.features(text)
    sg = sorted(k[1] for k in g["consts"])[:10]
    sf = sorted(k[1] for k in consts_f)[:10]
    print(f"{r['mh2_name']:34s} -> {r['mhf_addr']} score {r['score']} [{r['method']}]")
    print(f"   MH2 lines {g['lines']:4d} shape {g['shape']} calls {len(g['calls'])} consts {sg}")
    print(f"   MHF {head[3:]:30s} shape {shape_f} consts {sf}")
