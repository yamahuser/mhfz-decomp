"""Match Monster Hunter 2 (Dos, PS2) decompiled functions (thirdparty/mh2-decomp, named C) to MHF-Z functions
(decomp/<addr>.c, Ghidra pseudo-C of mhfo-hd.dll) without copying any code: only numeric features are compared.

Features per function: integer/float constants (weighted by rarity in the MHF corpus), switch case-label sets,
control-flow counts (if / loops / switch / return), callee count. Pipeline:
  1. candidates from shared rare constants (inverted index), scored by weighted overlap * shape similarity
  2. anchors = mutual-best pairs with a clear margin
  3. propagation: callees/callers of anchored pairs are matched among each other (shape + constants), repeated
Output: analysis/mh2_matches.csv (mhf_addr, mh2_name, mh2_file, score, method, evidence) and a summary.
Usage: python -I mh2match.py"""
import collections, csv, math, os, re, sys

ROOT = r"C:\Users\Ayman\mhfz-60fps"
MH2 = os.path.join(ROOT, "thirdparty", "mh2-decomp", "src")
MHF = os.path.join(ROOT, "decomp")
OUT = os.path.join(ROOT, "analysis", "mh2_matches.csv")

NUM = re.compile(r"(?<![\w.])(-?(?:0x[0-9a-fA-F]+|\d+\.\d+(?:e[-+]?\d+)?|\d+))[uUlLfF]*(?![\w.])")
CASE = re.compile(r"\bcase\s+(-?(?:0x[0-9a-fA-F]+|\d+))\s*:")
CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
KW = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case"}
TRIVIAL = {0, 1, 2, 3, 4, -1, -2}


def norm(tok):
    t = tok.lower().rstrip("ulf")
    try:
        if "." in t or "e" in t and not t.startswith(("0x", "-0x")):
            v = float(t)
            return ("f", float(f"{v:.5g}"))
        v = int(t, 16) if t.lstrip("-").startswith("0x") else int(t)
        if v < 0 and v >= -0x80000000:
            v &= 0xFFFFFFFF  # compare negatives in two's complement form (Ghidra prints both styles)
        return ("i", v)
    except ValueError:
        return None


CASEBLK = re.compile(r"\bcase\s+(-?(?:0x[0-9a-fA-F]+|\d+))\s*:")


def case_calls(body, call_re):
    """{case value: [callee, ...]} for the code between one case label and the next (fallthrough blocks share)."""
    out = {}
    marks = [(m.start(), m.group(1)) for m in CASEBLK.finditer(body)]
    for i, (pos, lab) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        v = int(lab, 16) if "x" in lab.lower() else int(lab)
        out[v] = call_re(body[pos:end])
    return out


def features(body):
    consts = collections.Counter()
    for m in NUM.finditer(body):
        k = norm(m.group(1))
        if k and not (k[0] == "i" and (k[1] in TRIVIAL or k[1] in (0xFFFFFFFF, 0xFFFFFFFE))):
            consts[k] += 1
    cases = frozenset(int(c, 16) if "x" in c.lower() else int(c) for c in CASE.findall(body))
    shape = (
        len(re.findall(r"\bif\b", body)),
        len(re.findall(r"\b(for|while)\b", body)),
        len(re.findall(r"\bswitch\b", body)),
        len(re.findall(r"\breturn\b", body)),
    )
    return consts, cases, shape


# ---------------------------------------------------------------- MH2 (named C source)
FUNC_HEAD = re.compile(r"^(?!static\s+const)(?:static\s+)?(?:inline\s+)?[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*$")


def load_mh2():
    funcs = {}
    for dp, _, fs in os.walk(MH2):
        for fn in fs:
            if not fn.endswith(".c"):
                continue
            path = os.path.join(dp, fn)
            lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
            i = 0
            while i < len(lines):
                m = FUNC_HEAD.match(lines[i])
                if m and i + 1 < len(lines) and lines[i + 1].strip() == "{" and m.group(1) not in KW:
                    name = m.group(1)
                    j = i + 2
                    depth = 1
                    body = []
                    while j < len(lines) and depth > 0:
                        depth += lines[j].count("{") - lines[j].count("}")
                        body.append(lines[j])
                        j += 1
                    text = "\n".join(body)
                    calls = [c for c in CALL.findall(text) if c not in KW]
                    funcs[name] = {"file": os.path.relpath(path, MH2), "calls": list(dict.fromkeys(calls)), "seq": calls,
                                   "case_calls": case_calls(text, lambda s: [c for c in CALL.findall(s) if c not in KW]) if "case" in text else {}, "lines": len(body), **dict(zip(("consts", "cases", "shape"), features(text)))}
                    i = j
                else:
                    i += 1
    return funcs


