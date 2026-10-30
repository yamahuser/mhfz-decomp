"""Transfer real function names from the unstripped Wii U build (mhfo-wiiu.rpx) onto the PC DLL (mhfo-hd.dll).

Both sides are reduced to binary-level features, nothing is decompiled or copied:
  Wii U: functions from .symtab; per-function references from .rela.text (REL24 = calls, data relocs on
         lfs/lfd = float constants, anything pointing at a C string = string ref).
  PC:    functions from ghidra\\functions.csv; per-function references from the PE base relocations in .text
         (absolute target -> string / x87+SSE float constant / function pointer); calls from decomp headers.
Pipeline:
  1. anchors from shared strings (+ floats), weighted by rarity, mutual-best with a margin
  2. call-graph propagation: neighbours of matched pairs vote, size ratio must fit
  3. layout: equal-sized gaps between consecutive anchors (same order on both sides) are paired in order
Output: analysis\\wiiu_matches.csv, analysis\\wiiu_names.jsonl (merged by merge_names.py as tier "wiiu").
usage: python -I tools\\wiiumatch.py [path\\to\\mhfo-wiiu.rpx]
"""
import bisect, collections, csv, json, math, os, pickle, re, struct, sys, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPX = r"C:\Users\Ayman\Downloads\Monster Hunter Frontier Z [Update] [0005000e1014da00]\code\mhfo-wiiu.rpx"
DLL = os.path.join(ROOT, "build", "mhfo-hd.60fps.dll")   # unpacked .text
CACHE = os.path.join(ROOT, "wiiu", "features.pkl")
A = os.path.join(ROOT, "analysis")


# ---------------------------------------------------------------- shared helpers
def as_string(buf, off):
    """Bytes of a plausible C string starting at off (ASCII or Shift-JIS), else None."""
    if off < 0 or off >= len(buf):
        return None
    end = buf.find(b"\0", off, off + 1024)
    if end < 0 or end - off < 4:
        return None
    s = buf[off:end]
    try:
        t = s.decode("cp932")
    except UnicodeDecodeError:
        return None
    if sum(c.isprintable() or c in "\r\n\t" for c in t) < len(t):
        return None
    if sum(c.isalnum() for c in t) < 2:
        return None
    return s


def fkey(v):
    if not math.isfinite(v) or v == 0 or not (1e-6 < abs(v) < 1e8):
        return None
    return ("f", float(f"{v:.5g}"))


def tables_from(ptrs, minlen=3):
    """Runs of consecutive 4-byte slots that all point at functions -> list of [func, ...]."""
    ptrs.sort()
    out, run, last = [], [], None
    for a, t in ptrs:
        if last is not None and a == last + 4:
            run.append(t)
        else:
            if len(run) >= minlen:
                out.append(run)
            run = [t]
        last = a
    if len(run) >= minlen:
        out.append(run)
    return out


