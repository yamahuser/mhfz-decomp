"""Feeds the hub with analysis work from the decompiled functions and collects the answers. Safe to stop/restart anytime.

Pass 1 (tier bulk)  : name + summarise each function, ordered by call depth from the main loop (0x108e3f00) so the
                      code that matters for the 60fps/render-update split gets named first.
Pass 2 (tier review): a stronger model (codex first) re-checks the shallow, important functions.
Outputs (all under ../analysis): names.jsonl, reviews.jsonl, failed.jsonl, state.json, progress.json.
NOTHING here edits the binary or the Ghidra project: names are *suggestions* from small models, to be verified.
"""
import json, re, subprocess, time, traceback
from collections import deque
from pathlib import Path

ROOT = Path(__file__).parent
BASE = ROOT.parent
DECOMP = BASE / "decomp"
OUT = BASE / "analysis"
OUT.mkdir(exist_ok=True)
QUEUE, DONE, RUNNING = ROOT / "queue", ROOT / "done", ROOT / "running"
ARCHIVE = ROOT / "done_archive"
ARCHIVE.mkdir(exist_ok=True)
ROOTS = ["108e3f00", "1000a2f0"]          # update+render entry, frame limiter
TARGET_QUEUED = 80                         # keep this many tasks waiting/running
MAX_C_CHARS = 7000
REVIEW_DEPTH, REVIEW_MAX, REVIEW_INFLIGHT = 8, 3000, 10   # depth<=2 (41 fns) was exhausted at 02:35; depth<=4 ~ 170
REVIEW_MIN_CALLERS = 40   # also review widely called functions (main-loop reachable set is only ~411 fns; vtable calls are not followed)
MARBLE = ["ssh", "-i", str(Path.home() / ".ssh" / "marble_ed25519"), "-o", "BatchMode=yes", "ayman@192.168.1.240"]
SYNC_EVERY = 300

info = {}              # addr -> {"bytes","callers","calls"}
indexed = set()
state_file = OUT / "state.json"
state = {"queued": [], "reviewed": [], "failed": [], "marble_final_sync": False}
if state_file.exists():
    state.update(json.loads(state_file.read_text()))
queued, reviewed, failed = set(state["queued"]), set(state["reviewed"]), set(state["failed"])
names = {}             # addr -> {"name","purpose","confidence"}
if (OUT / "names.jsonl").exists():
    for line in (OUT / "names.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            names[r["addr"]] = r
        except Exception:
            pass
depth = {}


def log(m):
    print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)


def save_state():
    state.update(queued=sorted(queued), reviewed=sorted(reviewed), failed=sorted(failed))
    state_file.write_text(json.dumps(state))


def index_new():
    n = 0
    for p in DECOMP.glob("*.c"):
        a = p.stem
        if a in indexed:
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                h1, h2 = f.readline(), f.readline()
            m = re.search(r"bytes=(\d+) callers=(\d+)", h1)
            info[a] = {"bytes": int(m.group(1)), "callers": int(m.group(2)),
                       "calls": h2.replace("// calls:", "").split()}
            indexed.add(a)
            n += 1
        except Exception:
            continue
    return n


def compute_depth():
    depth.clear()
    dq = deque()
    for r in ROOTS:
        if r in info:
            depth[r] = 0
            dq.append(r)
    while dq:
        a = dq.popleft()
        for c in info[a]["calls"]:
            if c in info and c not in depth:
                depth[c] = depth[a] + 1
                dq.append(c)


def load_c(addr):
    t = (DECOMP / f"{addr}.c").read_text(encoding="utf-8", errors="replace")
    return t[:MAX_C_CHARS] + ("\n// ...TRUNCATED..." if len(t) > MAX_C_CHARS else "")


def known_callees(addr):
    out = []
    for c in info[addr]["calls"]:
        n = names.get(c)
        if n and n.get("confidence", 0) >= 0.5:
            out.append(f"{c}={n['name']}")
    return ", ".join(out[:25]) or "none known yet"