# ---------------------------------------------------------------- MHF (Ghidra pseudo-C, one file per function)
def load_mhf():
    funcs = {}
    for fn in os.listdir(MHF):
        if not fn.endswith(".c"):
            continue
        text = open(os.path.join(MHF, fn), encoding="utf-8", errors="replace").read()
        head, _, rest = text.partition("\n")
        m = re.search(r"addr=([0-9a-f]+) bytes=(\d+)", head)
        if not m:
            continue
        cm = re.search(r"// calls:([^\n]*)", text)
        calls = cm.group(1).split() if cm else []
        body = rest.split("{", 1)[1] if "{" in rest else rest
        seq = [c.lower() for c in re.findall(r"\bFUN_([0-9a-fA-F]{8})\s*\(", body)]
        ccalls = case_calls(body, lambda s: [c.lower() for c in re.findall(r"\bFUN_([0-9a-fA-F]{8})\s*\(", s)]) if "case" in body else {}
        body = re.sub(r"\b(DAT|PTR|FUN|LAB|s|u|switchD|caseD)_[0-9a-fA-F_]+\w*", " ", body)  # drop address-like labels
        funcs[m.group(1)] = {"bytes": int(m.group(2)), "calls": calls, "seq": seq, "case_calls": ccalls, "lines": body.count("\n"), **dict(zip(("consts", "cases", "shape"), features(body)))}
    return funcs


def shape_sim(a, b):
    s = 0.0
    for x, y in zip(a["shape"], b["shape"]):
        s += 1.0 - abs(x - y) / max(x, y, 1)
    s /= len(a["shape"])
    lc = 1.0 - min(1.0, abs(len(a["calls"]) - len(b["calls"])) / max(len(a["calls"]), len(b["calls"]), 1))
    return 0.75 * s + 0.25 * lc


