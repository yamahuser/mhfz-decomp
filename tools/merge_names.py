"""Merge all function-name sources into analysis\\merged_names.csv.

Priority (best first): analysis\\wiiu_names.jsonl (real symbols, tools\\wiiumatch.py) > analysis\\mh2_names.jsonl >
analysis\\claude_names\\*.jsonl (agent-reviewed) > analysis\\reviews.jsonl (Codex) >
analysis\\names.jsonl (small models). Within a source the highest-confidence record per addr wins.
usage: python -I tools\\merge_names.py        -> prints coverage stats, writes analysis\\merged_names.csv
"""
import csv, glob, json, os, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, 'analysis')


def load(paths, tier, last_wins=False):
    best = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in open(p, encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            addr = str(o.get('addr', '')).lower().replace('0x', '').replace('fun_', '')
            name = o.get('name')
            if not addr or not name:
                continue
            conf = o.get('confidence')
            conf = float(conf) if isinstance(conf, (int, float)) else 0.0
            if last_wins or addr not in best or conf >= best[addr][0]:
                best[addr] = (conf, name, (o.get('purpose') or '').replace('\n', ' ')[:300], o.get('subsystem', ''), tier)
    return best


def main():
    srcs = [
        load([os.path.join(A, 'wiiu_names.jsonl')], 'wiiu'),  # real names from the unstripped Wii U build (tools\wiiumatch.py)
        load([os.path.join(A, 'mh2_names.jsonl')], 'mh2'),   # names carried over from the MH2 (PS2) decomp by tools\mh2match.py
        load(sorted(glob.glob(os.path.join(A, 'claude_names', '*.jsonl'))), 'agent', last_wins=True),
        load([os.path.join(A, 'wiiu_names_weak.jsonl')], 'wiiu-weak'),  # size-aligned Wii U names, ~75% right
        load([os.path.join(A, 'reviews.jsonl')], 'codex'),
        load([os.path.join(A, 'names.jsonl')], 'small'),
    ]
    merged = {}
    for s in reversed(srcs):          # lowest priority first, overwritten by better tiers
        merged.update(s)
    out = os.path.join(A, 'merged_names.csv')
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['addr', 'name', 'confidence', 'tier', 'subsystem', 'purpose'])
        for addr in sorted(merged):
            c, n, p, sub, t = merged[addr]
            w.writerow([addr, n, f'{c:.2f}', t, sub, p])
    tiers = collections.Counter(v[4] for v in merged.values())
    print(f'{len(merged)} functions named -> {out}')
    print('by tier:', dict(tiers))
    for tname, s in zip(('wiiu', 'mh2', 'agent', 'wiiu-weak', 'codex', 'small'), srcs):
        print(f'  {tname}: {len(s)} records, {sum(1 for v in s.values() if v[0] >= 0.7)} with conf>=0.7')


if __name__ == '__main__':
    main()