# ---------------------------------------------------------------- Wii U
def load_wiiu(path):
    data = open(path, "rb").read()
    (shoff,) = struct.unpack_from(">I", data, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from(">HHH", data, 0x2E)
    secs = []
    for i in range(shnum):
        name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from(
            ">IIIIIIIIII", data, shoff + i * shentsize)
        raw = data[off:off + size] if typ != 8 else b""
        if flags & 0x08000000 and raw:
            raw = zlib.decompress(raw[4:])
        secs.append(dict(name=name, type=typ, addr=addr, raw=raw, link=link, info=info))
    shstr = secs[shstrndx]["raw"]
    for s in secs:
        s["nm"] = shstr[s["name"]:shstr.find(b"\0", s["name"])].decode()
    sec = {s["nm"]: s for s in secs}
    symsec = sec[".symtab"]
    strtab = secs[symsec["link"]]["raw"]
    syms, funcs = [], {}
    for o in range(0, len(symsec["raw"]), 16):
        st_name, value, size, info, other, shndx = struct.unpack_from(">IIIBBH", symsec["raw"], o)
        nm = strtab[st_name:strtab.find(b"\0", st_name)].decode("latin1") if st_name else ""
        syms.append(value)
        if info & 0xF == 2 and nm and value not in funcs:
            funcs[value] = (size, nm)
    text = sec[".text"]
    # flat readable image of .rodata + .data for string / float reads
    rod, dat = sec[".rodata"], sec[".data"]

    def read(addr, n):
        for s in (rod, dat, text):
            if s["addr"] <= addr < s["addr"] + len(s["raw"]):
                o = addr - s["addr"]
                return s["raw"], o
        return None, None

    starts = sorted(funcs)
    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        if i >= 0 and a < starts[i] + max(funcs[starts[i]][0], 4):
            return starts[i]
        return None

    feats = collections.defaultdict(collections.Counter)
    gref = collections.defaultdict(list)
    calls = collections.defaultdict(list)
    rela = sec[".rela.text"]["raw"]
    tw = text["raw"]
    for o in range(0, len(rela), 12):
        r_off, r_info, r_add = struct.unpack_from(">IIi", rela, o)
        typ, si = r_info & 0xFF, r_info >> 8
        tgt = (syms[si] + r_add) & 0xFFFFFFFF
        f = owner(r_off)
        if f is None:
            continue
        if typ == 10:  # R_PPC_REL24: bl / b
            if tgt in funcs and tgt != f:
                calls[f].append(tgt)
            continue
        if tgt in funcs:
            feats[f][("fp", None)] += 0  # function pointer refs are matched via the graph, not as features
            continue
        buf, bo = read(tgt, 1)
        if buf is None:
            if typ in (4, 109) and dat["addr"] <= tgt < 0x16000000:   # .bss / .ipc_smem
                gref[f].append(tgt)
            continue
        op = None
        if typ in (4, 109):  # ADDR16_LO / EMB_SDA21 sit on the instruction that uses the address
            io = (r_off & ~3) - text["addr"]
            if 0 <= io < len(tw):
                op = struct.unpack_from(">I", tw, io)[0] >> 26
        if op in (48, 49, 52, 53, 50, 51, 54, 55):
            if op in (48, 49, 52, 53) and bo + 4 <= len(buf):
                k = fkey(struct.unpack_from(">f", buf, bo)[0])
            elif bo + 8 <= len(buf):
                k = fkey(struct.unpack_from(">d", buf, bo)[0])
            else:
                k = None
            if k:
                feats[f][k] += 1
            continue
        if typ == 6:  # the @ha half of a pair; the @l half carries the same target
            continue
        s = as_string(buf, bo)
        if s:
            feats[f][("s", s)] += 1
        elif typ in (4, 109) and tgt >= dat["addr"]:
            gref[f].append(tgt)
    for f in feats:
        feats[f].pop(("fp", None), None)
    # intra-module bl's carry no relocation: decode them (opcode 18, AA=0, LK=1)
    calls = collections.defaultdict(list)
    for io in range(0, len(tw) - 3, 4):
        ins = struct.unpack_from(">I", tw, io)[0]
        if ins >> 26 == 18 and ins & 3 == 1:
            li = ins & 0x03FFFFFC
            if li & 0x02000000:
                li -= 0x04000000
            pc = text["addr"] + io
            t = (pc + li) & 0xFFFFFFFF
            f = owner(pc)
            if f is not None and t in funcs and t != f:
                calls[f].append(t)
    # function-pointer tables in data (ADDR32 relocs to function starts, consecutive words)
    ptrs = []
    for nm in (".rela.data", ".rela.rodata"):
        rr = sec[nm]["raw"] if nm in sec else b""
        for o in range(0, len(rr), 12):
            r_off, r_info, r_add = struct.unpack_from(">IIi", rr, o)
            t = (syms[r_info >> 8] + r_add) & 0xFFFFFFFF
            if r_info & 0xFF == 1 and t in funcs:
                ptrs.append((r_off, t))
    return dict(funcs=funcs, feats=dict(feats), calls=dict(calls), tables=tables_from(ptrs), gref=dict(gref))


# ---------------------------------------------------------------- PC
def load_pc():
    import pefile
    pe = pefile.PE(DLL, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_BASERELOC"]])
    base = pe.OPTIONAL_HEADER.ImageBase
    img = pe.get_memory_mapped_image()
    funcs = {}
    for row in csv.DictReader(open(os.path.join(ROOT, "ghidra", "functions.csv"))):
        funcs[int(row["addr"], 16)] = (int(row["size"]), row["name"])
    starts = sorted(funcs)
    def owner(a):
        i = bisect.bisect_right(starts, a) - 1
        if i >= 0 and a < starts[i] + max(funcs[starts[i]][0], 1):
            return starts[i]
        return None
    text = next(s for s in pe.sections if s.Name.startswith(b".text"))
    t0, t1 = base + text.VirtualAddress, base + text.VirtualAddress + text.Misc_VirtualSize
    feats = collections.defaultdict(collections.Counter)
    gref = collections.defaultdict(list)
    for blk in pe.DIRECTORY_ENTRY_BASERELOC:
        for e in blk.entries:
            if e.type != 3:
                continue
            site = base + e.rva
            if not (t0 <= site < t1):
                continue
            f = owner(site)
            if f is None:
                continue
            tgt = struct.unpack_from("<I", img, e.rva)[0]
            if tgt in funcs or t0 <= tgt < t1:
                continue
            to = tgt - base
            if not (0 <= to < len(img)):
                continue
            r = e.rva
            modrm, op, b3, b4 = img[r - 1], img[r - 2], img[r - 3], img[r - 4]
            kind = None
            if (modrm & 0xC7) == 0x05:
                if op in (0xD8, 0xD9):
                    kind = "f"
                elif op in (0xDC, 0xDD):
                    kind = "d"
                elif b3 == 0x0F and b4 == 0xF3:
                    kind = "f"
                elif b3 == 0x0F and b4 == 0xF2:
                    kind = "d"
            if kind == "f":
                k = fkey(struct.unpack_from("<f", img, to)[0])
            elif kind == "d":
                k = fkey(struct.unpack_from("<d", img, to)[0])
            else:
                k = None
            if kind:
                if k:
                    feats[f][k] += 1
                continue
            s = as_string(img, to)
            if s:
                feats[f][("s", s)] += 1
            elif tgt >= 0x115d2000:
                gref[f].append(tgt)
    calls = {}
    hdr = re.compile(r"^// calls: (.*)$", re.M)
    D = os.path.join(ROOT, "decomp")
    for fn in os.listdir(D):
        head = open(os.path.join(D, fn), encoding="utf-8", errors="replace").read(4096)
        m = hdr.search(head)
        if m:
            calls[int(fn[:-2], 16)] = [int(x, 16) for x in m.group(1).split() if re.fullmatch(r"[0-9a-fA-F]+", x)]
    # call sites in code order (E8 rel32 landing exactly on a function start)
    seq = collections.defaultdict(list)
    tb = img[text.VirtualAddress:text.VirtualAddress + text.Misc_VirtualSize]
    i = tb.find(b"\xE8")
    while i >= 0 and i + 5 <= len(tb):
        site = t0 + i
        t = (site + 5 + struct.unpack_from("<i", tb, i + 1)[0]) & 0xFFFFFFFF
        if t in funcs:
            f = owner(site)
            if f is not None and t != f:
                seq[f].append(t)
        i = tb.find(b"\xE8", i + 1)
    ptrs = []
    for blk in pe.DIRECTORY_ENTRY_BASERELOC:
        for e in blk.entries:
            site = base + e.rva
            if e.type == 3 and not (t0 <= site < t1):
                t = struct.unpack_from("<I", img, e.rva)[0]
                if t in funcs:
                    ptrs.append((site, t))
    return dict(funcs=funcs, feats=dict(feats), calls=calls, seq=dict(seq), tables=tables_from(ptrs), gref=dict(gref))


# ---------------------------------------------------------------- matching
def demangle(n):
    """cfront/EDG (GHS) mangling -> 'Class::func' (params dropped). Plain C names pass through."""
    m = re.match(r"^(__ct|__dt|__\w+?|[A-Za-z_]\w*?)__(?=[0-9QFC])(.*)$", n)
    if not m:
        return n
    base, rest = m.group(1), m.group(2)
    base = {"__ct": "ctor", "__dt": "dtor"}.get(base, base)
    cls = []
    q = re.match(r"^Q(\d)_(.*)$", rest)
    if q:
        cnt, rest = int(q.group(1)), q.group(2)
    else:
        cnt = 1 if rest[:1].isdigit() else 0
    for _ in range(cnt):
        d = re.match(r"^(\d+)(.*)$", rest)
        if not d:
            break
        ln, rest = int(d.group(1)), d.group(2)
        cls.append(rest[:ln])
        rest = rest[ln:]
    return "::".join(cls + [base])


def align_gap(gp, gw, pf, wf, r, cons):
    """Order-preserving alignment of two unequal gaps by size + call consistency; keep tight, unambiguous pairs.
    cons(a, b): +1 a known callee of a maps into b's callees, -1 known callees exist but none agree, 0 unknown."""
    n, m = len(gp), len(gw)
    memo = {}
    def sim(a, b):
        if (a, b) in memo:
            return memo[(a, b)]
        d = abs(math.log(max(wf[b][0], 8) / (max(pf[a][0], 8) * r)))
        c = cons(a, b)
        v = None if d >= math.log(1.5) or c < 0 else 1.0 - d / math.log(1.5) + c
        memo[(a, b)] = v
        return v
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best = max(S[i + 1][j], S[i][j + 1])
            s_ = sim(gp[i], gw[j])
            if s_ is not None:
                best = max(best, s_ + S[i + 1][j + 1])
            S[i][j] = best
    out, i, j = [], 0, 0
    while i < n and j < m:
        s_ = sim(gp[i], gw[j])
        if s_ is not None and abs(S[i][j] - (s_ + S[i + 1][j + 1])) < 1e-9:
            # require that skipping this pairing costs something (otherwise the choice is ambiguous)
            if S[i][j] - max(S[i + 1][j], S[i][j + 1]) > 0.25 and pf[gp[i]][0] >= 24:
                out.append((gp[i], gw[j]))
            i, j = i + 1, j + 1
        elif S[i][j] == S[i + 1][j]:
            i += 1
        else:
            j += 1
    return out


def main():
    if os.path.exists(CACHE):
        W, P = pickle.load(open(CACHE, "rb"))
    else:
        W = load_wiiu(sys.argv[1] if len(sys.argv) > 1 else RPX)
        P = load_pc()
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        pickle.dump((W, P), open(CACHE, "wb"))
    print(f"wiiu: {len(W['funcs'])} funcs, {len(W['feats'])} with features, {sum(map(len, W['calls'].values()))} call edges")
    print(f"pc:   {len(P['funcs'])} funcs, {len(P['feats'])} with features, {sum(map(len, P['calls'].values()))} call edges")

    # graph (sets, both directions)
    def graph(calls):
        out = {f: set(c) for f, c in calls.items()}
        inn = collections.defaultdict(set)
        for f, cs in out.items():
            for c in cs:
                inn[c].add(f)
        return out, inn
    Wout, Win = graph(W["calls"])
    Pout, Pin = graph(P["calls"])

    nW = collections.Counter(k for c in W["feats"].values() for k in c)
    nP = collections.Counter(k for c in P["feats"].values() for k in c)
    def kw(k):
        return (1.0 if k[0] == "s" else 0.35) / max(nW[k], nP[k])
    idx = collections.defaultdict(list)
    for f, c in W["feats"].items():
        for k in c:
            if nP[k] and nW[k] <= 40:
                idx[k].append(f)

    def fscore(p, w):
        a, b = P["feats"].get(p), W["feats"].get(w)
        if not a or not b:
            return 0.0
        return sum(kw(k) for k in a if k in b)

    # ---- 1. anchors
    cand = {}
    for p, c in P["feats"].items():
        sc = collections.Counter()
        for k in c:
            for w in idx.get(k, ()):
                sc[w] += kw(k)
        if sc:
            cand[p] = sc.most_common(3)
    perW = collections.defaultdict(list)
    for p, lst in cand.items():
        for w, sc in lst:
            perW[w].append((sc, p))
    for w in perW:
        perW[w].sort(reverse=True)
    p2w, w2p, how = {}, {}, {}
    for p, lst in cand.items():
        w, s = lst[0]
        second = lst[1][1] if len(lst) > 1 else 0.0
        if perW[w][0][1] != p:
            continue
        rival = perW[w][1][0] if len(perW[w]) > 1 else 0.0
        if s >= 0.9 and s - max(second, rival) >= 0.4:
            p2w[p], w2p[w], how[p] = w, p, ("anchor", s)
    print(f"anchors: {len(p2w)}")

    # size ratio calibration
    def ratio():
        rs = sorted(W["funcs"][w][0] / max(P["funcs"][p][0], 1) for p, w in p2w.items() if P["funcs"][p][0] > 32)
        return rs[len(rs) // 2] if rs else 1.3
    r = ratio()
    print(f"median size ratio wiiu/pc: {r:.2f}")
    def size_ok(p, w, tol=2.5):
        sp, sw = max(P["funcs"][p][0], 8), max(W["funcs"][w][0], 8)
        return abs(math.log(sw / (sp * r))) <= math.log(tol)

    wslot = collections.defaultdict(list)
    for ti, wt in enumerate(W["tables"]):
        for j, y in enumerate(wt):
            wslot[y].append((ti, j))
    print(f"pointer tables: pc {len(P['tables'])}, wiiu {len(W['tables'])}")

    # ---- 2+3. propagate until stable
    for rnd in range(400):
        added = 0
        votes = collections.defaultdict(float)
        for p, w in list(p2w.items()):
            for Pn, Wn in ((Pout, Wout), (Pin, Win)):
                cp = [x for x in Pn.get(p, ()) if x not in p2w and x in P["funcs"]]
                cw = [x for x in Wn.get(w, ()) if x not in w2p]
                if not cp or not cw or len(cp) * len(cw) > 400:
                    continue
                bonus = 1.5 if len(cp) == 1 and len(cw) == 1 else 1.0
                for a in cp:
                    for b in cw:
                        if size_ok(a, b):
                            votes[(a, b)] += bonus
            # call-order alignment: one unknown callee between the same two known ones on both sides
            sp, sw = P["seq"].get(p, ()), W["calls"].get(w, ())
            if sp and sw:
                pos = {}
                for j, x in enumerate(sw):
                    pos.setdefault(x, j)
                fixed = [(-1, -1)]
                for i, x in enumerate(sp):
                    j = pos.get(p2w.get(x, -1))
                    if j is not None and j > fixed[-1][1]:
                        fixed.append((i, j))
                fixed.append((len(sp), len(sw)))
                for (i0, j0), (i1, j1) in zip(fixed, fixed[1:]):
                    up = {x for x in sp[i0 + 1:i1] if x not in p2w}
                    uw = {x for x in sw[j0 + 1:j1] if x not in w2p}
                    if len(up) == 1 and len(uw) == 1:
                        a, b = next(iter(up)), next(iter(uw))
                        if size_ok(a, b, 3.0):
                            votes[(a, b)] += 1.5
        # pointer tables: same slot order on both sides
        for pt in P["tables"]:
            shifts = collections.Counter()
            bad = collections.Counter()
            for i, x in enumerate(pt):
                if x in p2w:
                    for (ti, j) in wslot.get(p2w[x], ()):
                        shifts[(ti, j - i)] += 1
            for (ti, sh), n in shifts.items():
                wt = W["tables"][ti]
                if n < 2 and not (n == 1 and len(wt) == len(pt) and sh == 0):
                    continue
                pairs = [(x, wt[i + sh]) for i, x in enumerate(pt) if 0 <= i + sh < len(wt)]
                if any(x in p2w and p2w[x] != y for x, y in pairs):
                    continue
                for x, y in pairs:
                    if x not in p2w and y not in w2p and x in P["funcs"] and size_ok(x, y, 3.0):
                        votes[(x, y)] += 1.5
        # globals: map PC globals -> Wii U globals from matched pairs (same distinct-ref order), then use
        # mapped globals like strings for unmatched functions
        gv = collections.defaultdict(collections.Counter)
        for p, w in p2w.items():
            gp = list(dict.fromkeys(P["gref"].get(p, ())))
            gw = list(dict.fromkeys(W["gref"].get(w, ())))
            if gp and len(gp) == len(gw) <= 40:
                for a, b in zip(gp, gw):
                    gv[a][b] += 1
        gmap = {}
        for a, c in gv.items():
            (b, n), *rest = c.most_common(2)
            if n >= 2 and (not rest or rest[0][1] * 3 <= n):
                gmap[a] = b
        gW = collections.defaultdict(list)
        for w, refs in W["gref"].items():
            if w not in w2p:
                for g in set(refs):
                    gW[g].append(w)
        for p, refs in P["gref"].items():
            if p in p2w or p not in P["funcs"]:
                continue
            keys = {gmap[g] for g in refs if g in gmap}
            sc = collections.Counter()
            for g in keys:
                ws = gW.get(g, ())
                if 0 < len(ws) <= 20:
                    for w in ws:
                        sc[w] += 1.0 / len(ws)
            for w, v in sc.items():
                if v >= 0.5 and size_ok(p, w):
                    votes[(p, w)] += 1.5 * v
        tot = collections.defaultdict(float)
        for (a, b), v in votes.items():
            tot[(a, b)] = v + fscore(a, b)
        byP, byW = collections.defaultdict(list), collections.defaultdict(list)
        for (a, b), v in tot.items():
            byP[a].append((v, b))
            byW[b].append((v, a))
        for a, lst in byP.items():
            lst.sort(reverse=True)
            v, b = lst[0]
            v2 = lst[1][0] if len(lst) > 1 else 0.0
            wl = sorted(byW[b], reverse=True)
            if wl[0][1] != a:
                continue
            vw2 = wl[1][0] if len(wl) > 1 else 0.0
            if v >= 1.5 and v - max(v2, vw2) >= 1.0 and a not in p2w and b not in w2p:
                p2w[a], w2p[b], how[a] = b, a, ("graph", v)
                added += 1
        # layout gaps
        def cons(a, b):
            known = [p2w[c] for c in Pout.get(a, ()) if c in p2w]
            if not known:
                return 0
            wc = Wout.get(b, ())
            hit = sum(1 for x in known if x in wc)
            return 1 if hit else (-1 if len(known) >= 1 else 0)
        lay = 0
        Ps = sorted(P["funcs"])
        Ws = sorted(W["funcs"])
        pa = sorted(p2w)
        for i in range(len(pa) - 1):
            p1, p2 = pa[i], pa[i + 1]
            w1, w2 = p2w[p1], p2w[p2]
            if w2 <= w1:
                continue
            gp = Ps[bisect.bisect_right(Ps, p1):bisect.bisect_left(Ps, p2)]
            gw = Ws[bisect.bisect_right(Ws, w1):bisect.bisect_left(Ws, w2)]
            if not gp or not gw or len(gp) > 30 or len(gw) > 45:
                continue
            if any(x in p2w for x in gp) or any(x in w2p for x in gw):
                continue
            if len(gp) == len(gw) and all(size_ok(a, b, 2.0) for a, b in zip(gp, gw)):
                for a, b in zip(gp, gw):
                    p2w[a], w2p[b], how[a] = b, a, ("layout", 0.5)
                    lay += 1
                continue
            for a, b in align_gap(gp, gw, P["funcs"], W["funcs"], r, cons):
                p2w[a], w2p[b], how[a] = b, a, ("gapdp", 0.5)
                lay += 1
        r = ratio()
        print(f"round {rnd}: +{added} graph, +{lay} layout -> {len(p2w)}")
        if not added and not lay:
            break

    # ---- output
    conf = {"anchor": 0.95, "graph": 0.85, "layout": 0.75, "gapdp": 0.6}
    cnt = collections.Counter(h[0] for h in how.values())
    with open(os.path.join(A, "wiiu_matches.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["pc_addr", "wiiu_addr", "wiiu_symbol", "name", "method", "score", "pc_size", "wiiu_size"])
        for p in sorted(p2w):
            w = p2w[p]
            wr.writerow([f"{p:08x}", f"{w:08x}", W["funcs"][w][1], demangle(W["funcs"][w][1]), how[p][0],
                         f"{how[p][1]:.2f}", P["funcs"][p][0], W["funcs"][w][0]])
    # size-only gap alignments (~75% right by spot check) go to a weaker file merged below agent names
    fs = {k: open(os.path.join(A, fn), "w", encoding="utf-8")
          for k, fn in (("strong", "wiiu_names.jsonl"), ("weak", "wiiu_names_weak.jsonl"))}
    if True:
        for p in sorted(p2w):
            w = p2w[p]
            sym = W["funcs"][w][1]
            f = fs["weak" if how[p][0] == "gapdp" else "strong"]
            f.write(json.dumps({"addr": f"{p:08x}", "name": demangle(sym), "confidence": conf[how[p][0]],
                                "purpose": f"Wii U symbol {sym} @ {w:08x} ({how[p][0]})", "subsystem": ""}) + "\n")
    for f in fs.values():
        f.close()
    print(f"matched {len(p2w)} / {len(P['funcs'])} PC functions:", dict(cnt))


if __name__ == "__main__":
    main()
