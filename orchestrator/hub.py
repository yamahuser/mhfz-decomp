"""Always-on task hub v2 (concurrent). Watches queue/, runs tasks on several AI backends at once.

Task file  queue/<id>.json : {"prompt": "...", "tier": "bulk"|"review"|"critical", "meta": {...}}
Result     done/<id>.json  : {"backend", "output", "attempts", "meta"}      (failed -> failed/<id>.json)
Health     status.json     : rewritten every few seconds

Routing = ordered *groups*. Inside a group the hub load-balances over whichever backend is free (so both
GPUs work in parallel). It only moves to the next group when every backend in the current one
is cooling down or failed this task. Paid/limited backends (copilot, agy, codex, claude) therefore sit in
later groups and only run when the free ones can't, or when a tier asks for them first.
Stdlib only. Started by start_all.ps1 (restarts it if it crashes).
"""
import json, os, re, shutil, subprocess, threading, time, traceback, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
QUEUE, RUNNING, DONE, FAILED = (ROOT / d for d in ("queue", "running", "done", "failed"))
for d in (QUEUE, RUNNING, DONE, FAILED):
    d.mkdir(exist_ok=True)

OLLAMA_HOSTS = {"ollama": ("http://localhost:11434", os.environ.get("HUB_OLLAMA_MODEL", "qwen2.5-coder:14b")),
                "marble": ("http://localhost:11435", os.environ.get("HUB_MARBLE_MODEL", "qwen2.5-coder:7b"))}  # 11435 = ssh tunnel to marble
TASK_TIMEOUT_S = 900
OLLAMA_TIMEOUT_S = 240       # a 14B answer takes ~10 s; anything past 4 min is a stuck generation
MARBLE_REST_S = 4
WORKERS = 14
SLOTS = {"ollama": 1, "marble": 1, "copilot": 2, "agy": 2, "codex": 2, "claude": 2}
sem = {b: threading.BoundedSemaphore(n) for b, n in SLOTS.items()}

TIERS = {   # lists of groups; see module docstring
    "bulk":     [["ollama", "marble", "copilot", "agy", "codex"]],   # user wants every agent working: one wide group
    "review":   [["codex", "copilot", "agy", "claude"], ["ollama", "marble"]],
    "critical": [["claude"], ["codex"], ["copilot"], ["agy"], ["ollama", "marble"]],
}
HARD_FAIL = re.compile(r"429|quota|rate.?limit|limit reached|unauthor|login|credit|not installed|auth|forbidden|402|403|401|refused|connection|timed? ?out", re.I)

