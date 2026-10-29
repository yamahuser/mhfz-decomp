"""One process that keeps the marble tunnel, hub and feeder alive (restarts any that exit). Ctrl-C stops everything.
Run:  python -I supervisor.py        (logs: supervisor.log)
"""
import os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
KEY = str(Path.home() / ".ssh" / "marble_ed25519")
CMDS = {
    "hub": [sys.executable, "-I", str(ROOT / "hub.py")],
    "feeder": [sys.executable, "-I", str(ROOT / "feeder.py")],
}
procs = {}


def log(m):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {m}"
    print(line, flush=True)
    with open(ROOT / "supervisor.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


try:
    while True:
        for name, cmd in CMDS.items():
            p = procs.get(name)
            if p is None or p.poll() is not None:
                if p is not None:
                    log(f"{name} exited with {p.returncode}; restarting")
                out = open(ROOT / f"{name}.out.log", "a", encoding="utf-8")
                procs[name] = subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL)
                log(f"started {name} (pid {procs[name].pid})")
                if name == "tunnel":
                    time.sleep(3)
        time.sleep(5)
except KeyboardInterrupt:
    for p in procs.values():
        p.terminate()
    log("supervisor stopped")