NAME_PROMPT = """You are reverse engineering a 32-bit Windows C++ game client (Monster Hunter Frontier Z, MSVC, Direct3D 9, thiscall/x87).
Below is Ghidra decompiler output for the function at {addr}. Already-identified callees: {callees}.
Reply with ONLY one JSON object, no prose, no markdown:
{{"name": "snake_case_verb_noun", "purpose": "one or two sentences", "confidence": 0.0-1.0, "evidence": ["AT MOST 3 short items, each under 80 chars"], "category": "render|update|ui|net|file|memory|math|audio|input|crt|unknown"}}
Rules: use only evidence visible in the code. If you cannot tell what it does, set name to "unknown_{addr}" and confidence below 0.3. Never invent game features.

```c
{code}
```"""

REVIEW_PROMPT = """You are verifying a reverse-engineering annotation for a 32-bit Windows C++ game client (Monster Hunter Frontier Z).
Function {addr}. A small model proposed: name="{name}", purpose="{purpose}", confidence={conf}.
Callee names so far: {callees}.
Check the proposal against the decompiled code. Reply with ONLY one JSON object:
{{"verdict": "agree|revise|unclear", "name": "final_snake_case_name", "purpose": "corrected purpose", "confidence": 0.0-1.0, "struct_hints": ["offset/field guesses, e.g. this+0x14 is frame counter"], "notes": "anything that matters for splitting update from render"}}

```c
{code}
```"""


def enqueue(prefix, addr, prompt, tier):
    order = "0" if prefix == "review" else "1"      # hub claims files alphabetically: reviews first, never starved
    (QUEUE / f"{order}{prefix}_{addr}.json").write_text(
        json.dumps({"prompt": prompt, "tier": tier, "meta": {"addr": addr, "kind": prefix}}), encoding="utf-8")


def pending_count():
    return len(list(QUEUE.glob("*.json"))) + len(list(RUNNING.glob("*.json")))


def load_priority():
    """analysis/priority.txt: one address per line, named + Codex-reviewed first (edit freely; re-read each cycle)."""
    p = OUT / "priority.txt"
    return set(p.read_text().split()) if p.exists() else set()


def top_up():
    room = TARGET_QUEUED - pending_count()
    if room <= 0:
        return 0
    prio = load_priority()
    order = sorted((a for a in info if a not in queued and a not in names and len(a) == 8),
                   key=lambda a: (0 if a in prio else 1, depth.get(a, 99), -info[a]["callers"]))
    n = 0
    for a in order:
        if n >= room:
            break
        if info[a]["bytes"] < 12:
            queued.add(a)
            continue
        enqueue("name", a, NAME_PROMPT.format(addr=a, callees=known_callees(a), code=load_c(a)), "bulk")
        queued.add(a)
        n += 1
    return n


def queue_reviews():
    inflight = len(list(QUEUE.glob("0review_*.json"))) + len(list(RUNNING.glob("0review_*.json")))
    if len(reviewed) >= REVIEW_MAX or inflight >= REVIEW_INFLIGHT:
        return
    prio = load_priority()
    cands = sorted((a for a in names if a not in reviewed and (depth.get(a, 99) <= REVIEW_DEPTH or a in prio or info.get(a, {}).get("callers", 0) >= REVIEW_MIN_CALLERS)),
                   key=lambda a: (0 if a in prio else 1, depth.get(a, 99), -info.get(a, {}).get("callers", 0)))
    for a in cands[: REVIEW_INFLIGHT - inflight]:
        n = names[a]
        enqueue("review", a, REVIEW_PROMPT.format(addr=a, name=n["name"], purpose=n.get("purpose", ""),
                conf=n.get("confidence"), callees=known_callees(a), code=load_c(a)), "review")
        reviewed.add(a)


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:    # truncated by the token cap (endless 'evidence' list): salvage the leading fields
        nm = re.search(r'"name"\s*:\s*"([^"]+)"', text)
        if not nm:
            return None
        pu = re.search(r'"purpose"\s*:\s*"([^"]*)"', text)
        co = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
        ca = re.search(r'"category"\s*:\s*"([^"]+)"', text)
        return {"name": nm.group(1), "purpose": pu.group(1) if pu else "",
                "confidence": min(float(co.group(1)), 0.5) if co else 0.3,   # truncated answer: cap trust
                "category": ca.group(1) if ca else "unknown", "salvaged": True}
    if False:
        return None
    s = m.group(0)
    try:
        return json.loads(s)
    except json.JSONDecodeError:   # models emit stray backslashes (paths, \x00) and raw newlines inside strings
        s = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", s)
        return json.loads(s, strict=False)