lock = threading.Lock()
cooldown_until, consec_fail = {}, {}
stats = {b: {"ok": 0, "fail": 0, "last_error": None, "busy": 0} for b in SLOTS}


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with lock, open(ROOT / "hub.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_json(url, body=None, timeout=10, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_ollama(which, prompt):
    base, model = OLLAMA_HOSTS[which]
    body = {"model": model, "prompt": prompt, "stream": False, "keep_alive": "30m",
            "options": {"num_ctx": 8192, "temperature": 0.2, "num_predict": 700}}   # cap: stops runaway generations
    if model.startswith("qwen3"):
        body["think"] = False
    if which == "marble":
        # marble's sshd forbids TCP forwarding, so run curl *on* marble and feed the request over stdin
        p = subprocess.run(["ssh", "-i", str(Path.home() / ".ssh" / "marble_ed25519"), "-o", "BatchMode=yes",
                            "ayman@192.168.1.240", "curl -s --max-time %d http://127.0.0.1:11434/api/generate -d @-" % OLLAMA_TIMEOUT_S],
                           input=json.dumps(body), capture_output=True, text=True, encoding="utf-8",
                           timeout=OLLAMA_TIMEOUT_S + 30)
        if p.returncode != 0 or not p.stdout.strip():
            raise RuntimeError("marble connection failed: " + (p.stderr or "empty")[-200:])
        out = json.loads(p.stdout)
        if "response" not in out:
            raise RuntimeError("marble ollama: " + p.stdout[:200])
        time.sleep(MARBLE_REST_S)   # duty-cycle the GPU: user wants marble quiet (fan noise)
        return out["response"]
    return http_json(base + "/api/generate", body, timeout=OLLAMA_TIMEOUT_S)["response"]


def run_cli(cmd, prompt, stdin=False):
    """stdin=True feeds the prompt on stdin: npm .cmd shims on Windows truncate multi-line argv at the first newline."""
    exe = shutil.which(cmd[0])
    if not exe:
        raise RuntimeError(f"{cmd[0]} not installed / not on PATH")
    argv = [exe] + cmd[1:] + ([] if stdin else [prompt])
    p = subprocess.run(argv, capture_output=True, text=True, input=prompt if stdin else None,
                       stdin=None if stdin else subprocess.DEVNULL,
                       timeout=TASK_TIMEOUT_S, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not p.stdout.strip():
        # CLIs echo the prompt (decompiled code!) into stderr, so only keep short lines that look like errors,
        # otherwise words in the code ("auth", "401"...) falsely trip the quota detector.
        lines = [l.strip() for l in (p.stderr or "").splitlines()
                 if re.search(r"error|fail|limit|quota|unauthor|denied|exceeded|usage", l, re.I) and len(l) < 300]
        raise RuntimeError(" | ".join(lines[:3]) if lines else f"exit {p.returncode}, no clear error line ({len(p.stdout)} bytes out)")
    return p.stdout


BACKENDS = {
    "ollama": lambda p: run_ollama("ollama", p),
    "marble": lambda p: run_ollama("marble", p),
    "copilot": lambda p: run_cli(["copilot", "-s"], p, stdin=True),   # no --allow-all-tools: text-only
    "agy": lambda p: run_cli(["agy", "-p"], p),
    "codex": lambda p: run_cli(["codex", "exec", "--skip-git-repo-check", "-"], p, stdin=True),
    # springboard: spends Claude usage, only tier "critical" reaches it
    "claude": lambda p: run_cli(["claude", "-p", "--model", "sonnet"], p, stdin=True),
}


def cooling(b):
    return time.time() < cooldown_until.get(b, 0)


def record_failure(b, err):
    with lock:
        stats[b]["fail"] += 1
        stats[b]["last_error"] = err[:300]
        consec_fail[b] = consec_fail.get(b, 0) + 1
        if b in ("marble", "ollama"):          # local backends: ssh blips / one runaway generation are transient, never an hour
            cooldown_until[b] = time.time() + 60
        elif HARD_FAIL.search(err):
            cooldown_until[b] = time.time() + 3600
        elif consec_fail[b] >= 3:
            cooldown_until[b] = time.time() + 120
    log(f"{b} failed: {err[:140]}")


def try_group(group, task, attempts):
    """Run the task on one backend of the group; returns (backend, output) or None if the group is exhausted."""
    tried = set()
    while True:
        live = [b for b in group if b not in tried and not cooling(b)]
        if not live:
            return None
        for b in live:
            if sem[b].acquire(blocking=False):
                break
        else:
            time.sleep(0.5)       # everything usable is busy: wait for a slot
            continue
        try:
            out = BACKENDS[b](task["prompt"])
            with lock:
                stats[b]["ok"] += 1
                consec_fail[b] = 0
            return b, out
        except Exception as e:
            tried.add(b)
            attempts.append({"backend": b, "error": str(e)[:300]})
            record_failure(b, str(e))
        finally:
            sem[b].release()


def handle(path):
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
        attempts = []
        for group in TIERS.get(task.get("tier", "bulk"), TIERS["bulk"]):
            got = try_group(group, task, attempts)
            if got:
                result = {"backend": got[0], "output": got[1], "attempts": attempts, "meta": task.get("meta")}
                (DONE / path.name).write_text(json.dumps(result, indent=1), encoding="utf-8")
                path.unlink()
                return
        (FAILED / path.name).write_text(json.dumps({"attempts": attempts, "task": task}, indent=1), encoding="utf-8")
        path.unlink()
    except Exception:
        log("handle error: " + traceback.format_exc()[-400:])
        try:   # put it back so a hub crash/restart never loses work
            shutil.move(str(path), str(QUEUE / path.name))
        except Exception:
            pass


def health():
    h = {}
    for name, (base, model) in OLLAMA_HOSTS.items():
        if name == "marble":      # no tunnel; liveness is judged from task results
            h[name] = {"via": "ssh+curl", "model": model}
            continue
        try:
            ps = http_json(base + "/api/ps", timeout=3)
            h[name] = {"up": True, "model": model, "loaded": [m["name"] for m in ps.get("models", [])]}
        except Exception as e:
            h[name] = {"up": False, "error": str(e)[:100]}
    for b in ("copilot", "agy", "codex", "claude"):
        h[b] = {"installed": shutil.which(b) is not None}
    for b in SLOTS:
        h.setdefault(b, {}).update(stats[b])
        h[b]["cooldown_s"] = max(0, int(cooldown_until.get(b, 0) - time.time()))
    return h


def counts():
    return {d.name: len(list(d.glob("*.json"))) for d in (QUEUE, RUNNING, DONE, FAILED)}


def main():
    log(f"hub v2 started; {WORKERS} workers; ollama={OLLAMA_HOSTS['ollama'][1]} marble={OLLAMA_HOSTS['marble'][1]}")
    for p in RUNNING.glob("*.json"):          # recover tasks interrupted by a previous crash
        shutil.move(str(p), str(QUEUE / p.name))
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    inflight = set()
    last_status = 0
    while True:
        try:
            if time.time() - last_status > 5:
                (ROOT / "status.json").write_text(json.dumps(
                    {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "counts": counts(), "backends": health()}, indent=1))
                last_status = time.time()
            inflight = {f for f in inflight if not f.done()}
            room = WORKERS - len(inflight)
            if room > 0:
                for p in sorted(QUEUE.glob("*.json"), key=lambda q: (not q.name.startswith("review_"), q.name))[:room]:
                    try:
                        r = RUNNING / p.name
                        os.replace(p, r)       # claim
                    except OSError:
                        continue
                    inflight.add(pool.submit(handle, r))
        except Exception:
            log("hub loop error: " + traceback.format_exc()[-400:])
        time.sleep(1)


if __name__ == "__main__":
    main()
