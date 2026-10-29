# Hub setup — what to paste and run

## 1. Permission rules (lets Claude start the hub and set up ollama on marble)
Add inside `"permissions": { "allow": [ ... ] }` in `C:\Users\Ayman\.claude\settings.json`
(the file has no "permissions" block yet, so add the whole block next to "theme"):

```json
"permissions": {
  "allow": [
    "PowerShell(powershell -File C:\\Users\\Ayman\\mhfz-60fps\\orchestrator\\start_hub.ps1)",
    "PowerShell(ssh -i * ayman@192.168.1.240 *)",
    "PowerShell(ollama *)",
    "PowerShell(gemini *)",
    "PowerShell(codex *)"
  ]
}
```
Narrow on purpose: nothing here lets Claude expose a service to the LAN. Ollama on marble stays on
localhost and the hub reaches it through an SSH tunnel (`ssh -L 11435:localhost:11434 ...`).

## 2. Logins (one-time, interactive — Claude can't type these for you)
| CLI | Command | Notes |
|---|---|---|
| Gemini | `gemini` | choose "Login with Google" (free tier) |
| Codex | `codex login` | sign in with your ChatGPT account. The ChatGPT desktop app is NOT the Codex CLI |
| Claude | already logged in | the hub's "claude" backend spends your Claude usage |

## 3. Start the hub
```
powershell -File C:\Users\Ayman\mhfz-60fps\orchestrator\start_hub.ps1
```
Drop a task into `queue\` as JSON: `{"tier": "bulk" | "critical", "prompt": "..."}`; results land in `done\`.