def main():
    print("loading MH2 ...", flush=True)
    mh2 = load_mh2()
    print(f"  {len(mh2)} MH2 functions", flush=True)
    print("loading MHF ...", flush=True)
    mhf = load_mhf()
    print(f"  {len(mhf)} MHF functions", flush=True)

    df = collections.Counter()
    for f in mhf.values():
        for k in f["consts"]:
            df[k] += 1
    N = len(mhf)
    idf = {k: math.log(N / (1 + c)) for k, c in df.items()}
    index = collections.defaultdict(list)
    for a, f in mhf.items():
        for k in f["consts"]:
            if df[k] <= 0.01 * N:  # ignore constants used by more than 1% of all functions
                index[k].append(a)

    def const_score(g, f):
        shared = set(g["consts"]) & set(f["consts"])
        w = sum(idf.get(k, math.log(N)) for k in shared)
        tot = sum(idf.get(k, math.log(N)) for k in set(g["consts"]) | set(f["consts"]))
        return (w / tot if tot else 0.0), w, shared

    def pair_score(g, f):
        c, w, shared = const_score(g, f)
        if not g["consts"] and not f["consts"]:
            c = 0.5  # both constant-free: neutral, let shape and call context decide
        case = 0.0
        if g["cases"] and f["cases"]:
            case = len(g["cases"] & f["cases"]) / len(g["cases"] | f["cases"])
        s = shape_sim(g, f)
        return 0.55 * c + 0.20 * case + 0.25 * s, w, shared

    # 1. candidates and anchors
    best = {}
    rev = collections.defaultdict(list)
    for name, g in mh2.items():
        rare = [k for k in g["consts"] if k in index]
        if not rare:
            continue
        votes = collections.Counter()
        for k in rare:
            for a in index[k]:
                votes[a] += idf.get(k, 0)
        cands = [a for a, _ in votes.most_common(40)]
        scored = sorted(((pair_score(g, mhf[a]), a) for a in cands), key=lambda x: -x[0][0])
        if not scored:
            continue
        (top, w, shared), a = scored[0]
        second = scored[1][0][0] if len(scored) > 1 else 0.0
        best[name] = (a, top, second, w, shared)
        rev[a].append((top, name))

    matches = {}
    for name, (a, top, second, w, shared) in best.items():
        mutual = max(rev[a])[1] == name
        if mutual and top >= 0.45 and w >= 8.0 and top - second >= 0.08:
            matches[name] = (a, top, "constants", f"shared={len(shared)} weight={w:.1f} margin={top - second:.2f}")
    print(f"anchors: {len(matches)}", flush=True)

    # 2. propagation through callees and callers
    mh2_callers = collections.defaultdict(set)
    for n, g in mh2.items():
        for c in g["calls"]:
            if c in mh2:
                mh2_callers[c].add(n)
    mhf_callers = collections.defaultdict(set)
    for a, f in mhf.items():
        for c in f["calls"]:
            if c in mhf:
                mhf_callers[c].add(a)
    used = {v[0] for v in matches.values()}
    for rnd in range(6):
        added = 0
        for name, (a, sc, *_rest) in list(matches.items()):
            for rel, gn, fn_ in (("callee", [c for c in mh2[name]["calls"] if c in mh2], [c for c in mhf[a]["calls"] if c in mhf]),
                                 ("caller", list(mh2_callers[name]), list(mhf_callers[a]))):
                gn = [x for x in gn if x not in matches]
                fn_ = [x for x in fn_ if x not in used]
                if not gn or not fn_ or len(gn) * len(fn_) > 900:
                    continue
                for g_name in gn:
                    scored = sorted(((pair_score(mh2[g_name], mhf[x])[0], x) for x in fn_), reverse=True)
                    if not scored:
                        continue
                    top, x = scored[0]
                    second = scored[1][0] if len(scored) > 1 else 0.0
                    back = max(pair_score(mh2[y], mhf[x])[0] for y in gn)
                    if top >= 0.55 and top - second >= 0.10 and abs(back - top) < 1e-9 and x not in used:
                        matches[g_name] = (x, top, f"{rel}-of:{name}", f"margin={top - second:.2f} round={rnd}")
                        used.add(x)
                        added += 1
        print(f"propagation round {rnd}: +{added}", flush=True)
        if not added:
            break

    # 3. order-aware call alignment: a matched pair calls its callees in (mostly) the same order, so align the two call
    # sequences (Needleman-Wunsch on shape+constant similarity) and accept aligned pairs proposed by enough parents.
    def seq_mh2(name):
        return [c for c in mh2[name]["seq"] if c in mh2]

    def seq_mhf(a):
        return [c for c in mhf[a]["seq"] if c in mhf]

    def size_ok(g, f):
        lo, hi = sorted((max(g["lines"], 1), max(f["lines"], 1)))
        return hi <= 4 * lo + 6

    sim_cache = {}

    def sim(g_name, a):
        key = (g_name, a)
        if key not in sim_cache:
            g, f = mh2[g_name], mhf[a]
            sim_cache[key] = pair_score(g, f)[0] if size_ok(g, f) else 0.0
        return sim_cache[key]

    def align(xs, ys):
        n, m = len(xs), len(ys)
        if not n or not m or n * m > 40000:
            return []
        gap = -0.15
        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        bt = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            dp[i][0], bt[i][0] = dp[i - 1][0] + gap, 1
        for j in range(1, m + 1):
            dp[0][j], bt[0][j] = dp[0][j - 1] + gap, 2
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                s = sim(xs[i - 1], ys[j - 1]) - 0.35
                best_v, best_b = dp[i - 1][j - 1] + s, 0
                if dp[i - 1][j] + gap > best_v:
                    best_v, best_b = dp[i - 1][j] + gap, 1
                if dp[i][j - 1] + gap > best_v:
                    best_v, best_b = dp[i][j - 1] + gap, 2
                dp[i][j], bt[i][j] = best_v, best_b
        out, i, j = [], n, m
        while i > 0 and j > 0:
            b = bt[i][j]
            if b == 0:
                out.append((xs[i - 1], ys[j - 1]))
                i, j = i - 1, j - 1
            elif b == 1:
                i -= 1
            else:
                j -= 1
        return out

    for rnd in range(12):
        proposals = collections.defaultdict(list)
        mult_ok = collections.defaultdict(int)
        for name, (a, *_r) in list(matches.items()):
            sx, sy = seq_mh2(name), seq_mhf(a)
            cx, cy = collections.Counter(sx), collections.Counter(sy)
            for g_name, x in align(sx, sy):
                if g_name in matches or x in used:
                    continue
                proposals[(g_name, x)].append(name)
                if cx[g_name] == cy[x]:
                    mult_ok[(g_name, x)] += 1
        by_g = collections.defaultdict(list)
        by_x = collections.defaultdict(list)
        for (g_name, x), parents in proposals.items():
            s = sim(g_name, x)
            support = len(set(parents))
            bonus = (0.12 if mult_ok[(g_name, x)] else 0.0) + 0.08 * min(support - 1, 3)
            s = s + bonus
            if s >= 0.62:
                by_g[g_name].append((support, s, x, parents))
                by_x[x].append((support, s, g_name))
        added = 0
        for g_name, opts in by_g.items():
            opts.sort(reverse=True)
            support, s, x, parents = opts[0]
            if len(opts) > 1 and opts[1][:2] == opts[0][:2]:
                continue  # ambiguous
            if max(by_x[x])[2] != g_name or x in used:
                continue
            matches[g_name] = (x, s, f"callseq-of:{parents[0]}", f"support={support} round={rnd}")
            used.add(x)
            added += 1
        print(f"call-sequence round {rnd}: +{added} (total {len(matches)})", flush=True)
        if not added:
            break

    # 4. multiplicity voting: inside a matched pair, a callee used k times in MH2 maps to the callee used k times in MHF
    # (ties broken by order of first use). Votes are pooled across every matched pair; shared helpers collect many.
    def first_use_order(seq):
        seen = []
        for c in seq:
            if c not in seen:
                seen.append(c)
        return seen

    def vote_stage():
      for rnd in range(15):
        votes = collections.Counter()
        for name, (a, *_r) in list(matches.items()):
            sx, sy = seq_mh2(name), seq_mhf(a)
            if not sx or not sy:
                continue
            cx, cy = collections.Counter(sx), collections.Counter(sy)
            ox, oy = first_use_order(sx), first_use_order(sy)
            groups_x = collections.defaultdict(list)
            groups_y = collections.defaultdict(list)
            for c in ox:
                groups_x[cx[c]].append(c)
            for c in oy:
                groups_y[cy[c]].append(c)
            for k, gx in groups_x.items():
                gy = groups_y.get(k, [])
                if len(gx) == len(gy) and len(gx) <= 3:
                    for g_name, x in zip(gx, gy):
                        if g_name not in matches and x not in used:
                            votes[(g_name, x)] += 2 if len(gx) == 1 else 1
        best_for_g = collections.defaultdict(list)
        best_for_x = collections.defaultdict(list)
        for (g_name, x), v in votes.items():
            best_for_g[g_name].append((v, x))
            best_for_x[x].append((v, g_name))
        added = 0
        for g_name, opts in best_for_g.items():
            opts.sort(reverse=True)
            v, x = opts[0]
            v2 = opts[1][0] if len(opts) > 1 else 0
            rv = sorted(best_for_x[x], reverse=True)
            if rv[0][1] != g_name or (len(rv) > 1 and rv[1][0] * 2 > rv[0][0]):
                continue
            s = pair_score(mh2[g_name], mhf[x])[0]
            if x in used or v < 2 or v < 2 * v2:
                if not (v >= 2 and s >= 0.55 and v > v2):
                    continue
            if x in used:
                continue
            matches[g_name] = (x, s, "callcount-vote", f"votes={v} next={v2} round={rnd}")
            used.add(x)
            added += 1
        print(f"vote round {rnd}: +{added} (total {len(matches)})", flush=True)
        if not added:
            break

    # 5. layout: functions of one MH2 source file sit in the same order in MHF. Between two matched functions of the
    # same file that are close in MHF, align the unmatched functions on both sides by position and similarity.
    order = collections.defaultdict(list)
    for n, g in mh2.items():
        order[g["file"]].append(n)
    pos = {n: i for names in order.values() for i, n in enumerate(names)}
    mhf_sorted = sorted(mhf)
    mhf_idx = {a: i for i, a in enumerate(mhf_sorted)}

    def align_free(xs, ys):
        n, m = len(xs), len(ys)
        if not n or not m or n * m > 20000:
            return []
        gap = -0.05
        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        bt = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            dp[i][0], bt[i][0] = dp[i - 1][0] + gap, 1
        for j in range(1, m + 1):
            dp[0][j], bt[0][j] = dp[0][j - 1] + gap, 2
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                s = pair_score(mh2[xs[i - 1]], mhf[ys[j - 1]])[0] - 0.40
                cand = [(dp[i - 1][j - 1] + s, 0), (dp[i - 1][j] + gap, 1), (dp[i][j - 1] + gap, 2)]
                dp[i][j], bt[i][j] = max(cand)
        out, i, j = [], n, m
        while i > 0 and j > 0:
            b = bt[i][j]
            if b == 0:
                out.append((xs[i - 1], ys[j - 1]))
                i, j = i - 1, j - 1
            elif b == 1:
                i -= 1
            else:
                j -= 1
        return out

    def layout_stage():
        added = 0
        by_file = collections.defaultdict(list)
        for n, (a, *_r) in matches.items():
            by_file[mh2[n]["file"]].append((pos[n], mhf_idx[a]))
        for f, lst in by_file.items():
            lst.sort()
            names = order[f]
            for (p1, i1), (p2, i2) in zip(lst, lst[1:]):
                if not (i2 > i1 and p2 > p1 + 0):
                    continue
                gx = [n for n in names[p1 + 1:p2] if n not in matches]
                gy = [a for a in mhf_sorted[i1 + 1:i2] if a not in used]
                if not gx or not gy or (i2 - i1) > 6 * (p2 - p1) + 12:
                    continue
                for g_name, x in align_free(gx, gy):
                    s = pair_score(mh2[g_name], mhf[x])[0]
                    if s >= 0.42 and g_name not in matches and x not in used:
                        matches[g_name] = (x, s, f"layout:{f}", f"between {names[p1]} and {names[p2]}")
                        used.add(x)
                        added += 1
            # edges: past the last and before the first matched function of the file (stricter threshold)
            if lst:
                (pl, il), (pf, if_) = lst[-1], lst[0]
                K = 12
                tail_x = [n for n in names[pl + 1:pl + 1 + K] if n not in matches]
                tail_y = [a for a in mhf_sorted[il + 1:il + 1 + 2 * K] if a not in used]
                head_x = [n for n in names[max(0, pf - K):pf] if n not in matches]
                head_y = [a for a in mhf_sorted[max(0, if_ - 2 * K):if_] if a not in used]
                for gx, gy, where in ((tail_x, tail_y, "after"), (head_x, head_y, "before")):
                    for g_name, x in align_free(gx, gy):
                        s = pair_score(mh2[g_name], mhf[x])[0]
                        if s >= 0.52 and g_name not in matches and x not in used:
                            matches[g_name] = (x, s, f"layout-edge:{f}", f"{where} matched block")
                            used.add(x)
                            added += 1
        return added

    def weak_anchor_stage():
        # weaker constant matches from step 1, accepted only when the MHF address sits between the MHF addresses of the
        # nearest matched functions before and after it in the same MH2 file (layout-consistent)
        added = 0
        by_file = collections.defaultdict(list)
        for n, (a, *_r) in matches.items():
            by_file[mh2[n]["file"]].append((pos[n], mhf_idx[a]))
        for lst in by_file.values():
            lst.sort()
        for name, (a, top, second, w, shared) in best.items():
            if name in matches or a in used or top < 0.33 or top - second < 0.03 or w < 4.0:
                continue
            lst = by_file.get(mh2[name]["file"], [])
            p = pos[name]
            before = [x for x in lst if x[0] < p]
            after = [x for x in lst if x[0] > p]
            ia = mhf_idx[a]
            ok = False
            if before and after:
                ok = before[-1][1] < ia < after[0][1]
            elif before:
                ok = 0 < ia - before[-1][1] <= 3 * (p - before[-1][0]) + 5
            elif after:
                ok = 0 < after[0][1] - ia <= 3 * (after[0][0] - p) + 5
            if ok:
                matches[name] = (a, top, "constants+layout", f"weight={w:.1f} margin={top - second:.2f}")
                used.add(a)
                added += 1
        return added

    def window_stage():
        # Per MH2 file: cluster its matched MHF addresses; inside each cluster window (+-0x8000), score every unmatched
        # function of the file against every unused MHF function there and accept mutual clear winners.
        added = 0
        by_file = collections.defaultdict(list)
        for n, (a, *_r) in matches.items():
            by_file[mh2[n]["file"]].append(int(a, 16))
        for f, addrs in by_file.items():
            if len(addrs) < 3:
                continue
            addrs.sort()
            clusters, cur = [], [addrs[0]]
            for x in addrs[1:]:
                if x - cur[-1] < 0x20000:
                    cur.append(x)
                else:
                    clusters.append(cur)
                    cur = [x]
            clusters.append(cur)
            gx = [n for n in order[f] if n not in matches]
            for cl in clusters:
                if len(cl) < 2 or not gx:
                    continue
                lo, hi = cl[0] - 0x8000, cl[-1] + 0x8000
                gy = [a for a in mhf_sorted if lo <= int(a, 16) <= hi and a not in used]
                if not gy or len(gx) * len(gy) > 250000:
                    continue
                sc = {}
                for g_name in gx:
                    for x in gy:
                        if size_ok(mh2[g_name], mhf[x]):
                            s = pair_score(mh2[g_name], mhf[x])[0]
                            if s >= 0.40:
                                sc[(g_name, x)] = s
                best_g, best_x = collections.defaultdict(list), collections.defaultdict(list)
                for (g_name, x), s in sc.items():
                    best_g[g_name].append(s)
                    best_x[x].append(s)
                for (g_name, x), s in sorted(sc.items(), key=lambda kv: -kv[1]):
                    if g_name in matches or x in used:
                        continue
                    sg = sorted(best_g[g_name], reverse=True)
                    sx = sorted(best_x[x], reverse=True)
                    if s >= 0.52 and s == sg[0] == sx[0] and (len(sg) < 2 or sg[1] < s - 0.05) and (len(sx) < 2 or sx[1] < s - 0.05):
                        matches[g_name] = (x, s, f"window:{f}", f"cluster {cl[0]:08x}-{cl[-1]:08x}")
                        used.add(x)
                        added += 1
            gx = None
        return added

    # 6. pointer tables: MH2 initialised arrays of function names vs runs of function addresses in MHF's data sections,
    # aligned index by index once two or more entries agree with existing matches.
    def load_mh2_tables():
        tabs = []
        pat = re.compile(r"\b(\w+)\s*\[[^\]]*\]\s*=\s*\{(.*?)\};", re.S)
        for dp, _, fs in os.walk(MH2):
            for fn in fs:
                if not fn.endswith(".c"):
                    continue
                text = open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read()
                for m in pat.finditer(text):
                    body = re.sub(r"/\*.*?\*/", "", m.group(2), flags=re.S)
                    if "{" in body:
                        continue
                    ents = [e.strip().lstrip("&") for e in body.split(",")]
                    if ents and ents[-1] == "":
                        ents.pop()
                    named = [e for e in ents if e in mh2]
                    if len(named) >= 3 and len(named) >= 0.5 * len(ents):
                        tabs.append((m.group(1), [e if e in mh2 else None for e in ents]))
        return tabs

    def load_mhf_tables():
        import struct
        dll = os.path.join(os.path.dirname(ROOT), "Desktop", "MHFZ", "mhfo-hd.dll")
        if not os.path.exists(dll):
            return []
        b = open(dll, "rb").read()
        pe = struct.unpack_from("<I", b, 0x3C)[0]
        nsec = struct.unpack_from("<H", b, pe + 6)[0]
        optsz = struct.unpack_from("<H", b, pe + 20)[0]
        base = struct.unpack_from("<I", b, pe + 24 + 28)[0]
        funcs = {int(a, 16) for a in mhf}
        tabs = []
        for i in range(nsec):
            s = pe + 24 + optsz + 40 * i
            va, rawsz, rawptr, chars = struct.unpack_from("<I", b, s + 12)[0], struct.unpack_from("<I", b, s + 16)[0], struct.unpack_from("<I", b, s + 20)[0], struct.unpack_from("<I", b, s + 36)[0]
            if rawsz < 0x1000:  # this DLL is packed: every section is flagged executable, .text has no raw data
                continue
            run = []
            for off in range(0, rawsz - 3, 4):
                v = struct.unpack_from("<I", b, rawptr + off)[0]
                if v in funcs or (v == 0 and run):
                    run.append(f"{v:08x}" if v else None)
                    continue
                while run and run[-1] is None:
                    run.pop()
                if sum(1 for x in run if x) >= 3:
                    tabs.append((base + va + off - 4 * len(run), run))
                run = []
        return tabs

    mh2_tabs = load_mh2_tables()
    mhf_tabs = load_mhf_tables()
    print(f"pointer tables: MH2 {len(mh2_tabs)}, MHF {len(mhf_tabs)}", flush=True)
    mhf_tab_of = collections.defaultdict(list)
    for ti, (_, run) in enumerate(mhf_tabs):
        for x in run:
            if x:
                mhf_tab_of[x].append(ti)

    def table_stage():
        added = 0
        for tname, ents in mh2_tabs:
            known = [(i, matches[e][0]) for i, e in enumerate(ents) if e and e in matches]
            if len(known) < 2:
                continue
            cand_tabs = collections.Counter()
            for i, a in known:
                for ti in mhf_tab_of.get(a, []):
                    run = mhf_tabs[ti][1]
                    # same relative index? try every offset implied by this entry
                    for j, x in enumerate(run):
                        if x == a:
                            cand_tabs[(ti, j - i)] += 1
            for (ti, shift), agree in cand_tabs.items():
                run = mhf_tabs[ti][1]
                conflicts = sum(1 for i, a in known if 0 <= i + shift < len(run) and run[i + shift] and run[i + shift] != a)
                if agree < 2 or agree < 2 * conflicts:
                    continue
                for i, e in enumerate(ents):
                    j = i + shift
                    if not e or e in matches or not (0 <= j < len(run)) or not run[j] or run[j] in used:
                        continue
                    x = run[j]
                    if ents.count(e) != 1 or run.count(x) != 1:
                        continue  # repeated entries (shared nop handlers) are ambiguous
                    s = pair_score(mh2[e], mhf[x])[0]
                    matches[e] = (x, s, f"ptrtable:{tname}", f"index {i} (+{shift}), {agree} agreeing entries")
                    used.add(x)
                    added += 1
        return added

    NUMNAME = re.compile(r"^(.*?_(?:State|Act|Mode|Step|Kind|Sub|Phase)?\w*?)([0-9A-F]{2,3})$")

    def numbered_table_stage():
        # MHF dispatch tables vs MH2's numbered handler names: if matched entries Prefix_NN sit at table indices whose
        # differences equal the differences of NN, the unmatched slots are Prefix_<number for that index>.
        added = 0
        for _, run in mhf_tabs:
            inv = {x: n for n, (x, *_r) in matches.items()}
            groups = collections.defaultdict(list)
            for j, x in enumerate(run):
                n = inv.get(x) if x else None
                mm = NUMNAME.match(n) if n else None
                if mm:
                    for base in (16, 10):
                        try:
                            groups[(mm.group(1), len(mm.group(2)), base)].append((j, int(mm.group(2), base)))
                        except ValueError:
                            pass
            for (prefix, width, base), pts in groups.items():
                if len(pts) < 2:
                    continue
                offs = collections.Counter(num - j for j, num in pts)
                off, agree = offs.most_common(1)[0]
                if agree < 2 or agree < len(pts) - agree + 2:
                    continue
                for j, x in enumerate(run):
                    if not x or x in used:
                        continue
                    num = j + off
                    if num < 0:
                        continue
                    name = f"{prefix}{num:0{width}X}" if base == 16 else f"{prefix}{num:0{width}d}"
                    if name in mh2 and name not in matches and run.count(x) == 1:
                        matches[name] = (x, pair_score(mh2[name], mhf[x])[0], "numbered-table", f"{prefix}NN at index {j} (offset {off}, {agree} agreeing)")
                        used.add(x)
                        added += 1
        return added

    def caller_intersection_stage():
        # An unmatched MH2 function called by >= 2 matched functions maps to the unique unused MHF function that all of
        # their MHF counterparts call (ties broken by score with a margin).
        added = 0
        for g_name in list(mh2):
            if g_name in matches:
                continue
            callers = [c for c in mh2_callers.get(g_name, ()) if c in matches]
            if len(callers) < 2:
                continue
            common = None
            for c in callers:
                cs = {x for x in mhf[matches[c][0]]["calls"] if x in mhf and x not in used}
                common = cs if common is None else common & cs
                if not common:
                    break
            if not common:
                continue
            scored = sorted(((pair_score(mh2[g_name], mhf[x])[0], x) for x in common), reverse=True)
            top, x = scored[0]
            second = scored[1][0] if len(scored) > 1 else -1
            if (len(scored) == 1 and top >= 0.30) or (top >= 0.45 and top - second >= 0.10):
                matches[g_name] = (x, top, "caller-intersection", f"{len(callers)} matched callers, {len(scored)} candidates")
                used.add(x)
                added += 1
        return added

    def switch_case_stage():
        # Matched pairs whose bodies switch on a value: the k-th distinct unmatched callee in MH2's case N pairs with the
        # k-th distinct unused callee in MHF's case N when both cases call the same number of such functions.
        votes = collections.Counter()
        trusted = set()  # proposals from switches whose other cases already agree with existing matches
        for name, (a, *_r) in list(matches.items()):
            cg, cf = mh2[name]["case_calls"], mhf[a]["case_calls"]
            if not cg or not cf:
                continue
            agree = 0
            for lab in set(cg) & set(cf):
                fset = set(cf[lab])
                agree += any(c in matches and matches[c][0] in fset for c in cg[lab])
            for lab in set(cg) & set(cf):
                gx1 = [c for c in dict.fromkeys(cg[lab]) if c in mh2 and c not in matches]
                fx1 = [c for c in dict.fromkeys(cf[lab]) if c in mhf and c not in used]
                if agree >= 2 and len(gx1) == 1 and len(fx1) == 1:
                    trusted.add((gx1[0], fx1[0]))
            for lab in set(cg) & set(cf):
                gx = list(dict.fromkeys(c for c in cg[lab] if c in mh2))
                fx = list(dict.fromkeys(c for c in cf[lab] if c in mhf))
                if len(gx) != len(fx) or not gx or len(gx) > 4:
                    continue
                for g_name, x in zip(gx, fx):
                    if g_name not in matches and x not in used:
                        votes[(g_name, x)] += 1
        added = 0
        by_g, by_x = collections.defaultdict(list), collections.defaultdict(list)
        for (g_name, x), v in votes.items():
            by_g[g_name].append((v, x))
            by_x[x].append((v, g_name))
        for g_name, opts in by_g.items():
            opts.sort(reverse=True)
            v, x = opts[0]
            if len(opts) > 1 and opts[1][0] >= v:
                continue
            rv = sorted(by_x[x], reverse=True)
            if rv[0][1] != g_name or (len(rv) > 1 and rv[1][0] >= rv[0][0]) or x in used:
                continue
            s = pair_score(mh2[g_name], mhf[x])[0]
            if v >= 2 or s >= 0.35 or ((g_name, x) in trusted and s >= 0.12):
                matches[g_name] = (x, s, "switch-case", f"votes={v}{' trusted-switch' if (g_name, x) in trusted else ''}")
                used.add(x)
                added += 1
        return added

    def callee_intersection_stage():
        # An unmatched MH2 function that calls >= 2 matched functions maps to the unique unused MHF function that calls
        # all of their MHF counterparts (ties broken by score with a margin).
        added = 0
        for g_name, g in mh2.items():
            if g_name in matches:
                continue
            callees = [c for c in g["calls"] if c in matches and c != g_name]
            if len(callees) < 2:
                continue
            common = None
            for c in callees:
                cs = {x for x in mhf_callers.get(matches[c][0], ()) if x not in used}
                common = cs if common is None else common & cs
                if not common:
                    break
            if not common or len(common) > 20:
                continue
            scored = sorted(((pair_score(g, mhf[x])[0], x) for x in common), reverse=True)
            top, x = scored[0]
            second = scored[1][0] if len(scored) > 1 else -1
            if (len(scored) == 1 and top >= 0.30) or (top >= 0.45 and top - second >= 0.10):
                matches[g_name] = (x, top, "callee-intersection", f"{len(callees)} matched callees, {len(scored)} candidates")
                used.add(x)
                added += 1
        return added

    def sandwich_stage():
        # Inside a matched pair, the first-use call orders on both sides are aligned at callees that already match each
        # other; where exactly one unmatched callee sits between the same two anchors on both sides, pair them.
        added = 0
        for name, (a, *_r) in list(matches.items()):
            sx = first_use_order(seq_mh2(name))
            sy = first_use_order(seq_mhf(a))
            if len(sx) < 3 or len(sy) < 3:
                continue
            pos_y = {x: j for j, x in enumerate(sy)}
            anchors = [(-1, -1)]
            for i, g_name in enumerate(sx):
                if g_name in matches and matches[g_name][0] in pos_y:
                    j = pos_y[matches[g_name][0]]
                    if j > anchors[-1][1]:
                        anchors.append((i, j))
            anchors.append((len(sx), len(sy)))
            if len(anchors) < 4:  # need at least two real anchors to trust the alignment
                continue
            for (i1, j1), (i2, j2) in zip(anchors, anchors[1:]):
                gx = [g for g in sx[i1 + 1:i2] if g not in matches]
                fx = [x for x in sy[j1 + 1:j2] if x not in used]
                if len(gx) == 1 and len(fx) == 1 and i2 - i1 == 2 and j2 - j1 == 2:
                    s = pair_score(mh2[gx[0]], mhf[fx[0]])[0]
                    if s >= 0.15:
                        matches[gx[0]] = (fx[0], s, "call-sandwich", f"in {name} between matched calls")
                        used.add(fx[0])
                        added += 1
        return added

    def caseset_stage():
        # Dispatchers (ChangeState, SetGroupNState, ...) keep their case-label sets. Near a file's existing matches
        # (+-0x40000), pair unmatched functions with >= 5 case labels whose label sets nearly coincide.
        added = 0
        by_file = collections.defaultdict(list)
        for n, (a, *_r) in matches.items():
            by_file[mh2[n]["file"]].append(int(a, 16))
        cand_f = [a for a in mhf if len(mhf[a]["cases"]) >= 5]
        for f, addrs in by_file.items():
            gx = [n for n in order[f] if n not in matches and len(mh2[n]["cases"]) >= 5]
            if not gx:
                continue
            near = [a for a in cand_f if a not in used and any(abs(int(a, 16) - x) <= 0x40000 for x in addrs)]
            for g_name in gx:
                gc = mh2[g_name]["cases"]
                scored = []
                for x in near:
                    fc = mhf[x]["cases"]
                    j = len(gc & fc) / len(gc | fc)
                    if j >= (0.75 if sum(1 for n in order[f] if n in matches) < 0.10 * len(order[f]) else 0.85):
                        scored.append((j + 0.2 * shape_sim(mh2[g_name], mhf[x]), x))
                scored.sort(reverse=True)
                if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.12) and scored[0][1] not in used:
                    x = scored[0][1]
                    matches[g_name] = (x, pair_score(mh2[g_name], mhf[x])[0], f"caseset:{f}", f"label-set similarity {scored[0][0]:.2f}, {len(scored)} candidates")
                    used.add(x)
                    added += 1
        return added

    vote_stage()
    for rnd in range(8):
        a3 = table_stage() + numbered_table_stage() + caller_intersection_stage() + switch_case_stage() + callee_intersection_stage() + sandwich_stage() + (caseset_stage() if rnd >= 2 else 0)
        print(f"table round {rnd}: +{a3} (total {len(matches)})", flush=True)
        a2 = window_stage() + a3
        print(f"window round {rnd}: +{a2} (total {len(matches)})", flush=True)
        a0 = weak_anchor_stage() + a2
        print(f"weak-anchor round {rnd}: +{a0} (total {len(matches)})", flush=True)
        a1 = layout_stage()
        print(f"layout round {rnd}: +{a1} (total {len(matches)})", flush=True)
        vote_stage()
        if not a1 and not a0:
            break

    # 7. consistency check: for each pair, of its MH2 callees that are matched, how many map to callees of the MHF side
    # (and the same for callers). Pairs that contradict their matched neighbours are dropped.
    def consistency(name):
        a = matches[name][0]
        agree = total = 0
        fcalls = set(mhf[a]["calls"])
        for c in mh2[name]["calls"]:
            if c in matches and c != name:
                total += 1
                agree += matches[c][0] in fcalls
        fcallers = mhf_callers.get(a, set())
        for c in mh2_callers.get(name, ()):
            if c in matches and c != name:
                total += 1
                agree += matches[c][0] in fcallers
        return agree, total

    for rnd in range(3):
        drop = []
        for name in list(matches):
            agree, total = consistency(name)
            if total >= 3 and agree * 3 < total and not matches[name][2].startswith("constants"):
                drop.append(name)
        for name in drop:
            used.discard(matches[name][0])
            del matches[name]
        print(f"consistency round {rnd}: dropped {len(drop)} (total {len(matches)})", flush=True)
        if not drop:
            break
    cons = {n: consistency(n) for n in matches}
    tot = sum(t for _, t in cons.values())
    print(f"call-graph agreement over matched neighbours: {sum(a for a, _ in cons.values())}/{tot}", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["mhf_addr", "mh2_name", "mh2_file", "score", "method", "evidence"])
        for name, (a, sc, method, ev) in sorted(matches.items(), key=lambda kv: kv[1][0]):
            ag, tt = cons.get(name, (0, 0))
            w.writerow([a, name, mh2[name]["file"], f"{sc:.3f}", method, f"{ev}; graph {ag}/{tt}"])
    import json
    with open(os.path.join(os.path.dirname(OUT), "mh2_names.jsonl"), "w", encoding="utf-8") as fh:
        for name, (a, sc, method, ev) in sorted(matches.items(), key=lambda kv: kv[1][0]):
            fh.write(json.dumps({"addr": a, "name": name, "confidence": round(min(0.95, 0.5 + sc / 2), 2), "subsystem": "",
                                 "purpose": f"MH2 counterpart {mh2[name]['file']}:{name} ({method}; {ev})"}) + "\n")
    print(f"wrote {len(matches)} matches to {OUT}")
    by_file = collections.Counter(mh2[n]["file"].split(os.sep)[-1] for n in matches)
    print("top MH2 files:", by_file.most_common(12))


if __name__ == "__main__":
    main()