def collect():
    got = 0
    for p in list(DONE.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            meta = r.get("meta") or {}
            addr, kind = meta.get("addr"), meta.get("kind")
            obj = parse_json(r["output"])
            if not obj or not addr:
                raise ValueError("no JSON in output")
            obj.update(addr=addr, backend=r["backend"], t=int(time.time()))
            if kind == "name":
                names[addr] = obj
                with open(OUT / "names.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(obj) + "\n")
            else:
                with open(OUT / "reviews.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(obj) + "\n")
                if obj.get("verdict") in ("agree", "revise") and obj.get("name"):   # reviewer name supersedes
                    names[addr] = {**names.get(addr, {}), "name": obj["name"], "purpose": obj.get("purpose", ""),
                                   "confidence": obj.get("confidence", 0.7), "addr": addr, "reviewed": True}
            got += 1
        except Exception as e:
            failed.add(p.stem.split("_", 1)[-1])
            with open(OUT / "failed.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"file": p.name, "error": str(e)[:200]}) + "\n")
        p.replace(ARCHIVE / p.name)
    # tasks the hub gave up on
    for p in list((ROOT / "failed").glob("*.json")):
        with open(OUT / "failed.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"file": p.name, "error": "hub: all backends failed"}) + "\n")
        p.replace(ARCHIVE / ("hubfail_" + p.name))
    return got


def sync_marble():
    """Pull marble's decompiled functions into ../decomp (tar over ssh, binary-safe via cmd pipe)."""
    done_flag = subprocess.run(MARBLE + ["test -f ~/mhfz/marble_done.flag && echo yes"], capture_output=True, text=True, timeout=60).stdout.strip()
    cmd = f'ssh -i "{MARBLE[2]}" -o BatchMode=yes ayman@192.168.1.240 "tar -cf - -C /home/ayman/mhfz decomp" | tar -xf - -C "{BASE}"'
    subprocess.run(cmd, shell=True, timeout=900, capture_output=True)
    if done_flag == "yes":
        state["marble_final_sync"] = True


def main():
    # retry everything that failed earlier (parser/codex-prompt bugs fixed); only keep "reviewed" if a review exists
    queued.difference_update(failed)
    failed.clear()
    done_reviews = set()
    if (OUT / "reviews.jsonl").exists():
        for line in (OUT / "reviews.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                done_reviews.add(json.loads(line)["addr"])
            except Exception:
                pass
    reviewed.intersection_update(done_reviews)
    log(f"feeder start: {len(names)} names so far")
    last_sync = 0
    while True:
        try:
            if not state["marble_final_sync"] and time.time() - last_sync > SYNC_EVERY:
                sync_marble()
                last_sync = time.time()
            new = index_new()
            if new:
                compute_depth()
            got = collect()
            added = top_up()
            queue_reviews()
            save_state()
            (OUT / "progress.json").write_text(json.dumps({
                "time": time.strftime("%Y-%m-%d %H:%M:%S"), "functions_decompiled": len(info),
                "reachable_from_main_loop": len(depth), "queued_total": len(queued), "named": len(names),
                "named_confident": sum(1 for n in names.values() if n.get("confidence", 0) >= 0.6),
                "reviewed": len(reviewed), "failed": len(failed), "pending_in_hub": pending_count(),
                "marble_final_sync": state["marble_final_sync"]}, indent=1))
            if new or got or added:
                log(f"indexed+{new} collected+{got} queued+{added} | named={len(names)} pending={pending_count()}")
        except Exception:
            log("feeder error: " + traceback.format_exc()[-500:])
        time.sleep(20)


if __name__ == "__main__":
    main()
