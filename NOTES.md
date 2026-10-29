# MHF-Z 60fps — findings (handoff doc)

Client: `C:\Users\Ayman\Desktop\MHFZ\mhfo-hd.dll`, 32-bit, ImageBase 0x10000000,
SHA256 `CBFCAFB7FAF62E32C8B1FF751A96C6A4A6D1B97D6E2CD14F08C9F4EA0F044E82`.
The import table is intact, so the DLL is not packed and static analysis works directly.

## Frame limiter — `0x1000a2f0` (called once per frame from main loop @ `0x1000a5f4`)
- `0x1000a2fd  be 21 00 00 00  mov esi, 0x21` → base frame time **33 ms (~30 fps)**
- Alt path when `[0x11a9758c]!=0` and `word [[0x1e7fff3c]+0x14]==0x17b`:
  `esi = [0x11a97594] + 0x21` (`0x1000a31b  83 c6 21`); `[0x11a97594]` is an adaptive
  extra delay recomputed in the tail (0x1000a3bf..0x1000a408), probably network/sync pacing.
- `Sleep(last + esi - timeGetTime())`, then `last = timeGetTime()` stored at `[0x1e73ab40]`.
- Tail also keeps a wall-clock **60 Hz tick counter** at `[0x1e866c80]` (ms*3/50, remainder
  carried in `[0x1e73640c]`). Worth checking what reads it: it may already be real-time based.

## Main loop — around `0x1000a4f0..0x1000a650`
Single-threaded: RNG step (`[0x11a9a798]` LFSR), `call 0x108e3f00` (likely update+render),
then the limiter. There is no delta-time scaling, so logic is almost certainly per-frame.
- `0x1158ccb0` is called with (ptr, size) pairs before and after the frame
  (`0x1dc6b750`/0x1050, `[0x1e7fff3c]`/0x3ee0, `[0x1e8001ec]`/0xd40) and compared → sets bit 0 of
  `[0x1e7fff2e]` on mismatch. Looks like an anti-tamper checksum on **data** regions. It is not
  known whether `.text` is checksummed anywhere.

## Test build
`tools\make_patch.py` byte-verifies, then patches both sites to N ms (default 16):
- file off `0x96fd`: `be21000000` → `be10000000`
- file off `0x971b`: `83c621` → `83c610`
Output: `build\mhfo-hd.60fps.dll`. Install/undo: `swap.ps1 test` / `swap.ps1 restore`.

## Community leads (from Codex research, see codex_research_report.md)
- suzaku01/FZ-60FPS-Patch on GitHub: an existing 60fps patch? Not yet verified.
- mhfz-overlay reads the quest timer at mhfo-hd.dll+0xE7FE170 (VA 0x1E7FE170) in units of 1/30 s, which confirms frame-based logic.
- Mezeporta/Erupe docs/network_protocol.md lists decompiled dispatch handler addrs (e.g. FUN_114fb410 = CSync_man::putReceive_gacha_item).

## Rewrite project (decided 2026-10-12)
Hybrid re3/OpenRCT2-style: a C++ (32-bit, MSVC) injected DLL replaces functions one at a time.
Ghidra 12.1.4 is at C:\Users\Ayman\Tools\ghidra_12.1.4_PUBLIC; the project is in .\ghidra (mhfz.gpr), with the log in ghidra\analysis.log.
**Ghidra auto-analysis DONE (17 min, 2026-10-13).** Project: ghidra\mhfz, program `mhfo-hd.dll`.
- 48,284 functions, 21.0 MB of code. Only 763 have names, and those are switch cases (`caseD_*`).
- The only recovered C++ classes (23) are MSVC CRT/STL ones. The game's own classes have no RTTI, so there are no class names to recover. Names like `CSync_man` must come from debug strings, so search for strings next.
- Exports: ghidra\functions.csv (addr,size,name,callers), ghidra\classes.txt. Script: ghidra\scripts\ExportFunctions.java.
- Main loop is FUN_1000a4c0 (1232 B); the frame limiter is FUN_1000a2f0 (456 B). The largest functions are about 44 KB (FUN_10cf8f20), likely giant switch/state machines.
- Re-run scripts headless: analyzeHeadless ghidra mhfz -process mhfo-hd.dll -noanalysis -scriptPath ghidra\scripts -postScript <X>.java

VS 2022 Build Tools: the install was cancelled at the UAC prompt (0x8013153B); it needs a retry with the user present.

## Overnight analysis pipeline (built 2026-10-13) — READ THIS FIRST in a new session
**State:** Ghidra analysis done; ALL functions decompiled to `decomp\<addr>.c` (47,386 of 47,390 eligible; ≥24 bytes;
header line 1 = `// addr bytes callers`, line 2 = `// calls: <addr>...`). Reverse-engineering notes only — never redistribute.
Sharded by `ghidra\scripts\DecompileShard.java` (12 shards: PC ran 0-9 via `run_worker_pc.ps1`, marble ran 10-11 via
`run_worker_marble.sh`; project copied to marble `~/mhfz`, needs `JAVA_TOOL_OPTIONS=-Duser.name=Ayman`).

**Services** (all in the app's Terminal panel; start: `python -I orchestrator\supervisor.py`; keep PC awake: `orchestrator\keepawake.ps1`):
- `orchestrator\hub.py` — concurrent task hub (8 workers). Queue `orchestrator\queue\*.json` -> `done\` / `failed\`; health in `status.json`.
  Backends: ollama (PC, qwen2.5-coder:14b), marble (qwen2.5-coder:7b via `ssh marble curl` — marble sshd forbids TCP forwarding),
  codex (`exec -`, prompt via STDIN — .cmd shims truncate multi-line argv), copilot, agy, claude.
  Tiers: bulk = [ollama,marble] then copilot, agy, codex; review = codex first; critical = claude first (feeder never uses critical, to save Claude usage).
- `orchestrator\feeder.py` — indexes decomp, BFS call-depth from main loop `108e3f00` + limiter `1000a2f0`, queues naming tasks
  (shallow first), collects answers, queues Codex review pass for depth<=2 (max 150). Restartable; state in `analysis\state.json`.
**Outputs** (`analysis\`): `names.jsonl` (small-model suggestions, conf 0-1), `reviews.jsonl` (Codex verdicts + struct_hints + notes for the
update/render split), `progress.json`, `failed.jsonl`. Names are SUGGESTIONS from weak models — trust only conf>=0.6 and reviewed ones; verify against the binary.
**Bridge to Ghidra (built 09:36, NOT yet applied):** `python orchestrator\export_names.py [min_conf]` -> `analysis\ghidra_names.csv` (addr,name,confidence,source; Codex-reviewed names win; `ai_` prefix; ~6.9k names at conf>=0.6); then headless on a COPY of the project: `analyzeHeadless <copyDir> mhfz -process mhfo-hd.dll -noanalysis -scriptPath ghidra\scripts -postScript ApplyNames.java analysis\ghidra_names.csv` (renames only `FUN_*`, never overwrites existing names). Re-export as more names arrive.
**Next (old, partly done):** merge names/reviews into the Ghidra project (script to rename functions), then study `108e3f00` internals to split update from render.
VS 2022 Build Tools (MSVC 14.44) are now installed. Erupe server on marble (Docker) not set up yet.
Sandbox gotcha: Claude's PowerShell tool is sandboxed — npm -g installs from it don't reach the real system; use `run_in_terminal`.

## Per-frame function map (read from decomp 2026-10-13; D3D9 vtable indices from the standard IDirect3DDevice9 layout)
`FUN_1000a4c0` (1232 B, called from the main loop) is ONE FRAME, in this order:
1. copy 0x24cd4 bytes of state if `PTR_DAT_11a3ee2c != &DAT_1ed1ada0`; checksum bookkeeping (`FUN_1158ccb0` = checksum of a value, 4-slot rotating key `DAT_119dd770..774`; mismatches set bit 0 of `DAT_1e7fff2e` = anti-tamper flag).
2. **`FUN_108e3f00` — the logic tick** (385 B): RNG LFSR step, then calls `10b705b0`, `108f4150` (511 B, calls many draw-ish funcs: `1003f400` screen quads, `1002a6b0` render-target pairs — looks like UI/overlay drawing), `10887210`, `108176c0`, `115904c0` (file-I/O task pump, 868 B), `114dbcb0`, `10b42d40` (317 B -> `114dd030`,`115b4150`). Most of the actual game logic is probably reached via vtables/function pointers from here, not direct calls.
3. If rendering enabled (`_DAT_119dd74c & ~-(DAT_1e866c74!=0)`): `FUN_1002a760` = the render submit (lazily allocates a 0x210-byte object via `10029cb0`).
4. **`FUN_1000a2f0` — frame limiter** (33 ms; this is the 30 fps cap).
5. Re-verify checksums, accumulate wall-clock ticks `DAT_1e866c80` (60 Hz counter) into `DAT_1ecb1708`/`DAT_1e7fff34`, `GetClientRect`.
6. End of frame on the D3D9 device `DAT_1e811a3c`: vtable+0x44 = `Present`; vtable+0xac = `Clear(0,NULL,TARGET|ZBUFFER,color,z,0)` then `FUN_10029560`.
**Implication for 60fps:** tick (2) and render (3) run once per limiter wait (4), so logic is frame-locked. Real 60 fps = run the tick on every 2nd frame (or at 30 Hz via accumulator on `DAT_1e866c80`) and render every frame; without interpolating entity transforms in step 3 the extra frames are identical. Next: find where the camera/entity matrices are written inside the tick's callees (`10b42d40`, `108f4150`) to inject interpolation. Checksums: patching/hooking must keep step 1/5 consistent (they watch DATA regions, not .text — unverified for .text).
Small-model names for these (e.g. "initialize_game_state" for `10b705b0`) are NOT reliable; only Codex-reviewed names are.

### Codex-reviewed callees of the frame (analysis\reviews.jsonl; print with `python orchestrator\frame_reviews.py`)
LOGIC-TICK work (must stay at the original cadence — calling faster speeds the game up):
- `108176c0` update_stat_value_transitions: two timed value transitions (records stride 0x14 at `DAT_1e774b4c`, state==3 -> decrement ticks, linear interp start->target, clamp, lookup table). Pure per-tick state; Codex: running it at a higher rate accelerates the transitions.
- `1000a2b0` tick_countdown_and_invoke_expiry_callback: decrements `DAT_1e73d390`; at 0 calls vtable+0xa8 of `DAT_1e811a3c` (the D3D device object, so some device-level callback) if mask `_DAT_119dd74c` set and `DAT_1e866c74`==0.
- `115904c0` advance_queued_task_state: general task pump, 0x4c-byte task records (state at +0, callbacks/args, sync+overlapped file reads, worker thread dispatch). Not only file I/O.
- `10b705b0` one-shot init guarded by `DAT_1ed879f4` (counted down in step 2 and fires `1000a2b0` when it reaches 0); `114dbcb0` frees tracked allocations (list at `DAT_1e8175f4`, count `DAT_1e8175f0`).
RENDER work: `1002a760` draw_textured_fullscreen_quad (DrawPrimitiveUP triangle fan, sampler 5, this+0x2c RT, +0x30 depth, +0x34 inline verts stride 0x18; optional screenshot to file) — this is a post-process/fullscreen pass, not the world draw; `10029cb0` constructs its owner (nine helper objects + RT texture + depth surfaces); `108f4150` orchestrate_ui_frame_and_present (UI pass + present, lazily creates the shared 0x210 object).
PACING: `1000a2f0` also contains LATE-FRAME SKIPPING (flag `DAT_119dd750`; when late it clears `_DAT_119dd74c` — the render-enable mask — for up to 29 consecutive calls, so frames can be dropped while logic continues) and suspends/resumes a worker thread around the sleep. Consumers of `_DAT_119dd74c` are the key to separating render from logic: trace xrefs to it.
CHECKSUM: `1158ccb0` = seeded (0x6d68661a) buffer checksum with modes sub/add/xor; byte count arrives in EAX (non-standard convention). Anti-tamper watches data regions via this.
D3D DRAW SITES (03:35 grep of decomp for device vtable +0x148 DrawIndexedPrimitive / +0x14c DrawPrimitiveUP / +0x150 DrawIndexedPrimitiveUP): 633 call sites in 289 functions (densest: `1002bd10` x7, `1002c1f0` x5, `1001a1e0` x4, `1002e3c0` x4, `100fced0` x4; clusters at 1000da40..100108a0 and 1002ba80..1002f1e0). There is NO single world-draw function, so patching draw sites one by one is impractical. Better route for render interpolation: a D3D9 proxy/wrapper (hook `IDirect3DDevice9` SetTransform/SetVertexShaderConstantF/DrawPrimitive* and lerp world/view matrices between the last two logic ticks), plus the logic-rate change in the tick. VERIFIED 04:06 (device-vtable call sites in decomp, per function): SetTransform `+0xb0` in 9 fns (e.g. `1000b500` sets state 2=VIEW, 3=PROJECTION from `DAT_1e87ef90`/`DAT_1e87ef50`), SetVertexShaderConstantF `+0x178` in 26 fns, SetPixelShaderConstantF `+0x1b4` in 51 fns, SetVertexShader `+0x170` 43 fns, SetPixelShader `+0x1ac` 39 fns, SetFVF `+0x164` 28 fns. (An earlier note wrongly called +0x1ac SetVertexShaderConstantF; it is SetPixelShader.) So the game mixes fixed-function (view/proj via SetTransform in few places) with shader constants (26 fns) — a D3D9 proxy must lerp BOTH: SetTransform matrices and 4x4-looking blocks passed to SetVertexShaderConstantF. Start by logging them in a proxy to see what changes per tick. The global view/proj matrices `DAT_1e87ef90/ef50` are a cheap first target.
CAMERA GLOBALS (04:35, from xrefs in decomp): `DAT_1e87ef90` = global VIEW matrix (read by ~20 fns: 1000b500 SetTransform(2), 1000d4c0 inverse, 100150b0/10015280/10015450 TransformNormal, 1001a1e0 + 10029280 transpose-for-shader, 105eef80 Unproject; probable writers — functions that take its address as an out-param: 105e6cb0, 10b490c0, 10b8a210 (2 sites), 10b8f6f0, 10baee10). `DAT_1e87ef50` = global PROJECTION built by D3DXMatrixPerspectiveFovRH in `1043fec0`, `10b89f60`, `10b8a210`, `10baf300` (fov = `*(DAT_1edaad60+0xb8)`, aspect/near/far from `_DAT_119dd768`...). `1000c830` is a tiny getter returning either matrix. => Camera-only render interpolation = lerp/slerp `DAT_1e87ef90` (decompose position+rotation) between the last two logic ticks right before `1000b500`'s SetTransform and the shader-constant uploads (1001a1e0/10029280); objects/animation would still step at 30 Hz. 05:06 FINDING: `10b490c0` (331 B, 2 callers, sets up a scene/UI pass: calls `10baf1c0(0)`, `1000c7d0` x7, loops `10b49210` DAT_1e7ffb64 times) does `memcpy(&DAT_1e87ef90, &DAT_1dc6b710, 64)` — the VIEW matrix is COPIED from a source matrix at `DAT_1dc6b710`, which sits right next to the anti-tamper-checksummed state block (`0x1dc6b750`, 0x1050 bytes, see main-loop notes). So the camera pose lives in the game-state region; interpolate by lerping the source `DAT_1dc6b710` (or the copy) between ticks, and find who writes `DAT_1dc6b710` per tick (xrefs). Beware: writing into `0x1dc6b750+` triggers the checksum, but `0x1dc6b710` is 0x40 bytes BELOW that block (not covered, unverified).
05:35 xrefs of `DAT_1dc6b710` (only 5 fns by that exact symbol): COPIED into the view global by `10b490c0`, `10b8a210` (line ~1029, same function that builds PROJ) and `10baee10`; READ as a rotation matrix by `114dd030` (D3DXVec3TransformNormal — called from `10b42d40`, i.e. from the LOGIC TICK `108e3f00`) and `1136dd70` (float math using +0x00/+0x10/+0x20 columns). So it is the game's camera-orientation matrix used both by logic (camera-relative direction) and by rendering. Nobody writes it under that name, so it is written through a struct base/other alias (look at the symbols just below it, e.g. `DAT_1dc6b6xx`, and at who fills 16 floats before `10baee10`/`10b8a210` run). Implication: do NOT lerp the shared source in place (logic reads it); instead lerp only the render copy `DAT_1e87ef90` after the memcpy.
06:35 CAMERA MAP from the 56 Codex-reviewed priority fns (`python orchestrator\priority_summary.py`; all conf 0.8-0.97): the camera state struct is at pointer `DAT_1edaad60` (eye position vec3 at +0x80..+0x88, near clip +0xb0, far clip +0xb4, vertical FOV (radians) +0xb8). **`10baee10` refresh_camera_view_and_derived_transforms** is the real VIEW writer: repairs a degenerate target, rebuilds projection if a tracked param changed, builds a right-handed LookAt into `DAT_1e87ef90`, then refreshes derived matrices. `10b8a210` prepare_scene_render_state does the same per scene mode (mode selector `DAT_1e8004bc`, 0xff = special camera). Projection builders: `1043fec0`, `10b89f60`, `10baf300` -> `DAT_1e87ef50`. Uploads: `10029280` transposes and uploads view matrix to VS+PS constants (register 38) and a diagonal matrix (reg 42); `10015450` uploads lighting (regs 9,21-22,24-25). Consumers: `105e6cb0`/`105eef80`/`113cd340` unproject screen->world rays (picking), `10018d30` render_mesh_batches, `1001bc70` process_render_packet, `1136dd70` render_area_object_grid (0x8c-byte object records), `10bbe150` update_group_animation_and_transforms (group records stride 0x8c; advances delay/tick counters — TICK-RATE logic, applies position changes to indexed runtime objects).
=> REFINED CAMERA-INTERP PLAN: in the render path, hook `10baee10` (or the point just after its LookAt) and replace the eye/target/up with a lerp between the previous and current tick's camera (`DAT_1edaad60+0x80..`) using the real-time fraction since the last logic tick; keep `10b490c0`'s memcpy and logic reads of `DAT_1dc6b710` untouched. Objects/animation (`10bbe150` records, 0x8c stride) still tick at 30 Hz — their render positions would need the same previous/current lerp.
07:06 SCENE-LEVEL CALLERS of the camera/scene-setup fns (added to analysis\priority.txt for naming+review): `10b7b5c0` (658 B) calls BOTH `10b490c0` (scene setup/view copy) and `10b8a210` (prepare_scene_render_state) — likely the per-scene "begin render" routine, called from `1089cdb0`,`1089dd50`; `1080fe60` (564 B, no static callers => pointer/vtable-dispatched) and `1081fe90` (1 KB, 11 static callers) call `10baee10` (the LookAt writer) — candidates for the per-frame camera update; `10839260` (8.3 KB, no static callers, calls `10b42f90`...) and `10b81e30` (6.5 KB) are big scene/state handlers that reach `10bbe150`-style group animation. Functions with no static callers are the game's state-machine/vtable entry points — they're where the update/render split of each game state lives.
07:35 **THE UPDATE/RENDER SEAM (Codex-reviewed, conf 0.87):** `1080fe60` update_gameplay_phase_and_execute_render_passes (564 B, no static callers => dispatched): dispatches the current gameplay phase, does recurring slot / game-data / animation / camera updates (UPDATE, runs unconditionally), THEN conditionally runs render-state passes 2, optionally 4 and 3 (RENDER), then final processing and a conditional reset. Render is gated by `DAT_119dd74c != 0 && DAT_1e866c74 == 0 && DAT_1e866cb0 < 2` — the same mask the limiter's late-frame-skip clears. So the game ALREADY supports "tick without render" (frame skipping); a real 60 fps needs the opposite, "render without tick", i.e. call only the gated render block (and the Present path) on the in-between frames, with camera/object interpolation. `10b7b5c0` orchestrate_render_passes_and_restore_state = the render-pass runner (7 ordered stages 6,0,1,2,4,3,5; prepares scene state before stage 5; restores globals) — a clean hook target for an extra render-only invocation. `1081fe90` update_scripted_camera_controller: advances script channels, applies camera pose overrides/mode transitions, then refreshes camera transforms via `10baee10` = UPDATE work (don't repeat per render). `10b7acd0` run_game_frame_pipeline (1.8 KB; callers 1080fe60, 1089cb50, 10b7b570) mixes state and graphics ops — orchestrates the multi-phase frame; `10b81e30` render_character_model_parts (per-entity multipart model render, attachment transforms); `10839260` is a selection-screen state machine (input polling, countdowns, transitions), i.e. menu update logic.
=> To prototype: inject a DLL that, on odd frames, skips `1080fe60`'s update half and only runs the render block (needs the exact address range split inside 1080fe60 — disassemble it), lerps `DAT_1edaad60` camera and tracked entity transforms by alpha, and lets the limiter run at 16 ms. Risk: the render block may mutate state (cleanup helpers) — verify with a diff of globals across a render-only call.
08:06 **`1080fe60` EXACT STRUCTURE (read from decomp, 564 B, arg `param_1` = phase/state context; phase byte at `param_1+8`):**
 A) UPDATE (always runs): `switch(phase)` 0:`108103b0(p)` 1:`10810660` 2:(advance phase, clear `DAT_1ecb29df/29e4`, `10930e50`) 3:`10810bf0(p)` 4:`10812630` 5:`10812ad0`; then `for i<100: 10817a60(i,0)` (100 slot/entity updates); `10b8f330`; `108dea90`; **`10baee10` (camera view/LookAt refresh)**; `1154cd80`; `10b7acd0` (frame pipeline).
 B) RENDER block, gated by `(_DAT_119dd74c & ~-(DAT_1e866c74!=0)) != 0 && DAT_1e866cb0 < 2`: `114de7f0`; render-struct `DAT_1e3cbd64` fields (+0x10 = `DAT_119b8274`, +100 = 2, +0x88 = 0; `DAT_1ecb1704 = 0`); `1154cf40`; `114deb10`; `108f4460(2)` (= draw pass 2); then IF `DAT_1edba1bc && *(DAT_1edba1bc+0x15)`: pass 4 (+0x10=`DAT_119b73a8`, +100=4, `1000c7d0`, device `Clear(flags=2=ZBUFFER)` via vtable+0xac, `10b705e0`, `1154a080`, `114deb10`, `108f4460(4)`) and pass 3 (+0x10=`DAT_119b840c`, +100=3, `10990a20(0xbdb59f6c)`, `1154a190`, `114deb10`, `108f4460(3)`); finally `10b708f0`.
 C) TAIL (always): `10b7b4f0`; then if `DAT_1ed52870` and a per-slot byte != 1: reset (`10b738a0`, clear `*param_1`, etc.) = phase-end transition.
 => RENDER-ONLY frame = re-run `10baee10` with a LERPED camera, then block B verbatim (it only sets render-struct fields and calls draw helpers; the assignments are idempotent). Extra-frame hook: detour at the gate (`cmp/test` before `114de7f0`), or call B's body from a second thread-safe entry. Must still verify: `10b708f0`, `114de7f0`, `1154cf40` don't consume per-tick state (e.g. advance particle/anim counters). `108f4460(pass)` is the pass-draw routine (called with 2,4,3) — name/inspect it next.
 SIDE-EFFECT CHECK of block B helpers (Codex, 08:35): `114de7f0` = pure reset of the render-struct record at `DAT_1e3cbd64` (no calls/timing) -> SAFE to repeat; `10b708f0` process_pending_state_batches = drains up to 7 pending 0x14-byte batch slots and marks them processed -> a render-only repeat finds nothing pending (idempotent) but it IS state-consuming, keep it in the once-per-tick path; `1154cf40` = gated dispatcher by primary state byte + mode byte (callees unknown; no timing/drawing seen); **`108f4460(pass)` dispatch_active_entries_for_render_group = RISK**: scans 128 global entries for the group, calls a per-entry *state-transition helper* (`10992060`, once per matching entry incl. inactive) and dispatches up to 4 subentries via type-indexed callbacks (`10992170`) — if that helper advances animation/timers, running block B twice per tick would double-step them. Inspect `10992060` and `10992170` before trusting render-only repeats (added to priority.txt).
 RISK RESOLVED MOSTLY (Codex, 09:06): `10992060` = set_clipped_render_rectangle (clips x/y/w/h to global bounds, stores the rectangle in a global context; mutates render-rect state only — NOT a tick/animation step); `10992170` = apply_render_option_and_snapshot_state (reconciles render options, then copies six dwords `+0xC4..+0xD8` -> `+0xDC..+0xF0` of a global object; "no time advancement", but repeating it could overwrite a snapshot that something else expects from the *tick* — check who reads `+0xDC..+0xF0`). So block B is render-state work; the remaining unknown is the type-indexed callbacks `108f4460` dispatches (up to 4 subentries per active entry).
 **EXACT ADDRESSES (disasm of `mhfo-hd.dll`, saved `analysis\disasm_1080fe60.txt`; regenerate: `python tools\disasm.py <dll> 0x1080fe60 0x10810094`):** function prologue `1080fe60` (`esi=param_1`, `ebx=0` via `xor ebx,ebx` at `1080fe6e`); phase `switch` = `cmp ecx,5 / ja / jmp [ecx*4+0x10810094]` (jump table at `0x10810094`); UPDATE ends with `call 10b7acd0` at `1080fee9`. **Gate:** `1080feee a1 74 6c 86 1e mov eax,[1e866c74]` (exactly 5 bytes — a perfect `jmp rel32` detour site), `neg/sbb/not`, `1080fef9 test [119dd74c],eax ; je 10810047`, then `1080ff05 mov edi,2` and `1080ff0a cmp [1e866cb0],edi ; jge 10810047`. **RENDER BLOCK = `1080ff16` .. `10810042` (`call 10b708f0`)**, falling through to `10810047 call 10b7b4f0` (the tail). The block REQUIRES `ebx==0` and `edi==2` (edi=2 is reused as the pass-2 constant; `push edi` before `call 108f4460` at `10810039/3a`). Because the block ends by fall-through (not `ret`), a render-only invocation must either (a) copy `1080ff05..10810046` into a trampoline (fix up its 5 relative `call` rel32s and the 2 `je/jge` targets) and call it with ebx=0, edi=2, or (b) hook `10810047` with a flag that, on extra frames, returns to the caller after the block. Plan: detour `1080feee` -> our code that (1) runs the displaced `mov eax,[1e866c74]`, (2) lets the original path continue on logic frames.
 NEXT (concrete, superseded above): run `tools\disasm.py` on 0x1080fe60..+0x234 to get the gate instruction address + the byte pattern for a safe 5-byte detour; review `108f4460`, `10b708f0`, `114de7f0`, `1154cf40` for tick-state side effects.
(old NEXT) confirm which of the 'probable writers' compute the view (look for D3DXMatrixLookAtRH / multiply), then see how the camera pose itself is stored per tick.
=> Concrete 60 fps plan: keep `108e3f00`'s logic-tick work (108176c0, 1000a2b0, 115904c0...) on a 30 Hz accumulator; run render (`1002a760`/`108f4150` path + Present) every 16 ms; the world/entity draw (not yet located — it is not in these direct callees) needs transform interpolation. NEXT: find the 3D scene draw (look for D3D `DrawIndexedPrimitive` vtable+0x148 callers, and xrefs to `_DAT_119dd74c`).

## Expected result / next steps
- Most likely, the whole game runs at about 2× speed. That confirms the logic is tied to frames,
  so a real fix needs render/update decoupling plus interpolation.
- If it runs at normal speed and is smoother, the logic already reads a real-time clock
  (check the `[0x1e866c80]` readers).
- Next RE target: inside `0x108e3f00`, split update from render, then run update every 2nd
  frame at 16 ms. Animations and the camera would still hitch at 30 Hz without interpolation.

## Codex-reviewed callee findings for 1000a4c0 / 108e3f00 (pass 2026-10-13 ~01:40; from analysis\reviews.jsonl)
Classification for the update/render split (reviewed names only, conf>=0.9):
- **UPDATE (keep at 30 Hz; speeding up accelerates game time):** `108176c0` stat value transitions (lerp w/ remaining-tick counter, records stride 0x14 at `DAT_1e774b4c`); `10b42d40` delayed-action queue (32 entries x 0x20 at `0x1e7ff764`, countdowns per call); `1000a2b0` countdown `DAT_1e73d390` -> expiry vtable+0xa8 call; the countdowns inside `108e3f00` (`DAT_1e866c78`, `DAT_1ed879f4`).
- **MIXED (careful):** `108f4150` = UI frame orchestrator (updates + render + Present, 0x210 state obj `DAT_1e73d3c0`); preserve branch order, can't just call at 60 Hz. `10887210` = fixed render-state transition sequence gated on `DAT_1ed5291e != 0x80`.
- **RENDER:** `1002a760` (fullscreen textured quad, DrawPrimitiveUP fan, sampler 5, FVF 0x104), `10029cb0` is the one-time constructor of its owner (creates RT texture + depth surfaces; keep out of per-frame), `1002a6b0` RT/depth pair binding.
- **INFRA, leave alone:** `115904c0` task-state pump (not just file I/O; 0x4c-byte tasks, queue `DAT_1e866ce4`, active `DAT_1e879d40`), `114dbcb0` frees tracked allocs, `1158ccb0` seeded checksum (seed 0x6d68661a; modes 1 sub, 2 add, else XOR; EAX = length, nonstandard cc), `10b705b0` one-time init guard `DAT_1ed879f4`.
- **Limiter `1000a2f0`:** default 33 ms; late-frame skip clears `DAT_119dd74c` for up to 29 consecutive calls while timing continues; `DAT_1e866c80` is a nominal 60 Hz tick accumulator that does NOT itself run sim. Just changing 33->16 ms is unsafe. `DAT_119dd74c` is a "frame-processing eligibility" flag (render enable?) - trace its consumers next.
- `108e3f00` globals: LFSR `DAT_11a9a798` (mask 0x80200003) gated by `DAT_1e7ff240`; `DAT_1e811aee` wrapping byte tick counter; `DAT_1e811aed` status byte (1 or 5 from `114dbcb0`... reviewer flagged callee names as unreliable).
**Next RE step:** trace readers of `DAT_119dd74c` and `DAT_1e866c74`; inspect `114dd030` (called by the action queue) and `1002b430` (named update_position, unverified) for where entity transforms are written (interpolation hook point).

### Render-gate trace (pass 2026-10-13 ~02:30, from decomp grep)
- Effective render-enable expression, repeated in 129 functions: `(_DAT_119dd74c & ~-(DAT_1e866c74 != 0)) != 0`, i.e. render ON iff `119dd74c != 0` AND `1e866c74 == 0`. Limiter `1000a2f0` clears `119dd74c` on skipped (late) frames, so skipped frames already run logic without drawing. This is a ready-made hook: a "logic-only frame" = force the gate off for that frame.
- Sites using it (e.g. `10090d70`, `100fd760`, `1043eec0`) wrap D3D render-state changes behind a state cache `DAT_1ed5288c/8d` (only re-set when changed) - so the gate guards render-state/draw calls, not sim.
- `1000a260` = nested **BeginScene** (counter `DAT_1e73d390`++, vtable+0xa4 on `DAT_1e811a3c` when counter was 0 and gate on); `1000a2b0` = matching **EndScene** (vtable+0xa8 when counter hits 0). Confirms D3D9 vtable: 0xa4 BeginScene, 0xa8 EndScene, 0xac Clear, 0x44 Present.
- **Plan for 60 fps:** hook `1000a2f0` interval to 16 ms, and on every 2nd frame set `119dd74c` effective-off... NO - inverse needed: logic must run on 1 of 2 frames while render runs on both. Because the gate disables drawing (not logic) the cheap trick only gives 30 fps logic + skipped draws; for true 60 fps render need to skip the *tick* (`108e3f00`) on alternate frames and keep step 3 (`1002a760` submit) every frame, then interpolate transforms. Next: find who consumes transforms (view/world matrices) in the 129 gated sites.

### Pass 2026-10-13 ~03:20 - reviewed set grew to ~120
- Supervisor log: hub/feeder exit with -1 and get auto-restarted roughly hourly (hub 02:06, 03:06; feeder 01:25, 02:35); recovers fine, queue persists. Hub log also shows one marble "closed by remote host" ssh drop. Not fixed, harmless so far.
- Most reviewed draw funcs use PRETRANSFORMED screen-space quads (XYZRHW, FVF 0x104 / DrawPrimitiveUP): `1003f400` (11 quad entries, stride 0x44), `1000dec0` (colored quad), `1000e800` (textured quad), `1003f080` sprite draw by mode, `113aeb50` rect scale/center. => the renderer is largely 2D/sprite-like; interpolation targets are the quad POSITIONS (x/y passed to these), not world matrices.
- `11405950` dispatch_client_mode_and_update_render_camera_state (0.83): per-mode handler + camera update - inspect next as the update/render boundary candidate.
- Update-type found: `108f3e80` delayed vertical motion (displacement+velocity, per-tick), `114dd030` spatial sound request (listener-relative; called from action queue `10b42d40`), `113adce0` 11-slot callback table at `0x11aa0104` gated by `DAT_1e80db44+4` bits 0x1|0x8.

### Pass 2026-10-13 ~04:10
- **Fixed hub.py starvation:** queue was dispatched in filename order, so `review_*` (Codex) tasks sorted after all `name_*`/`1name_*` and starved (reviews stuck at 118 for 1h while ollama/marble kept naming). Dispatch now puts `review_` first (hub.py ~line 245). Takes effect on the next hub restart (it self-restarts ~hourly).
- `11405950` (166 B) = per-frame client mode dispatch: if `DAT_1e8e35a0==2` calls iface `DAT_1e8e3564` vtable +0xc/+0x14; then indirect call through table `PTR_LAB_11aa0574[DAT_1e8e35a0]` (the mode handler, indexed by mode); then if `1003f940()==0 && 113afda0()==0 && !(DAT_1e8e3598&1) && DAT_1e8119ec` -> `10b70630`, `114058d0`, `1000c7d0`, `10011280(&DAT_1e8119f0)`, `1000c7d0` (render/camera prep around the mode handler). Mode-handler table at 0x11aa0574 is a good entry to enumerate the game's per-mode update functions.

- 04:58: hub restarted manually (kill pid; supervisor respawns, running/ is recovered). Review-first dispatch confirmed live: codex ok=1 within seconds.

- 05:50 pass: healthy. named=5967/6030, reviews.jsonl=125 (codex slow: ~4 ok/50min, queue of review tasks is small - feeder caps at depth<=2/150). Marble had 1 transient ssh 'empty' failure. TODO next: dump the mode-handler table at 0x11aa0574 (needs Ghidra data read, grep of decomp finds only code refs; do NOT recurse into ghidra\ dir with Get-ChildItem - it is huge and times out).

### Pass 2026-10-13 ~06:45 - reviews 172, codex 58 ok (review-first dispatch works)
- **Correction to the 03:20 note:** the game DOES have real 3D. Reviewed: `10baee10` refresh_camera_view_and_derived_transforms (right-handed look-at; rebuilds projection on param change) = **primary interpolation hook for the camera**; `1043fec0` update_camera_perspective_projection, `10b89f60` configure_perspective_projection, `10b8a210` prepare_scene_render_state (mode-dependent camera coords + projection), `105e6cb0` unproject screen point -> world ray (picking), `1001a1e0` render_model_meshes (vertex/index buffers + matrix shader constants), `1001bc70` process_render_packet (matrix updates), `100150b0`/`10015280`/`10014c40` shader-constant uploads (lights etc).
- Per-tick update candidates (do NOT run at 60 Hz): `10bbe150` update_group_animation_and_transforms (0.68, tick counters + position changes = entity/anim transforms; interpolation target #2), `113545b0` update_object_depths (6 objects, wrapping counter), `10ab4df0` event-script exec w/ countdowns, `10b984e0` modal fade state, `10b98eb0` menu state machine.
- Plan: keep tick at 30 Hz; capture prev/curr camera (`10baee10` outputs) and `10bbe150` transforms, lerp for the in-between frame before `1001a1e0`/`1002a760` submit.

### Camera layout (pass 2026-10-13 07:35; from decomp `10baee10` + Codex struct_hints) - INTERPOLATION HOOK
`DAT_1edaad60` = pointer to the camera state. `FUN_10baee10` (929 B) runs per camera refresh and calls `D3DXMatrixLookAtRH(out, cam+0x80, cam+0x8c, cam+0x98)`:
- cam+0x80..0x88 eye vec3; cam+0x8c..0x94 look-at target vec3; cam+0x98..0xa0 up vec3; cam+0xa4..0xac cached (target-eye) direction (used to repair degenerate target).
- cam+0xb8 projection param (FOV?), cam+0xbc last-applied (change triggers `10baf300` rebuild); cam+0xc0 arg to `10baf460`.
- After LookAt: `10baead0`, `1000c7d0`, copies 64 B matrix `DAT_1e87ef90` -> `DAT_1dc6b710` (view matrix copy), then sets up audio/listener-ish orientation (`10005b20`, `108e4b90` angle, `10004c20` trig).
**60 fps plan:** per rendered frame, before `10baee10`'s LookAt, lerp eye/target (+0x80/+0x8c) between the previous-tick and current-tick snapshots (snapshot at tick start in `108e3f00` hook); restore real values after, so the 30 Hz sim never sees interpolated data. Callers: 3 (find them with the `// callers` header).

### Pass 2026-10-13 08:25 - callers of camera refresh `10baee10` (reviewed)
- `1080fe60` update_gameplay_phase_and_execute_render_passes (0.87): **the gameplay phase driver** - dispatches current phase, does slot/game-data/animation/camera updates, THEN runs render-state passes 2 (+optional 4) and 3, final processing. Update and render are interleaved in ONE function => the split point for 60 fps is inside it (after the camera/animation updates, before the render passes).
- `1081fe90` update_scripted_camera_controller (0.88): scripted/cutscene camera; advances 6 channels, applies pose overrides, calls `10baee10`. Camera is written here (the eye/target at cam+0x80/+0x8c) - snapshot prev/curr around this.
- `10839260` update_selection_screen_state_machine (0.68): menu screen, not gameplay.
- Next: read decomp `1080fe60.c` fully to locate the exact call boundary (update calls vs render passes 2/4/3) and who calls it from the mode table (`11405950` -> `PTR_LAB_11aa0574[mode]`).

### `1080fe60` read in full (pass 2026-10-13 09:17) - THE UPDATE/RENDER SPLIT POINT (564 B, 1 caller, arg `param_1` = phase record, `*(char*)(param_1+8)` = phase 0..5)
Order inside the function:
1. **UPDATE:** `switch(phase)` -> `108103b0`(0) / `10810660`(1) / advance-phase+`10930e50`(2) / `10810bf0`(3) / `10812630`(4) / `10812ad0`(5).
2. **UPDATE:** `for i in 0..99: 10817a60(i,0)` (100 slots/entities per tick), then `10b8f330`, `108dea90`, **`10baee10` (camera LookAt)**, `1154cd80`, `10b7acd0`.
3. **RENDER block**, guarded by `(_DAT_119dd74c & ~-(DAT_1e866c74!=0)) != 0 && DAT_1e866cb0 < 2`: `114de7f0`, then pass **2**: sets `*(DAT_1e3cbd64+0x10)=DAT_119b8274; +100=2; +0x88=0`, `1154cf40`, `114deb10`, `108f4460(2)`. If `DAT_1edba1bc && ->+0x15`: pass **4** (D3D `Clear` via vtable+0xac, `10b705e0`, `1154a080`, `114deb10`, `108f4460(4)`) then pass **3** (`10990a20(0xbdb59f6c)`, `1154a190`, `114deb10`, `108f4460(3)`). Then `10b708f0`.
4. **Post:** `10b7b4f0`; if `DAT_1ed52870` and slot condition on `DAT_1e7fff3c`: resets state (`10b738a0`, `*param_1=0`).
**60 fps design:** wrap step 3 only. Per 30 Hz tick run steps 1,2,4 once, then render block (3) TWICE per tick: frame A with interpolation factor 0.5 between the previous-tick and current-tick camera (+ entity transforms), frame B with factor 1.0 (pure current). Equivalent: split the function into `Update(param_1)` = 1,2,4 and `Render()` = 3 and call Render from the limiter loop. Render passes are indexed by `*(DAT_1e3cbd64+100)` = 2,4,3. `10baee10` must be re-run (or its LookAt only) per rendered frame with interpolated eye/target since it sits in the update half. Camera refresh also sets audio-listener-ish globals, so only redo the LookAt+matrix copy, not the whole function.

### Entity slot array (pass 2026-10-13 10:08) - from `10817a60` (120 B, per-slot update, called 100x by `1080fe60`)
- Slot stride **0x1050 bytes**, 100 slots, base `DAT_1dc6b750` (`slot = 0x1dc6b750 + i*0x1050`). Slot+0x00 = active byte, +0x01 = enabled byte, +0x10 (`DAT_1dc6b760`) = byte selecting path, +0x411 (`DAT_1dc6bb61`) = alt-path flag. Visible only when +0 and +1 non-zero (and a per-slot table flag at `PTR_DAT_11a5358c[i+0xa938]` when `*(DAT_1e7fff3c+0x23ff)!=0`).
- Per-slot update = `1081e6a0`, `1081e030`, `1081e250`, `1081e390` (normal path) or `1081eab0` (alt path). These are the functions that move entities: **interpolation snapshots for 60 fps = copy each active slot's position fields (find them inside these 4 callees) at tick start**. Next: read `1081e6a0`/`1081e030` for the position/rotation offsets within the 0x1050 slot.
- Camera view-matrix copy `DAT_1dc6b710` sits 0x40 bytes before slot 0: it is the header of the same global block (not an entity).

### Correction on the 100 slots (pass 2026-10-13 11:00; read `1081e6a0`, `1081e030`)
The 0x1050-byte slots at `DAT_1dc6b750` are **character/player records, not movers**: `1081e6a0`/`1081e030` read slot+0x690 / +0x694 (pointers to equipment/item records, `->+0x20` = level-ish short), +0x11 (class/type byte), +0x38e/+0x396/+0x398 (ids), cache them at +0xe64..+0xe78, and run per-item effect callbacks from table `PTR_FUN_118df2dc` indexed by `DAT_118dea08[id*0x14]` (item/skill effect table, stride 0x14). So they are stat/equipment/buff processing - **tick-rate logic, leave at 30 Hz; they hold no entity world position.** The positions to interpolate live elsewhere: look at what `10bbe150` (group animation/transforms) and the actor/model drawing path (`1001a1e0` render_model_meshes callers) read. Next: grep callers of `1001a1e0` and read the matrix source they use.

### Pass 2026-10-13 11:50 - actor draw path
- `10bbe150` (4502 B, 10 params incl. float `param_7` = blend/alpha weight, `param_1` = animation-group table, entries stride **0x8c**, per-group list stride 0x23 dwords): builds `D3DXMatrixTranslation` + per-bone/part transforms; only caller besides itself is `10b81e30`. With its many D3DX calls it looks like a **skeletal/part transform evaluator run per draw**, so it may live on the render side already (timed by a float weight rather than tick counters) - verify before treating as update.
- `1001a1e0` (render_model_meshes, 4144 B) has a single caller `10013440`. Trace upward: `10013440` -> `10b81e30`? Next: read `10b81e30` and `10013440` to see which side (update vs render half of `1080fe60`) they sit on, and where the per-actor world position/yaw is held.
- hub.py on disk was modified by something else since my edit but still has the review-first sort (line 246) and parses fine.

### Pass 2026-10-13 12:42 - actor render chain identified (render side)
Chain: `10b86ce0` (3656 B, 1 caller) -> `10b81e30` **render_character_model_parts** (Codex-reviewed, 6509 B, 4 callers: `10b7a240`, `10b86ce0`, `10b88470`) -> `10bbe150` (per-part transform/animation evaluator) -> `10013440` (4800 B generic mesh draw helper, **78 callers**, calls `1001a1e0` render_model_meshes + `1001bc70` process_render_packet; small-model name "update_render_state" is misleading) -> D3D.
- Entity struct (param_1 of `10b81e30`): +0x03 subtype, +0x0c id (-> render-pass id), +0x678 resource ptr, +0x680 model descriptor (+0x2c part count, +0x10/+0x30 part data, +0x44/+0x48 primary/alt part resources), **+0xf4 = attachment/transform object whose 4x4 matrix starts at +0x40** (this is the entity world matrix = interpolation target).
- Codex: visible evidence favors rendering/attachment prep, not simulation; but the supplied body was truncated - still must check it for time integration. `10bbe150` takes a float weight (param_7) -> animation pose is computed at DRAW time from an anim time/weight, so interpolating the anim time input (not the pose) may be enough for animation smoothness.
- So the actor path is largely already render-side; for 60 fps the work is: (a) lerp each entity's matrix at `entity->+0xf4->+0x40` between ticks (snapshot at tick, restore after draw), (b) feed anim time/weight a fractional tick. Next: find who WRITES `+0xf4->+0x40` during the tick (grep decomp for `+ 0xf4)` writes near `+ 0x40`), that is the transform-update function to hook for snapshots.

### Pass 2026-10-13 13:35 - caveat on entity `+0xf4`
Grep for writers of `+0xf4` is too noisy to answer directly (`+0xf4` is also a bit-flag word in other structs, e.g. `108f6200` ORs into `in_EAX+0xf0/0xf4`). In `10b83bb0` (9525 B, 3 callers; same 10b8xxxx render family) the entity's transform pointer is chosen by subtype: `param_3+3 in {4,6}` -> `*(param_3+0xf4)`, else `*(param_3+0xf8)`. So the matrix object pointer is `+0xf4` OR `+0xf8` depending on subtype byte `+3` - correct the earlier note. Writers of the matrix itself need a different approach: search for callers that store floats via `D3DXMatrix*` outputs into `(ptr + 0x40)`, or break on writes at runtime. Recommendation for next steps: stop static grepping for the transform source; instead build a tiny runtime probe (DLL/hook) once the project can launch the client, watch `ptr+0x40` writes per frame to see tick-vs-frame cadence directly. Static findings so far are enough to design the hook points (tick `1080fe60` steps 1-2 / render block 3, camera `10baee10`, entity matrix via `10b81e30`).

## GOAL REMINDER (user, 2026-10-13 ~14:00)
60 fps is only a milestone. The real goal is a **full rewrite of the game onto a new engine**. From now on, loop passes should favor engine-neutral subsystem documentation over patch-style hooks: (1) the game-state/update model (phase driver `1080fe60`, 100 character slots, event/script system `10ab4df0`, action queue `10b42d40`), (2) renderer contract (what each pass 2/3/4 draws, shaders/FVFs, the model/part/animation formats behind `10b81e30`/`10bbe150`/`10013440`), (3) data formats (task pump `115904c0` file loads, item/skill tables like `DAT_118dea08`), (4) input/UI/menus, (5) audio (`114dd030` spatial sound), (6) network layer (Erupe protocol). Keep a subsystem index here and record struct layouts in a form a new engine can reimplement.

## CURRENT FIRST GOAL (user, 2026-10-13 ~14:00) - supersedes the "new engine first" ordering
Milestone 1 = (a) get the **60 fps patch working in the real game** and (b) work out how to **inject HD upscaled textures and models for monsters**. The new-engine rewrite stays the long-term goal; spec work feeds both.
- (a) State: `build\mhfo-hd.60fps.dll` exists (limiter 33->16 ms, 2 patch sites). Not yet validated in game; per analysis the logic is frame-locked so expect ~2x speed. Real fix = split `1080fe60` update/render (see notes above) or tick logic every 2nd frame.
- (b) User history: years ago they packed HD textures into the model files and **the game crashed when loading the area with the monsters**. Hypotheses to test (likely 32-bit memory/size limits): fixed-size load buffers or pool sizes per file/entry; size/offset fields in archive headers or an index not updated after repacking; texture dimension/format/mip-count expectations (DXT vs RGBA, pow2); VRAM/32-bit address-space exhaustion when many HD textures load at once; per-model resource count or checksum validation; compression/encryption of the repacked data. Install layout: `dat\` has .pac (1899), .snd, .bin (1027), .mus, .gab, .snp, .txb (244), .mot (85, probably motion/animation). Agents are writing `spec\archive-format.md`, `spec\model-format.md`, `spec\animation-format.md`; next specs needed: texture format (.txb?) and the load-buffer sizing rules.

## HD texture injection - findings (2026-10-13 ~15:00) - Varusaburosu = em130
Tools: ReFrontier built from source at `thirdparty\ReFrontier` (exe: `ReFrontier\bin\Release\ReFrontier.exe`; built with msbuild + Crc32.NET 1.2.0 package + /p:AllowUnsafeBlocks=true). Workflow (all on COPIES in `work\em130`): `ReFrontier.exe X.pac -log -nonRecursive -close` -> folder + `X.pac.meta` (16-byte ECD header); `ReFrontier.exe folder -pack -close` -> `output\X.pac` (decrypted); copy the `.meta` next to it; `ReFrontier.exe output\X.pac -encrypt -close` -> installable pac.
- **Control tests passed:** unpack->pack->encrypt of em130-hd.pac is BYTE-IDENTICAL to the installed file (SHA256 2047D3DC...). Packing alone cannot cause the old crash.
- em130.pac (SD, 2.58 MB) = 6 parts; em130-hd.pac (HD, 5.74 MB) = 7 parts. Parts 3-6 are identical in both. Part1 = model container (2 sub-blobs; SD 170 KB vs HD 309 KB), **part2 = texture container** (u32 count, count*(u32 off,u32 size), blobs): SD has **8 PNGs at 256x256**, HD has **24 PNGs at 512x512** (all 8-bit indexed colour type 3; some are 1-bit indexed masks, e.g. texture 23). HD adds part 7 (3 KB, floats = matrix/constants). So textures are PLAIN PNGs; replacing them is easy; the game decodes them itself (gdiplus.dll ships in the install - unverified which decoder).
- Test packs (not installed) in `work\em130\tests\*\output\em130-hd.pac`: T1 (re-encode, identical to original), **T2** (texture 0 upscaled to 1024x1024, still 8-bit indexed, 5.78 MB), **T3** (all 8-bit textures upscaled to 1024, 6.92 MB; 1-bit mask left as is). Generator: `tools\mhf_texpack.py`. Install = back up `dat\emmodel-hd\em130-hd.pac`, copy test file over it.
- Interpretation of the user's old crash (entered monster area -> crash): consistent with loader limits on texture dimension/size or total container size. T2 vs T3 separates 'one big texture' from 'total memory/buffer'. Houmgaor's article (houmgaor.com/monster-hunter-frontier/decrypting-monster-hunter-frontier/) confirms the ECD 16-byte header (magic 'ecd', key byte, size, CRC32) and JKR header; nothing about asset size limits. Houmgaor also maintains a ReFrontier fork (github.com/Houmgaor/ReFrontier).

### Correction from animation spec agent (2026-10-13 ~15:30) - see spec\animation-format.md
- **`10bbe150` is NOT a skeletal evaluator** (my earlier note was wrong): it animates per-material/per-part effects (UV scroll, tint ramps, alpha ramps, eased offset/scale tracks), writes a 0x8c-byte slot record that `1000c390` uploads to the per-pass constant table at 0x11aa6af8; only D3DXMatrixTranslation/Scaling/Multiply/Vec3TransformNormal, no quaternions. Its frame counter advances at DRAW time (+1 per entity draw, first pass only) via entity draw callbacks `10b7b860/10b7ba30/10b7bbf0` -> `10b86ce0`/`10b88470` -> `10b81e30` -> `10bbe150`. For 60 fps make the counter tick-driven (30 Hz) and evaluate closed forms at a fractional frame.
- Formats solved (agent's analysis; unverified guesses marked in the spec): JKR types 3/4 decode (`tools\jkr.py`, `tools\pacwalk.py`); motion archive = 100-entry tables, motion id = group*100+index; per-bone tracks, 9 channel slots/bone (rot XYZ masks 0x08/0x10/0x20, trans XYZ 0x40/0x80/0x100); key = `s16 value,u16 frame,s16 tan_in,s16 tan_out`; skeleton em003 = 26 bones x 0x10c bytes (index,parent,first child,next sibling,scale vec4,bind quat,bind trans).
- **HD model replacement rule:** animation binds by bone INDEX, so a replacement mesh must keep the same bone count, order, hierarchy and bind translations (extra bones may be appended after the originals). Still undecoded: mesh format (skin weights, bone maps) and whether HD packs reuse the SD skeleton/motions. Skeletal clip sampler not found yet.

### Archive spec agent hand-back (2026-10-13 ~15:50) - see spec\archive-format.md, tools\mhf_archive.py
- Layers: optional ECD (stream cipher, key table read from the DLL; verified decrypt) -> optional JKR (types 3/4 decoded) -> pack table (u32 count, count*(u32 off,u32 size), entries back-to-back). **Loader returns early when magic is not ECD, so a PLAINTEXT pac with the same name should load as-is (read from code, untested in game)** - easiest injection route, no encryptor needed. ECD filename check value not reproducible: keep original names.
- Monster path (`108fba70`): tries `emmodel-hd\em%03d[_b|_c|_d|_e]-hd.pac` then falls back to `emmodel\em%03d[...].pac`.
- em001 entry layout: 0 mesh, 1 PNG textures set A (SD 4x256, HD 12x512), 2 motions, 3 second model, 4 textures set B, 5 config, 6 (HD only) 2297-byte material table. **Mesh and textures are a matched set (mesh materials index the texture list); entry 6 material table is validated against the mesh (group count == object count; per-group material count) - mismatch shows an 'Error' MessageBox naming the pac and discards data = strongest candidate for the user's old crash.** Pac loads into a fixed 14 MiB arena (0xE00000 at 0x1c404740) with no bounds check; texture slot ids: 72 per monster slot (set A base 0x5ed+slot*0x48, set B 0x631+slot*0x48).
- Note: our T2/T3 only change texture dims (not counts/materials), so they test the dimension/size hypothesis, not the material-table one. Next tests: (T4) change texture COUNT or add a texture without updating the material table; (T5) HD pac loaded plaintext (no ECD) to confirm the plaintext path.

## Naming swarm (started 2026-10-13 ~16:10)
User paused game testing (Rain launcher login blocked by network; texture tests T1-T3 wait) and asked for all hands on deck naming functions. 11 Claude subagents each own one address region (r1=0x10000000-0x101FFFFF ... r11=0x11400000-0x1159FFFF) and write `analysis\claude_names\rN.jsonl` + `spec\subsystems\rN_summary.md`. Background hub keeps running small models + Codex/Copilot/agy reviews. Merge everything with `python -I tools\merge_names.py` -> `analysis\merged_names.csv` (priority agent > codex > small). Next: a script to push merged names into the Ghidra project (rename functions).

### Model/mesh/texture spec agent hand-back (2026-10-13 ~17:00) - see spec\model-format.md, tools\mhfpac.py, tools\mhfmodel.py
- All 303 SD + 278 HD monster pacs decrypt/decompress cleanly. Parsers: ECD decrypt, JKR, PAC, fmod (chunk tree: u32 type,count,size; root children 0x20000, 2 meshes, 9 materials, 0xa texture descriptors), fskl, PNG; OBJ export.
- **Textures are decoded with D3DXCreateTextureFromFileInMemoryEx using the image's own size, 1 mip, no resize: ANY size works (DDS too). So my T2/T3 (1024px) are NOT expected to crash on dimension; they test the pipeline. The old crash is more likely one of the static limits below.**
- Limits read statically (none bounds-checked): decompressed fmod must be < 8 MiB (skeleton written at +8 MiB of a 14 MiB arena DAT_1ed528bc; largest official HD model 7.62 MB, em113_b-hd); texture slot holds 68 images in entry-1 array and 4 in entry-4 (official HD max 60) - extra images spill into the next slot; raw pac read into a 144 MiB static buffer (largest official pac 61 MB); per model slot: 64 meshes (official max 62), 32 bound materials/mesh (max 31), 63 palette bones/mesh, 4096 textures globally, 1280 model descriptors; 16-bit indices => < 65,536 vertices per mesh; entry 6 (HD material table) per-mesh material counts must match the fmod else Error box. Encrypted files with key index >= 4 must keep UPPER-CASE file name or loader rejects them; plaintext pac and JKR mode 0 (raw) are accepted (mod tools need no compressor/encryptor).
- HD vs SD: each material has up to 3 HD stages (diffuse, normal map, grey gloss/spec); em001 textures 4x256 -> 12x512 (3 per SD image), mesh 1477 -> 3656 vertices + tangents; HD meshes are re-exported with different numbering so SD geometry cannot mix with HD textures.
- Suggested confirming tests (pending game access): (T4) fmod padded >8 MiB via raw JKR mode 0; (T5) 70 images in entry 1; (T6) mismatched entry-6 material count; (T7) plaintext pac.

### Region r6 (0x10A00000-0x10BFFFFF) hand-back (2026-10-13 ~19:50) - see spec\subsystems\r6_summary.md, analysis\claude_names\r6.jsonl (188 records, ~60 at conf>=0.5)
- **Save-data struct** at `PTR_DAT_11a3ee2c`: item pouch +0x23e28 (30 slots x 8 B), item box +0x11a14 (pages of 100 slots), 400-slot storage +0x2051c, progress-flag bitmap +0x1fdb4, unlock bitmaps +0x64/+0x23cdc, hunter rank (0..999) computed from exp at +0x1fdac via cumulative table at 0x11858888. Master data: itemrefs {+1 category,+2 id} index tables at DAT_1e77dcc4 (strides 0x48/0x34/0x3c); item table +0xfc, 0x24-byte records incl. stack max.
- **CORRECTION to my 12:00 note:** the hunter slots (0x1dc6b750, stride 0x1050) DO hold world position at +0xac/+0xb0/+0xb4 (e.g. 0x1dc6b7fc) => interpolation candidates for 60 fps. Other characters (monsters/NPCs) are in a 0x28-entry array at DAT_1ed7ad2c, stride 0xef0. Actor fields: +0x14/+0x15 action id/category, current HP +0x7fc (12-bit fraction at +0xfa4), max HP +0xb2a (75..450); for hunters +3 = weapon class 0..13. Per-weapon action tables are probably the huge single-caller handlers 10bc4aa0, 10bc7910, 10bdf480, 10be7c50, 10bff090.
- `10b42d40` is a **delayed sound-effect queue** (32 x 0x20 B; producer 10b42bf0), not a generic action queue. Sound entry points: `10b42ef0` play_sound_cue_if_enabled (4431 callers). Monster sound banks: `sound\em%03d` + suffix (none/c/d/e/ce) as .snp (path builder 10b44950, sequencer 10b468b0).
- Global 30 Hz tick counter `DAT_1ed5f2c8` drives ~20 scene-object effect helpers (10b51030..10b54490: UV scroll, flip-book, spin) -> need fractional-tick evaluation at 60 fps. Frame pipeline `10b7acd0` render_world_frame_pipeline; attached-model tree walkers 10b7c1b0..10b7c9f0 (node: matrices dwords 0/0x10/0x20, sibling 0x33, child 0x34). Game text uses {I}{K}{U} tags; debug text ~Cnn colour tags.
- Still unnamed in r6: ~3,100 functions (1-caller handlers in 10bc0000-10bfffff and 10b4xxxx-10b6xxxx); 10b60230 (22 KB field/weather effects?).

### Region r4 (0x10600000-0x107FFFFF) hand-back (2026-10-13 ~19:55) - see spec\subsystems\r4_summary.md (~156 names; later duplicate lines supersede earlier ones)
- Region = game-specific logic: NPC dialogue, shops/inventory, menus/HUD, per-character action state machines, Mezeporta Festival mini-games, asset-load helpers. ~5,000 functions still unnamed (about half are single-caller screen/state handlers).
- Structures: session struct `DAT_1e7fff3c` (item pouch 224 x 8 B); player save struct `PTR_DAT_11a3ee2c` (money at +0x60 XOR-obfuscated); master item table `DAT_1e77dcc4+0xfc` stride 0x24; string-table root `DAT_1e77dccc`; 0x1050 character slots (action id, motion id, facing, name, per-action RNG seed); 40 x 0xef0 actor table (waypoints, routes, day/night route switching; maybe NPC-only - unconfirmed); shared text renderer ctx `DAT_1e3cbd64`.
- NPC dialogue engine: `start_npc_dialogue` 10726640, `update_npc_dialogue_node_input` 10726a50, `execute_npc_dialogue_action` 10726de0 (condition-list tables by NPC id). UI is laid out for **640x480 centred on the real backbuffer**; message window 1079dc70/1079e2d0/107ca5f0.
- **Asset loading (HD injection relevant):** loaders build a filename, read via the pack layer into tracked malloc buffers, upload into 0x80-byte texture slots (0x500 slots), detect JKR by 'JKR\x1a'. Stage packs try `stage_hd_som_NNN.pac` / `stage_hd_sef_NNN.pac` first then non-HD; other patterns `weapon\w<letter><NNN>.bin`, `effect.bin`, `mytra.bin`, `npc\*`, `load_um/us/NNN`, `sound\<bank>` by area id, `lobby/mezfes_minigame/*` (full list in r4_summary.md).
- Network: 0x180-byte player block sent as packet type 3 on change (`sync_player_data_block_to_server` 107a0c50); position as packet type 6 (`broadcast_player_position_packet` 106efbd0).
- Open: currency fields (money +0x60 XOR, 'Gz' +0x1ff14, 'Gg' +0x23b88, 'RP' DAT_1e506968); area-id group {0xca,0xcb,0xcc,0xce,0x1bd} special sound/loading; whether hunting monsters use the 0xef0 actor table. Suggested follow-up pass: 0x1073xxxx-0x1077xxxx mini-game cluster and 0x106c-0x106e screens.

### Region r9 (0x11000000-0x111FFFFF) hand-back (2026-10-13 ~20:00) - spec\subsystems\r9_summary.md (~311 names; merge now uses LAST line per addr for agent files)
- Region = **player weapon-class state machines**, continuing r8's modules wmA..wmU: 13 more dispatchers wmX1..wmXD (11015070, 11041b50, 110719a0, 110967d0, 110c12d0, 110ddbd0, 110f6140, 1110c640, 1112fbe0, 11142f20, 11169f30, 11178b60, 1119b920, 1119c160, 1117ef60), each `set_state(actor,kind,id,mode)` with kind 0-4 handlers + begin-idle, on-action-end, tick update, set-substate. Weapon-per-module mapping unknown (probably 14 types + styles).
- 47 giant single-caller functions = **motion event scripts** (switch on motion id at actor+0x32c, up to ~320 `108ff650` window tests spawning effects/sounds/screen shake at frames) and **sound schedules** (`1085cce0(frame,id,kind)`). `108ff650` = "is motion frame inside actor window N"; `1085cce0` = play-sound-at-window; `1082d680`/`11130bb0` write a screen-shake request.
- **Action-node system:** `111d4e20` allocates nodes from a free stack into an active list; 0xA00-slot buffer-block map (`11353f70` alloc, `11354020` free); node types 0,1,2,3,4,5,7,8,9,0x9a,0x1fb with substate-dispatched callbacks; type-8 chain 111e97b0/111e9a80/111eb5e0/111f10f0; ~25 `queue_actor_action_node_*` producers; parallel effect/sound pools (11405d70, 10b8f620).
- **Actor record:** euler rotation +0xa0/+0xa4(yaw)/+0xa8, world position +0xac; HP stored encoded twice (+0x624 rotl5, +0x6bc rotl3, XOR key table: anti-tamper; setter `111a3ad0`; inferred); +0x7f8 area generation check before spawning effects; controller class in 111a8xxx-111a9xxx (vtable slot +0xa38 request_action, +4 -> actor). Per-type tables read via `111a5080/111a5010/111a4fc0` (3000+ callers): `*(DAT_1e77dce0+0xc) + type*0xc0 + 0xb0`, 0x28-byte records x 200 columns.
- Open: which weapon each module is; `10857xxx` buff-slot helpers; ~1.7k unnamed functions in 111b0000-111d3fff (actor+0xd84/0xdf0 sub-struct, node type 0x1fb).

### Regions r2 + r10 hand-backs (2026-10-13 ~20:10) - spec\subsystems\r2_summary.md (246 names), r10_summary.md (627 names, ~500 scripted/pattern-based at conf 0.4-0.5)
- **Pooled FX/action objects (r2 + r10 agree):** 0x200-byte records; u16 family/type id at +4 (0xa0..0x1ba in r2), effect/subtype at +6, state at +8 (0 start/init, 1/3 run, 2/4/5/7/9 ending, 6 free), update callback +0x28, owner character +0xac, position +0x38. Pool alloc `111d4e20`, free `111d4ed0` (critical section DAT_1e73ad88). ~270-300 spawn functions share one template; each family has a state dispatcher; type definitions from an id-sorted 0x1c-byte record table. Generic family 0x3e (~450 call sites): start `1129d3e0`, update `112b3d00` -> class dispatch `112b2f90/112afc00/112ae010/112ad9e0`; class 3 = 70-entry jump table of per-effect scripts. Draw nodes go into 512 depth buckets (`10b8f6f0`).
- Particle/effect player `113d6250/113d6500/113d62d0` (~3000 call sites; templates DAT_1e8d31a8; Vec3/RGBA curve samplers; private LCG so effects never touch gameplay RNG). UI layout engine 0x113e-0x113f: layouts cached by name (`113ecae0`), group `113eeb70` -> part `113ed380` -> textured quad `113ecc60`, keyframed node transforms `113f0650`, 20-slot notice ring DAT_1e375450. 3D model instances table DAT_1e8d8be0. Item pools DAT_1e80db38.
- r2 actor facts: actor class byte +3 (0,1,5,6,0x0a,0x0c,0x0d; class 6 owns ~0x90000 bytes of handlers); per-actor RNG seed +0x448 (x*0xb0 mod 0xff53; matters for netplay sync); style selector +0xd42 (0-3, global override DAT_1ee08ce4). Per-player block DAT_1e2a32f0: 8 x 0x9d0 bytes (class state +0x1c0, buff counters +0x2ac max 18000 ticks, countdown sub-struct +0x92c). Server-time event windows DAT_1e866cd8 vs tables DAT_1e81839c/1e8183a8 (JST +9h). Screenshot upload = small HTTP/1.0 client posting JPEG to /api/ss/bbs/upload.php. UI draw state DAT_1e3cbd64: x +0xc, y +0xe, font size idx +0x64, style +0x18, ARGB +0x207d0; IME toggle via window msg 0x7e9. 16-entry item-combination table with ids XOR 0xA55A.
- Name fix: `10b70cf0` is the main UI text printf (not a debug logger); `10848420` = get_model_part_local_position(entity, partIndex).
- r10 found NO socket/crypto/packet code in 0x112-0x113; network must be >= 0x114xxxxx.

### Renderer subsystem agent hand-back (2026-10-13 ~20:15) - spec\subsystems\renderer.md, analysis\claude_names\s_render.jsonl (first pass)
- `mhl.dll` parses mhf.ini; `mhf.exe` loads `mhfo-hd.dll` if launcher-struct field +0x1d94 (GRAPHICS_VER) == 1 else `mhfo.dll` (SD-only paths); HD DLL tries `emmodel-hd\` then `emmodel\`. Resolutions clamped >= 640x480, aspect from backbuffer. Device creation `114d4fa0` (no MSAA, SWAPEFFECT_COPY, D24S8, lockable backbuffer, HW vertex processing if VS > 1.0); reset `114d6e20`. Game NEVER checks MaxTextureWidth/Height/NPOT caps.
- Textures: PNG via `D3DXCreateTextureFromFileInMemoryEx` (NOT GDI+), header size, 1 mip, managed pool; palette PNGs become A8R8G8B8 (1024x1024 = 4 MiB). Global texture table 4095 usable slots; `100113f0` returns 4096 when full and callers don't check (memory corruption on exhaustion). `108df7d0` writes ids into u16 table at 0x1ecda320 unchecked (72 ids/monster slot; table 4253 entries ~ 38 slots).
- **Strongest new hypothesis for the old crash: 32-bit address space exhaustion.** Process is not large-address-aware (2 GB), the DLL image alone is ~241 MB (static arena) plus a 192 MiB malloc buffer; 24 big uncompressed textures could push it over. Test T6: set the LAA flag (0x20 in PE Characteristics) on a COPY of mhf.exe and retest the 1024px pack (T3). Other candidates still stand (material-table mismatch, model > 8 MiB, > 68 images).
- Shaders: `dat\mhf_90c.bin` 93 entries; entry 9 = JKR block -> 2.17 MB with 504 vertex shaders (9 classes x 4 variants x 14, all SM 3.0), pixel shaders, 4 D3DX effects, 2 textures.
- Prepared (NOT installed, testing paused): LAA-patched copy of mhf.exe at work\laa\mhf.exe (PE Characteristics 0x103 -> 0x123), original backed up at backups\mhf.exe.original; switch with swap_laa.ps1 on/off/status. Use together with swap_hd.ps1 t3 for test T6.

### Scripts/flow subsystem agent hand-back (2026-10-13 ~20:20) - spec\subsystems\scripts_and_flow.md, s_scripts.jsonl (38 names) - CORRECTS several earlier notes
- `10ab4df0` = **quest script VM** (8-byte instructions: four s16 {op,a,b,c}; code ptr at quest runtime+0x58, runtime = `DAT_1e8001ec`; returns new pc, -1 = finished; ~35 ops in the spec; op 0x26 quest-start marker, 0x1a label). Quest runtime tick `10aa8da0`.
- `10cf8f20` is NOT a script interpreter: it switches on actor motion id (0x3eb..0x4aa) and fires effects/sounds at animation frames (a motion-id -> (frame, effect/sound) table in a rewrite).
- **The table at `0x11aa0574` (indexed by DAT_1e8e35a0, dispatched from `11405950`) is NOT the game mode machine: it is a 5-state HTTP image-banner downloader client** (status codes 200/400/403/404/500/503/600). My earlier note calling it the per-mode update table was wrong.
- Real top-level flow: scene pointer `DAT_1edb98c4` (scene id 8 = in-quest, `10899d90`); `game_state[0]` switch has states 0-7; `game_state[1]` = quest-load phase (`1089b860`), `game_state[2]` = load step 0-7 (`1089a240`). `game_state+0x23fe` = quest status (2 accepted, 3 running, 4 cleared, 5 ending, 6 failed, 7 retired, 8 cancelled); `game_state+0x14` = area id. `10b42d40` = delayed spatial sound queue (confirms r6).
- Not done: camera-script instruction set (six channel types, handler tables 0x118c93e8/0x118c9400), quest-flag bits, how `1080fe60` is installed into the scene pointer, motion-event table inside `10cf8f20`.

### Region r1 (0x10000000-0x101FFFFF) hand-back (2026-10-13 ~20:30) - spec\subsystems\r1_summary.md (192 names) - ANSWERS animation-spec open questions
- **Animation sampler found:** segment search `10004820`, sampler wrapper `10004120`, samplers `10009ed0`/`10008da0`. Key type 0x12 = **cubic Hermite**: v = h00*v0 + h01*v1 + dt*h10*tanOut0 + dt*h11*tanIn1 (tanOut of left key at +6, tanIn of right key at +4). **Rotation channels (slots 3..5) scaled by 0.00038349520 = 2*pi/16384 (DAT_119b6810): unit = 16384 per turn, NOT 65536.** All other channels scaled by 1/16 (DAT_119b6078). Track flag 0x2000 = fixed-point, 0x1000 = float. 9 channel slots = scale xyz, Euler rot xyz, translation xyz; local matrix = Scaling, then Euler rotation (`10004f80`), then translation.
- **Skeleton runtime node** (stride 0x1c0; same "part matrix table" at model resource +0x24 used for effect attachment): +0x00 world matrix (translation +0x30..0x38), +0x40 local, +0x80 inverse-bind, +0xc4 slot id, +0xc6 bone index, +0xc8 parent, +0xcc next sibling, +0xd0 first child, +0xd4/+0xd8 track base/offset, +0xdc..0x104 bind/current channel blocks, +0x180 final skin matrix. Functions: `10009640` init, `100083d0` pose from clip, `100092a0` world matrices, `10008670` blend two clips, `10008970`/`10008b20` skin matrix upload.
- fmod chunk tree decoded in `10002af0/10002bf0/10003190/10003790`: tags 5 = index runs, 6 = per-run material ids, 7 = positions, 8 = normals, 0xb = RGBA (float 0-255), 0xa = UV, 0x12 and 0xc = extra attributes (blend weights/tangents/2nd UV: unknown), 0x50000 = bone map. Runtime vertex strides 0x1c/0x24/0x48/0x3c; mesh slot table 0xb40 entries at DAT_11aa3dd8.
- Renderer helpers: render-state filter `1000b3c0/1000bec0/1000c7d0`; state save/restore for 2D passes `10010d50/10011060`; texture slot table DAT_11aa7d80 (stride 0xd8); shader loader `100121b0` (pack entry 9); pack-entry reader `1000ae90` (0x810-byte header).
- Monster AI: region is mostly per-species AI modules (species id = actor byte +3, action id +0x14); dispatchers `100659b0` (0x79), `101b48c0` (0x5f), `101b8d10` (0x63); species blocks listed in r1_summary.md (0x67,0x79,0x81,0x8d,0x8e,0x99,0xa3,0x9f,0xa4,0x11,0x5f,0x63). Actor common offsets: step +5, position +0xac..0xb4, yaw +0xa4 (u16), motion channels +0x1dc stride 0x50, speed +0xb20, area id +0x7f8, obfuscated u16 at +0x624/+0x6bc. Action-node class ids 0x6f/0x71/0x98/0x9a/0x9e/0x9f; global u16 action-serial counter at DAT_1e7fff3c+0x23fc.
- Housekeeping: agents share the scratchpad and overwrote each other's helper scripts; `analysis\claude_names` has stray .py/.txt files (merge_names only reads *.jsonl: fine).

### Region r8 (0x10E00000-0x10FFFFFF) hand-back (2026-10-13 ~20:40) - spec\subsystems\r8_summary.md; r8.jsonl 3,284 names (~450 hand/semi-hand at conf 0.25-0.6; ~2,800 auto-classified `mXXXX_<category>_<addr>` at 0.2-0.3 = routing hints only)
- Region = player-actor action state machines for ~21 weapon-class "modules" A..U (letters ours; weapon mapping unknown). Each module is a vtable class with 600+ virtual methods (why moves have no static callers) with `set_state(actor,kind,id,origin)` dispatcher (10ec2a40, 10eea7b0, 10f0e990, 10f303a0, 10f4e970, 10f75ea0, 10f8d730, 10fa0fe0, 10fe2630) + per-tick update; some have a movement integrator rotating local velocity (+0x468) by yaw16 (+0xa4) into position (+0xac).
- **Motion timelines are data-like:** giant switch-on-motion-id functions (10ec3740, 10ed1910, 10ef31d0, 10f13810, 10f76570, 10fe2d90...) hold per-motion sfx/effect timelines via `1085cce0(frame,id,..)` and `108ff650` window tests (windows = 0x50-byte records from actor+0x1dc; 20k callers); ~155 `move_script_*` + `*_motion_frame_event_table` functions. Extractable into a data table for the rewrite. Effects/sounds only for the locally owned actor (checked vs `*(DAT_1e7fff3c+0x14)`).
- Actor record: +3 class/style id (0..0xb0), +0xa4 yaw16, +0xac..0xb4 position, +0x14/+0x15 action type/phase, +0x410 stance mode, +0xb20 float reset on state entry (playback speed?), +0x678 model resource (attach-point table res+0x24, stride 0x1c0, up to 0x75), +0x7f8 network owner id, +0xab3 remote (net-driven) actor flag, +0x624 obfuscated health. Class motion table: `DAT_1e77dce0+0xc` -> per class (stride 0xc0) 0x28-byte entries; shorts +0x20/+0x22 = start/end frames. Timers decrement by 2 per tick => 1/60 s units with 30 Hz logic. Remote actors ignore requests with origin 3 or 4; `10850d70(kind)` commits state change with the 0xb0/0xff53 LCG.

### Combat subsystem agent hand-back (2026-10-14 ~00:30) - spec\subsystems\combat.md (H/M/L tags), s_combat.jsonl (41 names)
- Tick pipeline: `108af140` zeroes per-tick damage accumulators -> `108b6bf0` loops attack objects vs victims -> `108b7b60`, shape overlap `108c5910`, apply hit `108c26b0`; later each actor's `10842a20` (5.6 KB, 105 callers) converts accumulators to HP loss/part breaks and returns a reaction state id. Attack objects = pooled action nodes (class 0x71 player attacks, 0x6f monster attacks).
- Hit detection: attack hitboxes (attack obj +0xa0) and victim hurtboxes (`10846ca0`, per actor-type tables in CODE, not in the monster pac) share one 0x28-byte record (bone id, shape 0 sphere/1 capsule, radius, local offsets); `10a93dd0` -> world shape; overlap tests `108a9b90/108abc20/108aa220/108ac610`. Players = single capsule. Filters: stage id, team bit, armed-phase byte, ring buffer of attack-instance ids at actor +0x4a2 (multi-hit intervals).
- Damage: dmg = base(attack +0x6c) * attackerOutMult(+0x898) [* attack +0xf6 * 0.01]; dmg *= 80/(80 + victimInMult(+0x89c)); truncate to 16 bits, add chain-bonus table, add to victim +0x854 (8 per-part s16 accumulators; players use slot 0). Monster multipliers from per-type, per-quest-tier master data (`DAT_1e77dce0`, tier `10aa1520`; applied in `10851990`, `100514a0`). Status buildup uses (100 - resist%)*0.01, resist floats +0xc10..+0xc20 (5 classes). HP obfuscated +0x624 cur / +0x6bc max.
- Data: attack definitions = sorted class table `DAT_1e77dcd4` (lookup `10afcfd0`); weapon table `DAT_1e77dcc4+0x7c` stride 0x34; monster per-part defense `stat[0x4e+2*part]` via actor +0xd80. NOT found: elemental/hitzone-% tables, sharpness, affinity/crit (folded into precomputed attack +0x6c by weapon modules?). Correction: the 0x2c4-stride tables near DAT_1dbbb441 are input/UI storage (`108f5150`, `108f58d0`), not combat; 0x1050 slots are player characters (superset of the 0xef0 actor record; 4 players cleared per tick).

### Game-data agent hand-back (2026-10-14 ~01:00) - spec\subsystems\game_data.md, tools\mhf_data.py, s_data.jsonl (19 names)
- **BUG in tools\mhf_archive.py: wrong JKR constants** (uses 0x12/0x1b; DLL `1158efe0` and ReFrontier use +0x0a (4-bit length case) and +0x1a (byte length case)). With the right constants mhfdat's compressed stream is consumed exactly (7,043,471/7,043,471 B) -> 28.7 MB image. Use `tools\mhf_data.py` (`unwrap`, `load("mhfdat.bin")`) for JKR until mhf_archive.py is fixed (it only worked on small test files before).
- mhfdat.bin: magic `mhf\x1a`, version 0x59, header size 0xbc8, +0x10 -> ~400 u16 counts, pointer table from +0x34; loader `10af5140` adds the image base to stored offsets in place. Items: 0x24-byte records x 16701 (buy +0x0c, sell +0x10 confirmed via ReFrontier; rest guesses), names = 16,704-entry pointer array; armor 0x48-byte records (5 sparse per-class tables); ranged weapons 0x3c x 4224; melee weapons 0x38 (not ReFrontier's 0x34). Only ~25 of 735 table slots identified.
- `DAT_118dea08` = 0x71 records x 0x14 B (ten u16; word 0 = effect type 0-9 selecting callback in `PTR_FUN_118df2dc`), driven by lists at mhfdat+0xad8 (4 x {i16 effect id, i16 value}) via binary search in `1081def0` - looks like the equipment VISUAL-effect system (glows/trails), not the skill table. mhfpac: 232 skill-tree names + 536 active-skill names (English in this install) at ReFrontier offsets; mhfinf header decoded (quest rows TBD). Small headerless files (sdt, emd, gao, jmp, mec, mfd, msx, nav, rcc, sch, sqd) have loaders recorded but are not decoded.

### Network agent hand-back (2026-10-14 ~01:10) - spec\subsystems\network.md (~31 KB, ~310-row opcode table), s_network.jsonl (645 names)
- **ORIGINAL function names are recoverable:** most functions start with `mov esi,<name string>; call 114ea090` (function-enter tracer; `114ea000` = exit). The string is the original name, e.g. `CSync_man::putReceive_gacha_item` for `114fb410`. 600 of 603 tracer callers resolve (take the nearest preceding `BE imm32` before the call, read the string). Classes recovered: CAsock_man, CEntrance_terminal, CLobby_terminal, CMessage_man, CSync_man, CAcknowledge_man, CPobj_man, CUser_info_man, ... (agent script fnn.py was in the scratchpad).
- Winsock: WSAStartup(2.0) in `1153b2f0`; CAsock_man (`114e3d10`-`114e4e10`) = non-blocking TCP state machine polled with select once per frame. Framing: CMessage_man (`114eb1b0`-`114ec5c0`) 14-byte BE header (Pf0, KeyRotDelta, PacketNum, DataSize, PrevCheck, Check0-2) = Erupe CryptPacketHeader. Cipher = Erupe's: LCG *0x4fd+0x4fd, three 256-byte tables built by `114eb4e0` from "I want 2 fly high", initial keyrot 0xF2F2D; encrypt `114eb340`, decrypt `114eb410`. Message = u16 BE opcode (>=0x100 escaped as 00 0F + u16), u32 ack handle (`114ecfe0`), payload; replies = MSG_SYS_ACK (`exeAck` 11501860). Dispatch table `0x119de090` (432 entries by opcode, default `115011c0 noImplement`), only 25 real handlers. Opcode names agree with Erupe's packetid.go (0x137 RECEIVE_GACHA_ITEM confirmed). Entrance handshake `114e5ee0`: connect, send 8 zero bytes, send "LOG\0ALL+\0"; replies tagged 'USR','SV2','SVR'. Two separate HTTP clients (GET /v1 `11593950/11594510`; multipart POST `10341a00/10341ab0/10342230`).
- Erupe repo has no docs/network_protocol.md; used network/crypt_conn.go, crypt_packet.go, crypto/crypto.go, packetid.go. Open: per-opcode field layouts (builders are plain byte stores - mechanical), checksum lane order + keyrot-to-byte mapping vs a capture, MSG_SYS_LOGIN (0x14) builder, Entrance reply layouts, ~175 ACK result parsers unnamed.

### Monster AI agent hand-back (2026-10-14 ~00:30) - spec\subsystems\monster_ai.md, s_monster_ai.jsonl (~145 names incl. 116 per-species table entries), helper scripts work\ai\ (pev.py reads a VA from the DLL, findptr.py)
- 40 actors in array `DAT_1ed7ad2c` stride 0xef0 (alloc `10bc39c0`, reinit `1084cc20`); actor+3 = em id (em130 = 0x82; >0xb0 forced to 0); +4 lifecycle (0 spawning, 1 active, 2 remote, 3 despawn `108745c0`); +0x15 major state, +0x14 sub-state; HP obfuscated +0x624.
- **Per-species tables indexed by actor+3** (177 entries): on_spawn `118c3350`; tick `118c3628` (called by `1086e8a0`); request_state `118c38f0` (actor, major, sub, mode); class vtable ptr `11a4e420` -> actor+0x474; ops table ptr `11a4e6e8` -> actor+0x8cc (slots +0x44..+0x68 = per-major tick handlers); type descriptor `118c3bb8` (stride 0x28; 12-byte motion table at +0x14). (Corrects my earlier 'mode table at 0x11aa0574' idea.)
- **Monster AI is NOT in the pac files:** native per-species code + a bytecode script VM (`108696d0`, ~130 opcodes; scripts in DLL .data; script-set pointer actor+0x9f0; operand lengths in `10860730`, not yet decoded). em pac carries model, textures, motions (entry 2), effect defs (entry 5), materials (entry 6). Per-monster numbers come from `dat\mhfemd.bin` (ECD+JKR; loader `10afa180`; record layout not decoded - naive parse misaligned, likely an extra transform in `1158f310`).
- Motion id = space*1000 + group*100 + index (space 1 = per-monster pool); stored id = motionIdx + (layer+5)*200; play-animation call `1084fe60` (10172 callers). Aggro counters per player at +0xb08 (saturate 30000), masks +0xa7c/+0xa7f/+0xb04; target selection in AI ops 0x52/0x53 and `10852c10`; part-break reactions table `1188edf0`. Spawn: creator `10aaa420` (spawn record -> actor); what builds spawn records is unknown. Phase/rage HP thresholds are hard-coded per species in request_state (em130: 0xe10, 0x1518). Adding a monster id > 0xb0 requires extending all 177-entry species tables.

## Watchdog (2026-10-14 00:28)
Windows Task Scheduler task 'MHFZ pipeline watchdog' runs orchestrator\ensure_running.ps1 at logon and every 10 min: starts supervisor.py and keepawake.ps1 if not running (no-op otherwise; logs to orchestrator\watchdog.log only when it starts something). Remove with: Unregister-ScheduledTask -TaskName 'MHFZ pipeline watchdog' -Confirm:$false. Review stage widened: feeder REVIEW_MIN_CALLERS=40 (also reviews functions with >=40 callers). Backends: Codex hits rolling usage windows (resets within ~1-2 h); Copilot monthly quota, agy ~163 h reset, Claude CLI login expired.

- 2026-10-14 01:05: wrote ghidra\scripts\ApplyNames.java (renames FUN_* to <name>_<addr> from analysis\merged_names.csv at conf>=0.45, adds purpose as plate comment; run headless on a COPY of the project). NOTE: a file with that name already existed (created by another agent/session shortly before) and was overwritten without being read; its previous content is lost. Not yet run. Watchdog task verified (LastTaskResult 0). Reviews now 537 (feeder widened).

- 2026-10-14 01:25: family PC MOSHPC (user Mosharof, 192.168.1.48, RTX 3060 Ti) added to the hub as backend 'mosh' (qwen2.5-coder:7b over http://192.168.1.48:11434; yield guard stops Ollama when the owner is active -> 2 min cooldown). 22 tasks done in the first 90 s. SSH to it still rejected (key not accepted for Mosharof/MOSHPC) - not needed for the worker. hub.py backup: orchestrator\hub.py.bak_before_mosh. Second family PC: not set up yet.

- 2026-10-14 01:50: user paused the family-PC workers until tomorrow. 'mosh' removed from the hub (hub.py restored from hub.py.bak_before_mosh; the version with mosh + pause switch is saved as orchestrator\hub.py.with_mosh). Kit remains on marble media\worker_kit; MOSHPC has Ollama + yield guard installed (guard fix applied), SSH helper account NOT created yet (run_fix_ssh.cmd). Second PC not set up.

## Model benchmark on the RTX 5070 PC (2026-10-14 ~02:10) - work\bench_models.py, work\bench_result.txt
qwen2.5-coder:14b vs qwen3-coder:30b (17.3 GB MoE, Ollama partial CPU offload, 64 GB RAM) on 8 reviewed functions:
- Speed: 14B = 7.6 s/function (gen 62 tok/s, prompt 2,600 tok/s); 30B = 14.3 s/function (gen 46 tok/s, prompt ~990 tok/s). So the 30B MoE is usable on this PC at about half the throughput.
- Quality (names vs reviewed names, small sample): 30B names are more specific/closer on 3-4 of 8 (e.g. unpack_file_data_from_archive for read_pack_entry, find_special_effect_data_by_index for get_type6_record_fields, rotate_vector_around_y); 14B is vaguer (process_game_data, search_and_extract_data) but exactly matched one (update_game_state). Not a dramatic gap; the reference names themselves are not ground truth.
- Recommendation: do NOT swap bulk naming to the 30B (2x slower, marginal gain). Use it for REVIEW/second-opinion tasks on the most-called functions if a spare GPU window exists. Loading both models at once thrashes the 12 GB card, so use time-slicing (or a separate machine) rather than running them together. Not wired into the hub (pipeline unchanged overnight).

- 2026-10-14 03:45: review stage exhausted its candidate pool (depth<=8 or >=40 callers): ~1,290 reviews done, none queued. To review more, lower REVIEW_MIN_CALLERS in orchestrator\feeder.py (e.g. 15) - decide in the morning (weaker local-model reviews vs Codex quota). Naming 35,956/36,014 done.

## Bulk naming COMPLETE (2026-10-14 11:00)
All 47,386 decompiled functions have a name (small-model hints for ~38.6k, Codex ~480, agent ~8.3k; merged table analysis\merged_names.csv has 47,397 rows). Hub queue empty; reviews at 1,302 (candidate pool = depth<=8 or >=40 callers exhausted). Pipeline now idle; the overnight /loop passes were stopped. Next (needs user decisions): apply names to a COPY of the Ghidra project (ghidra\scripts\ApplyNames.java), verification harness vs the original DLL, HD texture tests (needs game login), 60fps patch, engine choice, family GPU workers (worker_kit on marble media share).

## New engine started (2026-10-14): C:\Users\Ayman\mhfz-engine (C++20 core 'mhfcore' + planned Godot 4 front-end; user chose C++ with Godot). First milestone done: ECD/JKR/pack readers + mhfx CLI + golden tests (24/24 pass vs Python prototype; ECD identical to ReFrontier). Next: fmod model parser + PNG/texture import, then Godot GDExtension viewer. Clean-room: engine code written from specs, never from decompiled code.

- 2026-10-14 13:00: engine milestone 2: fmod/fskl parsers + monster pack loader (golden-tested: meshes/verts/tris/bones/textures/materials match the Python prototype for em130 SD/HD and em001-hd), glTF exporter (mhfx gltf <pac> <outdir> [name]) and Godot 4.7 viewer (mhfz-engine\godot, runtime GLTFDocument load, orbit camera, --shot). First screenshots of em130-hd (Varusaburosu) with HD diffuse+normal textures in mhfz-engine\out\shots. Static rest-pose only (no skinning/animation yet).

## Engine milestone 3 (2026-10-14 ~14:30): animation + repack tool in C:\Users\Ayman\mhfz-engine
- core: texture-replacement repacker (`mhfx retex`, loader-limit checks, no-op rebuild byte-identical), motion archive parser (205 clips for em130; clip tags 0x80000001/0x80000002 both valid = loop/non-loop), Hermite sampler, pose evaluation with Euler order/unit options, skinned + baked-animation glTF export (`mhfx gltf --motion N`), Godot viewer plays it (`--time`, `--shot`). Golden tests: 30 comparisons pass (containers, model stats, clip counts).
- Verified visually in Godot: with defaults (rot 2*pi/16384 per unit, translation 1/16 replacing bind translation, Euler order ZYX) em130 motion 3 poses stay coherent (no shredding), so units are plausible; Euler order is NOT yet proven (posecheck stretch metric cannot discriminate orders; needs a clip with large rotations or a visual comparison).
- Skin bone indices go through the per-mesh bone palette (palette entries = skeleton bone ids, 48 bones for em130). Bind pose: mesh vertices are in bind-world space; IBM = inverse(accumulated bind translations).
- **Q6 answered:** skeleton bytes are IDENTICAL between SD and HD packs for em130 and em003 (em001 differs, same size); motions entry identical (em130). So an HD replacement model can reuse SD skeleton + motions.

- 2026-10-14 14:45: names applied to a COPY of the Ghidra project: C:\Users\Ayman\mhfz-60fps\ghidra_named (original ghidra\ untouched). ApplyNames: 35,331 functions renamed to <name>_<addr> (conf>=0.45), 509 kept existing names, 11,555 below confidence left as FUN_*, 0 failed; plate comments carry the purpose. Open with Ghidra: project dir ghidra_named, project mhfz.

## Engine milestone 4 (2026-10-14 ~16:00): model writer + replacement + subdivision (mhfz-engine). All 581 monster models: chunk tree and semantic fmod rewrite byte-identical (mhfx chunkcheck). replace_monster_model (limits: <8 MiB fmod, <65536 verts/mesh, <=64 meshes, <=32 materials/mesh, palette<=63) writes a plain pack (JKR stored wrapper). mhfx subdivide em130-hd: 11,596 -> 29,849 verts, renders skinned+animated in Godot. Roadmap file: mhfz-engine\ROADMAP.md.

## Engine milestone 5 (2026-10-14 ~17:30): downloads approved + used. (1) Real-ESRGAN ncnn-vulkan 20220424 (43.4 MB, github.com/xinntao/Real-ESRGAN v0.2.5.0, sha256 ABC02804...) in mhfz-engine\thirdparty\realesrgan; tools\upscale_textures.ps1 upscales diffuse maps (AI x4 -> area 2x, alpha separate; normal/gloss kept): em130-hd 35 s total, pack 19.3 MB (hd2x test pack: mhfz-engine\out\hd130\em130-hd.pac; install with swap_hd.ps1 hd2x - NOT installed). Observation: AI sharpening turns soft glow spots into crisp white ellipses; scales gain clear detail. (2) godot-cpp branch 4.5 (8 MB, thirdparty\godot-cpp) -> godot\bin\mhfz.dll GDExtension: Godot opens .pac directly (verified em001-hd). Mistake fixed: a commit briefly included the 43 MB upscaler binaries; amended and history pruned (repo 0.1 MB).

- 2026-10-14 ~18:00 (auto): engine - HD material table (pack entry 6) implemented: 259/259 HD packs with a table round-trip byte-identically AND are consistent with their model (group count == mesh count, per-group records == mesh material count), confirming the spec's crash rule empirically; 19 HD packs have no table. replace_monster_model regenerates entry 6 on mesh/material-count changes (test added). Next roadmap item: glTF import.

- 2026-10-14 ~19:00 (auto): engine - weapon packs (dat weapon w*.bin: entry0 JKR fmod, entry1 JKR skeleton, entry2 PNG pack) load via load_weapon_pack / mhfx weapon, golden-tested 7/7, renders textured in Godot. NOTE: two scheduled runs overlapped earlier (glTF import + ECD encryptor were committed by another run while I was editing); I discarded my duplicate importer edits. Next: stages (entry 1 nested pack), armour .abn.

- 2026-10-14 ~19:30 (auto): engine - generic model pack loader (mhfx modelpack): stage objects som*/nso* (428 non-empty packs, 29 nso are 0-byte placeholders) all load, fmod rewrite byte-identical, render in Godot (som000 = a tree). Stage terrain st###.pac has a complex nested layout and stage-hd/st###-hd.pac holds DDS sky textures + parameters (not geometry): still open, along with armour .abn.

## 2026-10-14 engine: mhfdat items
Added core/src/mhfdat.cpp (MhfDat::load + items(): 16701 records, 0x24 stride, names ptr array) and `mhfx items <mhfdat.bin> [csv]`; golden ITEMS line (count, name FNV, buy/sell sums) matches the Python prototype. Armour/weapon tables remain on the roadmap.

- 2026-10-14 (auto): engine - mhfdat armour tables: MhfDat::armor(class) reads 0x48-byte rows (head 14595, body 13463, arm 13453, waist 13709, leg 13515) with names, model ids (+0/+2), price (+8); counts from neighbouring table pointers, golden ARMOR lines match Python. Note every row counts as 'used' (names exist for all), so sparse-row claim in spec is unverified. Remaining: melee (0x38 @slot 0x7c) / ranged (0x3c @slot 0x80) weapons.

- 2026-10-14 (auto): engine - stage terrain probe (st001.pac): top pack entries 0 (3-entry pack: 2 small JKR + 170B blob), 2 (pack of 2 JKR), 3 (4 raw bytes), 29 (JKR 1.4 KB), 31 (1.5 MB custom container, NOT a pack table / not an fmod). Entry 31 header: u32 0x60, 0x2e0, 0,0, 0x350, 0x1c4, then 5 records of 3 u32 (id?, size/count?, offset) e.g. (0x4d,0x520,0x122334) (0x57,0x122860,0x2ed6d)... NOTE the records look like (id, offset, size) for ids 0x57,0x58,0xf5,0xf7 (blobs starting 06000000 34000000 09000000 3d000000 = an offset table, likely sub-meshes/sections) and (0x4d,0x520,0x122334) first. No chunk-tree (type 1 / 0x20000) found by scan, so terrain geometry uses a different layout than monsters. Needs a dedicated decode pass (use spec/subsystems or Ghidra stage loader); left unchecked. Next engine slice: mhfdat melee/ranged weapon tables.

- 2026-10-14 (auto): engine - mhfdat weapons: MhfDat::weapons(Melee|Ranged), mhfx weapons, golden WEAPONS lines. CORRECTION to spec game_data.md: melee row stride is 0x34 (17568 rows = name array count), not 0x38; ranged 0x3c (4223 named). Rows exposed raw+name; field decode (damage, sharpness, slots) still TODO. Roadmap mhfdat item ticked. Remaining open: stage terrain, armour .abn, native Godot meshes, motion convention checks.

- 2026-10-14 (auto): engine - armour archives extend/*.abn decoded: header 'mha\x01', u32 index offset, entry count, names offset/size; index (5 u32 {nameOff,dataOff,size,padded,ordinal}) runs to EOF; blobs padded to 0x200 from 0x18; each blob is an ECD/JKR wrapped model pack (f00_arm entry 0 loads: 1 mesh, 525 verts, 10 bones). AbnArchive (core/src/abn.cpp), mhfx abn <file> [idx out], golden ABN lines for all 81 files (126 golden comparisons total). Stage terrain (st###.pac entry 31 custom container) still undecoded.

- 2026-10-14 (auto): engine - STAGE TERRAIN decoded: st###.pac holds a section directory entry (u32 blockA off,size,0,0,blockB off,size,count, then {id,off,size} records); each section is a normal pack (header blob, JKR fmod, JKR params, PNGs) loadable with load_generic_model_pack. st001: section 0x4d = 34 meshes/14,984 verts/26 textures (terrain), 0x57 2,263 verts, three small props. 224 stage packs golden-tested (350 total golden comparisons; gen_golden now takes ~10 min because of pure-Python JKR). Blocks A/B (0x60,0x2e0 / 0x350,0x1c4) and per-section params blob (entry 2) undecoded: probably placement/lighting. Packs with no detectable directory (~200 other st*/-hd files) not yet surveyed.

- 2026-10-14 (auto): engine - motion: scale channels decoded (every scale channel rests at raw 16, so unit 1/16; range seen 1..191; used on ~75 bones per monster), applied in evaluate_pose via world_from_local; blend_local added (lerp T/S, shortest-arc slerp R) with synthetic tests; mhfx motionstats. Key type 0x22 channels exist (em001 motion 1) and are skipped - format unknown. Convention verification vs the real client still needs the game running (login blocked). Roadmap now has only that item open.

- 2026-10-14 (auto): engine - motion key type 0x22 decoded from em001 motion 1 (track 2 tags 0x802200xx): 16-byte keys {f32 value, f32 frame, f32 tanIn, f32 tanOut}; values are natural units (radians for rotation slots, scale 1.0, world units for translation) so no raw-unit conversion; 0x21 assumed {f32 value, f32 frame}. Key now carries float mirrors (v,f,ti,to) used for sampling; Channel.natural_units. 0x13/0x23 still skipped. Tests pass (350 golden + synthetic float-key rotation test). The roadmap's only open item needs the game running.

- 2026-10-14 (auto): engine - only roadmap item left was the game-running verification (needs user: Rain login). Added follow-up items to ROADMAP.md (native Godot meshes, stage blocks A/B + hd skies, mhfdat field decode which needs a few known in-game stats). No code changes this run.

- 2026-10-14 (auto): engine - Godot GDExtension now builds ArrayMesh natively: MhfLoader.pac_to_mesh(path, 'monster'|'weapon'|'model') and stage_to_meshes(path) (one surface per mesh x material, bind pose, diffuse texture via material dword 64 -> texdesc -> PNG, alpha scissor, reversed winding for Godot's clockwise front faces, culling off). Headless test godot/native_test.gd: em130-hd 30 surfaces, st001 5 sections / 56 surfaces. Not yet visually checked in a window (winding/normals); skeleton/skin/animation natively is the next roadmap item.

- 2026-10-14 (auto): engine - GDExtension MhfLoader.pac_to_actor(pac, motion_id): Skeleton3D from the pack skeleton (rest = bind locals), skinned ArrayMesh (4 influences, palette->bone like the glTF exporter, Skin from rest transforms), AnimationPlayer 'motion' with per-frame keys at 30 fps (loops per clip flag). godot/native_test.gd passes headless (em130-hd motion 3: 48 bones, 96 tracks, 4.57 s; pose rotations change on seek). Note: in headless tests read bone POSE rotation, global pose lagged. Not visually verified in a window yet.

- 2026-10-14 (auto): engine - stage packs without a section directory (204 of 428 non-empty st*.pac) decoded: 'layout v2' = top-level entries are packs; model packs (JKR fmod first, e.g. entries 0 and 8) and PNG-only texture packs (entries 3, 5). Pairing by image count (model's max texdesc image_index+1 vs pack size, exact match first) yields textures for all 405 models in 204 packs, fmod rewrite identical on all. load_stage_models(), mhfx stage falls back to it, MhfLoader.stage_to_meshes too (st006: 2 models). Test test_stage_v2 asserts these invariants. Blocks A/B + params + hd skies still undecoded.

- 2026-10-14 (auto): engine - stage-hd/st###-hd.pac: load_stage_hd + mhfx stagehd [outdir]: entry 0 = environment params blob (floats/colours; records with xyz positions e.g. 9506,-31,13851, colours, radii 1250/960 - looks like lights/effects, size varies per stage so the record layout is NOT fixed-stride; undecoded), entry 1 = pack of DDS (st001-hd: 3x 128x128, 393 KB each, flags 0xA1007 probably cube-map faces), entry 2 = 44-byte blob, entry 3 = 4 bytes. 418 packs parse, 898 DDS total, 4 packs (st464/466/467/468) are params-only. Test test_stage_hd. Next: decode the params blob and stage directory blocks A/B (placement).

- 2026-10-14 (auto): engine - TRACER slice 1 done (user approved the tracer plan): tools/tracer = mhftrace.dll (32-bit, injected, line protocol on 127.0.0.1:47000: ping/modules/read/write/bp/bpclear/hits/log), inject.exe (CreateRemoteThread+LoadLibrary), trace.py client, target.exe dummy and selftest.py (PASS: memory read/write, INT3 bp logging eax..edi + 4 stack args + return address, re-arm). Compiler: winget MartinStorsjo.LLVM-MinGW.MSVCRT (i686-w64-mingw32-clang++; the WinLibs install is 64-bit only). Not yet tried on mhf.exe. Notes for slice 2: the game dir has Xidi as dinput8.dll (so a dinput8 proxy would have to chain to it; remote injection avoids that); mhf.exe is launched by mhf-launcher (mhf-iel) so inject after it starts; the game's own anti-tamper/GameGuard behaviour is unknown, try in the MHFZ-erupe copy only.

- 2026-10-15 (night, with user then autonomous): TRACER on the live client (MHFZ-erupe via mhf-launcher; the game runs INSIDE mhf-launcher.exe, mhfo-hd.dll at 0x10000000 = Ghidra base). Injected mhftrace (47000), mhftrace3 (47311, scan), mhftrace4 (47312, snap/filter unknown-value search). Findings: actor HP is scrambled (u16 actor+0x624; hp = ror16(raw,5) ^ (~u16[0x1edb768e-2*idx] ^ u16[0x11a422c4] ^ 0x5ec0)); getter 10aa0d70, setter 10aa0db0, two live actor slots at camp (0x0fae60f0 hp 24500, 0x0fae6fe0 hp 9999) - neither drives the hunter's bar. Party array 0x1e2a3844+i*0x9d0 (fn 101c2c20) with an AddHp-shaped function 101c2cc0 on s16 +8, but +8 reads 0 while alive. Hunter HP still NOT found; god.py is parked. Next with the user: snap/filter search (port 47312: snap 1e000000 1f11c000 at full HP, filter dec after a hit, filter same while idle). User also pointed to Batenkaitos-dev/mh2-decomp (named MH2 Dos PS2 decompile; MHF's engine ancestor): Player struct has hp/hpMax/hpRecoverable, Player_AddHp/Player_Damage/Player_Heal/Player_AddMaxHp in pouch.c, Player_State0_xx state handlers, per-monster em_*.c. Use as a map only (clean-room).

- 2026-10-15 (night): MH2 -> MHF matching. Cloned Batenkaitos-dev/mh2-decomp to mhfz-60fps\thirdparty\mh2-decomp (user asked). New tools\mh2match.py (numeric features only, no code copied): rare-constant anchors (167) -> callee/caller propagation -> call-count voting -> code-layout alignment between matched neighbours of the same MH2 file -> weak constant matches accepted only when layout-consistent. Result analysis\mh2_matches.csv: 540 MH2 functions mapped to MHF addresses; hand audit of random samples ~85-90% plausible (shared distinctive constants). Biggest groups: NPC states, stage/area objects, per-monster code (Em*_MotionSounds for Garuga, Plesioth, Kushala, Chameleos, Blangonga, Fatalis, Shen Gaoren, Laoshan...), hunter Player_* (19). HUNTER HP FOUND statically: Player_Heal=10a983f0, Player_AddMaxHp=10a984f0 (clamp 1..150), AddHp=10a98010; hunter HP scrambled at player+0x624 with table 0x1edb7626 and rotate-3, max HP at +0x6bc rotate-5 (see spec\subsystems\player_core.md, tools\tracer\php.py). Not yet verified live: the client was closed. Next live step: bp 10a983f0 during a heal to get the player pointer, then php.py god.

- 2026-10-15 (night, later): mh2match.py improved (layout edges, wider gaps): 624 matches; written as analysis\mh2_names.jsonl and merged into merged_names.csv as the new top tier 'mh2' (merge_names.py updated). Cron job (:17/:47) continues with the roadmap's MH2 item (raise recall). Game client is closed; live god-mode test waits for the user.

- 2026-10-15 (auto): mh2match.py window stage (per-file MHF address clusters, all-pairs scoring, mutual clear winners >=0.52) -> 741 matches (was 624); window-stage precision lower (~70% in a 10-sample audit: small constant-free helpers rely on location). Monster AI files still low coverage (em_khezu 19/345 before this run). Names re-merged (tier mh2). Next idea: use MHF-side merged names/subsystem and the MH2 call order of state tables (EmX_StateNN arrays) to align per-monster state functions.

- 2026-10-15 (auto): mh2match.py + pointer-table stages. MH2 source has almost no readable dispatch tables (data values come from the disc at build time: only 43 name-tables, none with matched entries). MHF side: 1959 function-pointer runs found in mhfo-hd.dll data (NOTE the on-disk DLL is packed: every section is flagged executable and .text has 0x400 raw bytes, so scan by raw size). New 'numbered-table' stage infers Prefix_NN handler names from slot positions once two numbered matches agree: +9 (Talk_Check*), total 748. Remaining recall ideas: monster state handlers (EmX_StateNN) need more anchors in their MHF tables first; compare MHF table lengths with MH2 handler counts per prefix.

- 2026-10-15 (auto): mh2match.py caller-intersection stage (+9 -> 757 total). Notable: EmKushala_ChangeState=10fe2630 and EmRemobra_ChangeState=110166e0 (monster state dispatchers: their switch cases select the per-state handlers, the best entry point to the monster AI), Math_Sqrtf=100068d0 (2237 callers). Next: read MHF's EmKushala_ChangeState switch and pair its cases with MH2's EmKushala state handlers by case number (spec only).

- 2026-10-15 (auto): mh2match.py switch-case stage: in matched pairs that switch on a value, callees of MH2 case N pair with callees of MHF case N (equal counts, votes pooled). +177 -> 934 matches. Samples: EmGaruga_State4_05 (shares 72/74/75), TownPc_State01 (29/240/622), EmKushala_SetGroup4State (Kushala state machine), Pouch_GiveItems; low-score ones rest on case position only. Monster state handlers now start to fill in.

- 2026-10-15 (auto): mh2match.py consistency pass: a pair is kept only if its matched callers/callees mostly map onto the MHF side's callers/callees (drop when < 1/3 agree with >= 3 matched neighbours; constant anchors exempt). Dropped 42 -> 892 matches. Overall call-graph agreement among matched neighbours 2230/2658 = 84% (independent precision signal). CSV evidence column now ends with 'graph a/t'.

- 2026-10-15 (auto): mh2match.py callee-intersection stage (mirror of caller-intersection) -> 1042 matches after the consistency pass (dropped 45); call-graph agreement 3288/3790 = 87%. New coverage: EmCephadrome/EmKutku/EmDrome MotionSounds, EmKhezu_State6_00, Npc4F states, Contest_Play/Minigame_Update.

- 2026-10-15 (auto): MH2-map roadmap item TICKED. Added tools\mh2report.py -> spec\subsystems\monster_core.md (116 MH2 files; per file the matched count and key entry points: e.g. EmKhezu_ChangeState=10eea7b0, SetGroup0State=10ee9b00, RunGroup0=10ed0070, several State0_xx handlers; EmMosswine_ChangeState=10c0f720). New roadmap item 'MH2 map round 2' for monster-AI recall.

- 2026-10-15 (auto): engine - stage directory block A decoded: u32 header then 0x3c-byte placement records {+0 hi s16 rot (values -110..176, probably Y degrees, unverified), +4 hi u16 section id (0xffff none), +8 flags, +0x0c pos xyz, +0x18 scale xyz, +0x24 ARGB tint, zeros}. st001: terrain 0x4d at origin, 0x57 once, 0xf5 once, prop 0xf7 x8 with rotation/scale/tint. All 1506 placements over 224 directory stages reference existing sections (new test). Block B = fog/light params (far 60000, colour ff211917, light directions (1,1,-1), 0.3/-1/0.5), not decoded.

- 2026-10-15 (auto): engine - GDExtension MhfLoader.stage_to_scene(pac): whole stage as Node3D, one MeshInstance3D per block-A placement (pos, scale, Y rotation assumed degrees, tint kept as node meta). Directory-less (v2) stages get their models at the origin. native_test.gd: st001 -> 11 instances, PASS. Not visually checked yet (rotation unit / handedness may need flipping).

- 2026-10-15 (auto): engine - viewer.gd --stage <pac> [--shot png] renders MhfLoader.stage_to_scene. st001 check: section 0x4d (34 meshes) is terrain AND sky dome together (scene AABB 116k units), so framing hides sky-sized meshes; props (plants/trees of 0xf7, 0xf5, 0x57) appear upright, scattered, with varied sizes -> placement position/scale/up-axis look right. Rotation unit still unverified; next: split 0x4d meshes (sky vs ground) by per-mesh bounds so terrain stays visible, then compare a screenshot with the game.

- 2026-10-15 (auto): engine - viewer --stage now hides only sky-dome-sized SURFACES (5 of 48 in st001 section 0x4d), keeping the ground: st001 renders as a jungle stage (cliffs, waterfalls, vegetation terraces) with the block-A props sitting on the terrain - placement confirmed visually. White surfaces = untextured (water/waterfall materials: texture lookup or alpha not handled yet). Screenshot: mhfz-engine\out\st001_scene.png.

- 2026-10-15 (auto): engine - white stage surfaces explained: some PNGs are white RGB with the pattern in alpha (st001 terrain: 3 of 26, waterfalls/foam). build_mesh now detects them (mean RGB > 0.94 + alpha present) and renders them alpha-blended, colour from vertex colours, no depth write; st001 waterfalls now look like translucent cascades with mist. Still off: flat water planes bright, one black quad (probably an additive/other blend mode in the material render state, 0xf0000 chunk, not decoded).

- 2026-10-15 (auto): engine - render-state chunk 0xf0000 (18 dwords per mesh) survey on st001 terrain via new 'mhfx renderstate <pac> <section>': word0 0x10000, words 3/4/6/7/8/9 small flags, word11 = 2, word12 = 3 normally and 1 on mist/glow meshes and 6 tiny quads. Hypotheses applied in build_mesh: w12==1 additive+unshaded (fixed the black quad in st001), w7==1 alpha blend (depth pre-pass), w4==1 no depth write. Flat water planes (tex17, w4=w7=1) still too bright: probably darkened by vertex colour or a multiply blend in game. Needs a game comparison.

- 2026-10-15 (auto): engine - stage vertex colours are baked lighting + transparency (255 = full; st001 ground meshes average ~105-135, water planes alpha ~125-190). Stage meshes now multiply vertex colour/alpha into the albedo (build_mesh vertex_light flag, stage paths only; monsters unchanged until their colours are checked), and render-state w7==1 surfaces use real alpha blending. st001 now shows translucent teal water planes and shaded terrain. mhfx renderstate also prints mean vertex colour/alpha per mesh.

- 2026-10-15 (auto): engine - stage directory block B (452-byte layout) decoded into StageEnvironment: 3 slots (times of day?) each with fog far (60000) / factor / ARGB fog colour (+0x18 stride 0x18), light intensity + 4 packed colours (+0x5c stride 0x20), light direction vec3 (+0x100 stride 0x44) and an unknown second vec3. st001 fog ff211917, dir (1,-1,0); st139 fog ff8a7a70, dir (0.45,-0.8,-0.8). Only 28 of 224 directory stages have the 452-byte block (test checks those); other sizes/layouts not surveyed yet (st139 decoded in Python but not via mhfx - check). mhfx stage prints env slots.

- 2026-10-15 (auto): block B survey over the 224 directory stages: size 0 in 141, 452 in 28, then 440 x9, 2012 x8, 156 x6, 312/3960/3964 x4, 3408/432 x3, 520/396/248/172/1316/872 x2, 436/856 x1 -> variable structure (slot counts?). st139 has a 1-section directory in entry 31 (the earlier Python probe picked a wrong entry). Stage-scene roadmap item TICKED; leftovers moved to a low-priority item. mhfx stage prints block A/B offsets and sizes.

- 2026-10-15 (auto): engine - stage_to_scene applies block B slot 0: a 'Sun' DirectionalLight3D along the light direction (energy = light intensity) and fog colour/far as scene meta; viewer uses fog_color as background. st001 fog ff211917 read as ARGB = dark brown (0x21,0x19,0x17); channel order unverified (ABGR would be dark blue). native_test checks 11 instances + Sun.

- 2026-10-15 (auto): engine - block B is NOT a fixed struct: comparing st001 (452 B) and st110 (440 B) via new 'mhfx blockb <pac>' shows a tagged/keyframed layout. Header dwords hold counts (st001 00030001 00080003 00030001 00080000, st110 00030001 00050003 00030001 00070000); fog records (far, factor, ARGB colour) are followed by words with frame-like values 0x3c/0x12c/0xf0 (60/300/240) -> the environment is animated over time (day/night transitions?). st110: fog far 100000, colour ff6496ff, colour records 3c6496ff, light dir records (0.45,-0.8,-0.8)/(0,1.5,-1) at shifted offsets. The 452-byte decoder works only because those 28 stages share one keyframe layout. Next: derive the record/track grammar from the header counts (8 vs 5 and 8 vs 7) before generalising.

- 2026-10-15 (auto): MH2 map round 2 slice: 'trusted switch' rule - in a matched switch where >= 2 cases already agree with existing matches, single-callee case pairs are accepted even with a low content score (MHF versions grew). EmKhezu_ChangeState case 1/3 -> SetGroup1State=10ee9c60, SetGroup3State=10eea410, which cascades into the state handlers. Matches 1042 -> 1405 (dropped 53 by consistency), call-graph agreement 5548/6378 = 87%. Monster coverage now: Khezu 94/345, Kushala 83/248, Hermitaur 63/104, Cephadrome 53/185, Chameleos 49/236, Rathalos 44/264, Diablos 37/136, Garuga 31/159 (Gravios 8, Yamatsukami 2, Laoshan 6 still low). monster_core.md regenerated (122 files). Low-priority stage item moved to the end of the roadmap.

- 2026-10-15 (auto): MH2 round 2: call-sandwich stage (inside matched pairs with >= 2 anchored callees, a single unmatched callee between the same two anchors on both sides is paired). +32 -> 1437 matches (consistency dropped 62), agreement 5666/6548 = 87%. monster_core.md and merged names refreshed.

- 2026-10-15 (auto): MH2 round 2: case-set stage (dispatchers keep their case-label sets; near a file's matches pair unmatched functions with >= 5 labels at Jaccard >= 0.85, margin 0.12, only from round 2 on). First loose version (0.75, early) displaced good matches (Hermitaur 63 -> 8 via the consistency pass); strict late version: 1566 matches, agreement 6070/7058 = 86%. Coverage: Khezu 99/345, Kushala 85/248, Hermitaur 65/104, Cephadrome 56/185, Rathalos 55/264, Chameleos 49/236, Diablos 37/136, Garuga 36/159, Plesioth 25/227, Blangonga 23/168, Gravios 14/219. New tools\mh2cov.py prints per-monster coverage.

- 2026-10-15 (auto): MH2 round 2 TICKED at 1566 matches; round 3 queued for the low-coverage monsters (Gravios, Kutku, Yamatsukami, Laoshan, Shen Gaoren). Remaining autonomous work after that is only the low-priority stage leftovers; everything else on the roadmap waits for the user (game running for god mode / tracer / convention checks; known weapon stats for mhfdat fields).

- 2026-10-15 (auto): MH2 round 3 slice: case-set threshold 0.75 for files under 10% coverage (0.85 elsewhere): +25 -> 1591 matches, agreement 6140/7120 = 86%, no regressions in well-covered monsters; Gravios 14 -> 24, Kutku 10 -> 12, Shen Gaoren 12 -> 14; Yamatsukami 4/79 and Laoshan 7/77 barely move (MHF likely rewrote them).

- 2026-10-15 (auto): engine - stage block B GRAMMAR: header = 8 u16 counts h0..h7; size = 16 + 24*h1 + 32*h2 + 4*h3 + 32*h4 + 68*h5 + 16*h6 (exact least-squares fit on all 17 sizes; h0 always 1, h7 not a size - time value?). Lists in that order: fog keys (u32,u32,far,factor,ARGB,u32), colour keys (u32,intensity,4 packed colours,u32,u32), small 4-byte entries, 32-B records (e.g. 1000,1000,0,xyz position,0x101,0), light keys (u32,f32,dir xyz,aux xyz,...), 16-B records. StageDirectory::environment() parses all lists; all 83 stages with a block B parse to exactly their size (test). MH2 round 3 closed.

- 2026-10-15 (auto): stage-hd entry 0 (environment params) probe over 160 packs: header = f32 (3.4 or 3.3), then 4 count-like bytes (b0 0..5, b1 1..20, b2 = 30 almost always, b3 0), then ARGB fefefe00...; a linear size fit on these bytes fails (max error 2077 B), so the blob has further variable sections not described by those bytes. Examples: b=(0,1,30,0) -> 1385 B, (0,2,30,0) -> 1433 B (+48 per b1 step there), but (0,9,30) -> 1705 and (0,20,30) -> 2145 break that pattern. Parked (low priority). Nothing else on the roadmap is doable without the user now.

- 2026-10-15 (auto): no autonomous roadmap items were left, so queued 'Stage collision (HITS)': stage pack entry 2 holds two JKR 'HITS' blobs (st001 30132 / 57536 B). Header words: magic, total size, 501, 501, 40, 40, 0, 0; then at 0x20 two words (0x20, 0x3fdc) and a 40x40 table of increasing offsets (step 4), so a uniform spatial grid (40 x 501 = ~20000 units, matches the map) with per-cell lists and geometry later. Relative base of the offsets still to pin down.

- 2026-10-15 (auto): engine - stage collision 'HITS' decoded: all offsets relative to byte 8; u32 cell size x/z (501), cells x/z (40), 2 zero words, table offset (0x20 -> 0x28 abs), triangle data offset; table = cells u32 list offsets; lists = u32 byte offsets into the triangle data (multiples of 56) ending 0xffffffff; triangles 56 B = u32 flags, 3 x xyz vertices, xyz normal, u32 extra. st001: blob 0 246 tris (bounds 7130..16401 x 7197..14058, y -735..4475), blob 1 487 tris over the whole 20040x20040 grid. All 428 packs / 856 blobs / 444018 triangles parse (test). Next: Godot ConcavePolygonShape3D + walk camera.

- 2026-10-15 (auto): engine - GDExtension MhfLoader.stage_collision(pac): one StaticBody3D per HITS blob with a ConcavePolygonShape3D (backface collision on, winding reversed like the render meshes). native_test adds it to the tree and casts a ray down at (10000, *, 10000) in st001: hits at y 2685. Next: walk camera in the viewer.

- 2026-10-15 (auto): engine - walkable stages: godot/walk.tscn + walk.gd load stage_to_scene + stage_collision and drop a CharacterBody3D capsule (r 40, h 170 stage units, gravity 2400, speed 650, jump 900) onto the ground under --at x z; WASD/mouse/Space/Shift. --shot runs a scripted walk: st001 spawn (9000,193,11000) -> walked to (8663,55,11100), is_on_floor true; screenshot shows the sandy riverbank, cliff, trees and waterfalls. Collision item ticked (triangle flag meaning still open).

- 2026-10-15 (auto): engine - walk.tscn --monster/--motion/--dist: Varusaburosu (em130-hd, motion 3) stands animated on the st001 base-camp beach in front of the walking hunter (raycast onto HITS collision, faces the hunter). First 'monster in a stage' scene. Queued next milestone: monster idle/wander/turn using real motion clips, hunter body, hit/hurt boxes (close-enough fight slice).

- 2026-10-15 (with user awake): engine - first monster behaviour. mhfx clipstats (per clip: frames, loop, root travel, yaw, vertical) -> em130 roles idle 1, walk 3 (581 u per 136-frame loop), run 17 (1897 u / 166 f), lunge 65 (one-shot, ~1400 u). pac_to_actor now takes extra clips + in_place (root x/z frozen, travel stored as meta). monster_brain.gd (own rules): idle 1.5-3.5 s, turn 80 deg/s toward the hunter, walk/run by distance, attack under 1600 units only when facing within 25 deg, stop at 350 units, ground snap via HITS raycast. Scripted 30 s run in st001: idles, walks in at ~127 u/s, lunges, stops at 347, idles, re-attacks.

- 2026-10-15: engine - placeholder combat in walk.tscn (hit spheres, damage both ways, HUD bars, respawn) verified by a scripted 40 s run. USER REPORTED the tail detached: in_place froze x/z of every bone with translation channels; em130's tail root has its own translation channels, so it was pulled off. Fix: only the top-most translating bone (no translating ancestor) is frozen; side view (--mface) confirms the tail is attached again.

- 2026-10-15: em130-hd meshes (new mhfx meshbones): 0 and 7 cover the same part (bone 44, 650 vs 960 verts) and 8/9 are identical (bone 9): they are wing-blade GLOW VARIANTS - rendering with 7,9 hidden gives orange glow, with 0,8 hidden purple-blue glow (matches the user's in-game screenshots = normal state). The game shows one variant per state; we drew both. Loader now stores 'surface_mesh' meta (surface -> game mesh index); walk.tscn hides [0, 8] by default (--hidemesh to override). User asked 'why two tails' - likely the long crested head reads as a second tail from the side; asked them to point it out.

- 2026-10-15 (auto): engine - monster_brain hit spheres from bones: attack sphere follows the head bone (furthest forward in rest pose; em130 = bone 37) during the lunge window, hurt sphere centre = mean of all animated bone positions. Scripted 40 s: hunter hit 3x, monster hit 25x.

- 2026-10-15: engine - visible hunter. extend/f00_*.abn entries are model packs in a shared rest pose; their texture is a BARE PNG entry (generic loader now accepts it). Body skeleton (f00_body entry 1): bone 3 spine y 14.4, 4-7 shoulders ~y 35, 8 neck y 37.1, 9 head y 49.4. Face/hair are modelled in their own small skeletons: face root = head bone; hair root = spine (its head bone at y 35) -> offset = body head bone - piece's highest bone. walk.tscn --hunter f00 --third shows the armoured hunter (T-pose, static) on the st001 beach facing Varusaburosu. Player motion data not located yet (next).

- 2026-10-15 (auto): HUNTER MOTION located: dat/motion/plcom.mot (JKR -> raw motion archive, 392 clips in 11 groups; tag 0x80000002), w00..w13.mot per weapon class (w00: 162 clips), plface_m/f-pc.mot, npcNN.mot. Every player clip has 9 tracks: 0-1 empty, 2 root (rot+trans), 3-8 rotations only = the leg chains (leg piece skeleton: 0-2 roots, 3-5 R hip/knee/ankle at y -18.6/-58.6/-94.6, 6-8 L leg, 9-14 spine+R arm...). Armour pieces carry PARTIAL skeletons with their own numbering (body: 0-2 roots, 3 spine 14.4, 4-7 shoulders, 8 neck 37.1, 9 head 49.4; arm: spine, both arm chains to x +-70). Next: canonical hunter skeleton via the fskl Bone.id fields, then find the upper-body clips (other groups of plcom or w##.mot) and drive all pieces. New mhfx motfile <file> [id] (clip header + per-track channels).

- 2026-10-15: CANONICAL HUNTER SKELETON = the leg piece's skeleton (f00_leg entry 1): 21 bones, stored id == index: 0-2 roots, 3-5 R hip/knee/ankle, 6-8 L leg, 9 upper root, 10 spine (y 14.4), 11-14 R shoulder/upper/fore/hand (x 3..70, y 34-36), 15-18 L arm, 19 neck (37.1), 20 head (49.4). Other pieces carry SUBSETS renumbered from 0 (body: 0-2,10->3,11->4,12->5,15->6,16->7,19->8,20->9 by position; arm: 10,11..18; wst: 0-2 + 3,4,6,7 with parent 1). Mapping is by rest position (stored ids restart at 0 per piece). plcom clips (9 tracks) drive canonical 0-8 (root + legs); upper-body tracks 9-20 must come from other clips. New mhfx abnbones <abn> <i>.

- 2026-10-15: USER: 'tail below him' = em130-hd mesh 1 (main bone 47, 2 bones, small) is the SEVERED TAIL part; its bones have no animation, so it lay at the monster's feet. walk.tscn hides [0, 8, 1] by default (glow variants + cut tail). TODO: make this data-driven (part-break state / meshes on unanimated bones).

- 2026-10-15: USER noticed missing normal maps. build_mesh now adds the mesh tangents (HD 0x120000 chunk, xyz + sign) as ARRAY_TANGENT and the material's stage-1 texture (material dword 65 -> texdesc -> PNG) as the normal map; em130-hd shows scale relief, no obvious artefacts (normal-map channel convention not verified against the game). Gloss (stage 2, dword 66) not used yet (would map to inverted roughness).

- 2026-10-15: USER asked for gloss maps: build_mesh uses the material's stage-2 texture (dword 66 -> texdesc -> PNG), converted per pixel to roughness = 1 - mean(RGB), as the roughness texture (red channel, roughness 1.0). Subtle highlights on em130-hd scales; gloss channel convention not verified against the game.

- 2026-10-15: USER: drop placeholder particles, decode the real ones (monster_fx.gd removed). em130 pack: entry 3 = pack {JKR fmod 1,771,268 B, JKR fskl 79 bones}, entry 4 = 4 PNGs (both identical in SD/HD) -> second model set (effect meshes or another form; to render); entry 5 = JKR 68,612 B: u32 5 then 5 (offset,size) pairs, records like 0x00040001 0x04740001 0x04750001 0x04760001 0x04740002 = likely motion event tables (sound/effect triggers). Roadmap item added.

- 2026-10-15 LIVE SESSION (game crashed): tracer re-arm bug - a single global re-arm slot meant two game threads hitting breakpoints concurrently swapped targets, leaving an unhandled single-step trap -> crash. Low fps came from 289 breakpoints incl. ultra-hot ones (Effect_DrawModel 1000c7d0 ~926k hits, get_effect_bank_instance_ptr 10bbe0a0 ~106k). Fixed: per-thread (thread_local) re-arm, breakpoints retired after 2000 hits. Also: the KERNELBASE CreateFileA/W watcher saw NO opens while loading a quest (game reads its archives some other way - preloaded handles or memory maps; watch ReadFile/NtReadFile or MapViewOfFile next). Effect findings: 1091e410 = play sound when motion passes a frame (649 callers, name was wrong), 1091e6e0 (986 callers) calls 10b43590 with an id inside a motion window; effect runtime instances = bank of 0x94-byte records in sub-banks (+0xb320/+0xa0a0/+0xa9e0/+0xa540 ...), Effect_DrawModel draws effect models; effect tracks: effect_track_step_integer_value 10bbc1f0, loop counter 10bbbe40, uv scroll 10bbc330/10b52890.

- 2026-10-15 (later, with user): REAL MONSTER EFFECTS DECODED (spec: spec\subsystems\effects.md; engine commit bd46f2c). Monster pack entry 5 = effect container: u32 n + n x {off,size}; section 0 = directory {u16 ver, u16 count, count x {u16 type, u16 id}}; type 1 = effect file, type 2 = trigger table (em130: 7 records frame 194..324 -> effect 0x476 sub 2, a/b 35/26). Effect file (parser 113d4a70) = 0x1c-byte header of u16 counts + tables: T1 spawn timeline 0x70 (pos/rot/scale + jitter, +0x48 f32 yaw, +0x4c emitter id, +0x4e trigger time in 1/60 s, +0x50 timeline sub-id, +0x52 repeat, +0x54 flags (bit0 physics table), +0x58 count, +0x5c f32 time scale), T2 vec3 keys 0x18, T3 colour keys 0x10, T4 int keys 0x10 (mesh lists / child timelines), T5 particle emitters 0x38 (mesh source +6: 1 = owner model, else dat/effect.bin; mesh, lifetime, track ids; all defs sharing an id spawn together), T6 physics particles 0x8c (velocity+jitter, spin, grow, gravity, bounce). ALL 2120 effect files in emmodel/emmodel-hd parse to exactly their size. Particles are MESHES: entry 3 = effect model (em130 77 meshes: rings, shockwaves, pillars, shards), entry 4 = its 4 PNGs; dat/effect.bin entry 0 = global effect model (446 meshes) + entry 1 PNGs. Effect ids are per monster (em130 0x474-0x476, em140 0x492-...). Runtime: registry 128 x 0x44 at 0x1e8d31a8 (id +0x38), spawners 113d61f0 / 113d6250 / 113d62d0 take the effect id in EDX (decompile hides it) and the timeline sub-id as first stack arg. Correction: the 0x94-byte 'effect bank' (10bbe0a0) is MATERIAL animation (UV scroll, colour/alpha ramps), not particles.
- Which attack plays which effect: em130_motion_event_script 10da8e00 switches on motion (+0x32c), checks frames (108ff650(float const)) and spawns type-0x82 FX scripts 1121d390(owner, 4, N); N indexes 0x28-byte records of a runtime table (DAT_1e77dcd4, 0x1c-byte rows sorted by u16 id, lookup 10afcfd0) interpreted by an opcode table (116ab788); em130's opcode handlers live at 11216cc0..1121c240 and call the effect players with mov edx,0x474..0x476 (74 call sites found by scanning build\mhfo-hd.60fps.dll .text, which is unpacked). Static chain stops at the runtime table -> tools\tracer\fxtrace.py logs (motion, effect, sub) live and dumps that table. Static motion->frame->N list in analysis\em130_fx_map.json (handler column wrong: indexed the wrong table).
- Engine: mhfx effects/effectscan, MhfLoader.effect_data/effect_meshes, godot/effect_player.gd (MhfEffectPlayer), godot/fx_view.tscn (render a timeline; --only e12/p7). em130 0x474 timeline 17 renders as a ground-slam explosion (decal, fireball, glow, rays, debris) - screenshot out\fx\fx_474_17_0.90.png. Open: blend mode per draw variant (0 = mix, else additive is a guess), T6 lifetime offset, rotation order, billboard flags, child lists; live comparison.

- 2026-10-15 (with user): em130 STATES (user, from the game): ENRAGED = blue wing blades (meshes 7/9 shown, 0/8 hidden) and the glow spots all over the body glow WHITE; NORMAL = orange blades (0/8 shown) with orange glow; both forms emit stove-flame heat from the tail and horns (pink-white flaming spike tips in the user's screenshot). Glow atlas tex21 of em130-hd: blade glows pre-coloured, spots/claw glow are greyscale masks tinted at runtime (mesh 0 = near-white alpha mask, mesh 7 = dark additive). Persistent heat effect = effect file 0x476 subs 10-17 / 28-35 (emitters life 36000, meshes 35-42 / 66-73, f28 0.05 = alternate draw path, probably heat distortion); attachment bones unknown (nearest-bone guess in godot/glow_view.gd) -> get them from fxtrace (play_attached host). Earlier note calling purple-blue the normal state was WRONG.

- 2026-10-15: em130 heat flames PLACED from the client: handlers 11216cc0/11216db0/112190d0/112192a0 switch on the timeline sub-id and call 10848420(owner, bone) (= bone world position) then play_attached(0x8000|sub) of effect 0x476: subs 10,11 / 14,15 / 28,29 / 32,33 -> bone 34 (head), 12/16/30/34 -> bone 3 (body/back spikes), 13/17/31/35 -> bone 44 (tail tip/club). Shell meshes 35-38, 39-42, 66-69, 70-73 = nested layers (colour alpha 255/255/176/96). Only the bone POSITION is used (orientation = monster body). Renders now match the user's screenshot (flames on the tail club spikes, back spikes, horn tips). Still static: flicker presumably from the alternate draw path (+0x28 = 0.05) and/or material UV animation.

- 2026-10-15 (user): em130 greyscale glow parts (spots all over the body, claws/horns) glow WHITE in both states - not tinted; the colour around them is the heat-flame effect. Only the wing-blade glow differs per state (orange normal, blue enraged).

- 2026-10-16 (loop): material-effect bank (0x94/0xb4) = EQUIPMENT glow only: defs in mhfdat.bin header +0x294 (lists, 0x18 rows) / +0x298 (0xb4 defs), used only by character code (10bbac20, 10b81e30). Monster flame flicker is not from it. Alternate particle draw path (+0x28 != default, em130 flames 0.05) = 10007fd0 -> draw_mesh_object 10013440 pass 4 with post-process helpers off; the value goes to render_mesh_batches in a float register (decompile drops it) - confirm live. Spec effects.md updated.

- 2026-10-16 (loop): engine - godot/monster_look.gd (MonsterLook) holds the em130 look (states, glow masks, flame shells); walk.tscn uses it (enraged below 50% HP, placeholder) with bloom; glow_view.gd now a thin viewer over it. Screenshot out\fx\walk_look.png.

- 2026-10-16 (loop): HUNTER ANIMATION SOLVED: player .mot archives pair groups - even group = 9-track clips (canonical bones 0-8), odd group = 12-track clips (bones 9-20) with ids +100 and identical frame ranges (plcom: groups 0/1 69 pairs, 2/3 55, 4/5 39, 6/7 16, 8/9 17; w00: 11/3/67). MhfLoader.hunter_to_actor skins all armour pieces to the leg piece's 21-bone skeleton (rest-position mapping, depth tie-break for the 4 bones at the origin) and bakes lower+upper clips; plcom 1 = standing idle, 3 = crouch. godot/hunter_view.tscn. Next: use it in walk.tscn (idle/run clips), find walk/run ids.

- 2026-10-16 (loop): mhfx playerclips: plcom 1 idle, 52 walk, 39 run (160 u/s @30fps), 38 sprint (277), 28 dive, 37 sneak. walk.tscn hunter is animated (idle/run/sprint, faces movement); speeds 320/550 assume 60 fps player clips (unverified - compare with the game's run speed when live). Screenshot out\hunter\walk_hunter_run.png.

- 2026-10-16 (loop): WEAPONS = extend/w{e,f,g,h,i,k}{000,500}.abn (468-500 model packs each; *snd.abn = .snd sound entries). Letter -> class not mapped yet (wg = great swords by look, we000 long thin blade, wk000 wide head). w00.mot = Great Sword (10001 drawn stance, 10404 overhead swing, 10410 horizontal). Grip: weapon origin on canonical bone 14 (R hand) with no extra rotation looks right. walk.tscn hunter holds wg000 and swings on F/LMB. Next: map weapon letters to classes via mhfdat weapon rows (model id field), hit spheres from the blade.

- 2026-10-16 (loop): WEAPON ROW -> MODEL decoded: row +0x00 u16 model, +0x03 class; model -> extend/w{e,f,g,h,i,j,k}{000|500}.abn entry w<l><nnn>.bin (thousands -> letter, 5000s unused). 21714/21787 rows resolve (test). mhfx weapons <mhfdat> <row>, MhfLoader.weapon_info / weapon_mesh; walk.tscn --weapon-row (default 1 = model 10 great sword). Spec game_data.md updated. Next: weapon class -> motion archive (w00 = GS confirmed by look; the rest by class number?), blade hit spheres.

- 2026-10-16 (loop): weapon CLASS -> motion/wNN.mot confirmed from the client file table at 0x11a45ef0 (3rd PE section): plcom, lbcom_off/on/coco, selcom, ac_com, w00..w13 in class order, then w11ten/w11ran/w11goku, w12ten/w12ran, w12w_typeA-E, w11w, w11t0/t1, w13, w13w, pltow, plface_m/f, npc*. 'ten/ran/goku' look like MHF's Heaven/Storm/Extreme styles (unverified). walk.tscn --weapon-row now animates GS (row 1), hammer (5000), lance (103), long sword (5) with their own drawn idle + attack (out\hunter\weapon_classes.png).

- 2026-10-16 (loop): weapon skeletons: bone 2 at (0,0,L) = blade end along +Z (GS 224.6, LS 126.8; lance 52.3 with extra roots 3/4 = shield?); bone 3 e.g. (140,0,19) on the GS = maybe sheath/back attach point. walk.tscn blade hits = segment grip->bone2 vs monster posed bones (160 radius) in 25-75% of the swing; the real game uses per-part hit data (not decoded) and attack windows from the motion/attack tables.

- 2026-10-16 (loop): melee row +0x04 = price, +0x0a = raw attack (confirmed by names: Iron Sword 1320z/60 ... Royal Flawless 50000z/230); names are cp932 (English in this install). walk.tscn blade damage = attack * 0.5 placeholder motion value. Display-attack multiplier (GS x4.8?) still needs one in-game value from the user.

- 2026-10-16 (loop): melee rows: +0x0f element type (1 fire 2 water 3 thunder 4 dragon 5 ice), +0x10 element/10, +0x0c affinity (likely), +0x18 sharpness table index (table not found yet), +0x11/+0x12 status type/value? (spec game_data.md). weapon_info returns them.

- 2026-10-16 (loop): sharpness table NOT found as a header-referenced mhfdat table with ~3418 rows (index +0x18 max 3417; most rows small values like 10, 23, 24, 71, 236). Next try: look for a table of 7-8 u16 bar lengths summing ~400 anywhere in mhfdat, or the client code that reads row +0x18 (search decomp for 0x18 offsets near weapon row lookups).

- 2026-10-16 (loop): SHARPNESS decoded via client 10a98750: slot 0xac = per-class pointer array, gauge = table[class] + row byte +0x08 * 16, 8 cumulative u16 thresholds (max 400). All 17568 melee rows valid (test). +0x18 is not sharpness (my earlier guess was wrong). Weapon max/start sharpness still open (byte +0x09?).

- 2026-10-16 (loop): sharpness runtime decoded (spec game_data.md): hunter s16 +0xb26 current, +0xb2c max, +0xb2f colour level; -3 per hit (1/6/halved by skill checks; per-class extra from mhfdat 0xa8c), sharpen = current := max. walk.tscn HUD shows the real gauge, drains per blade hit, R sharpens; max (gauge end - 50) and colour damage factors are placeholders. Live: read player +0xb2c to find the max rule.

- 2026-10-16 (loop): GLOBAL EFFECTS: dat/effect.bin entry 18 = pack table {directory, 61 effect files} (ids 0xbb8-0xbcc, 0xfa0-0xfc6, 0x1004-0x100a, 0x13ee/ef), all exact. 0xbb8 = hit effects (0 orange sparks, 1 red splash, 4-8 blue/red/white slash streaks - element/sharpness variants?). Code callers of each global id listed by scanning mov edx,id before effect-spawn calls (generic names). walk.tscn plays 0xbb8/0 at blade contacts. Spec effects.md: add the pack-table form.

- 2026-10-16 (loop): QUESTS decoded (spec subsystems/quests.md, engine core/src/quest.cpp, mhfx questscan): all 54977 Erupe quest files parse; monster id == emNNN, spawn stage == stNNN. Varusaburosu: st396 (volcanic arena with lava river) at (6307,0,5820), orientation 12080, stat table 31/53. walk.tscn --quest <file> loads arena + monster + spawn (out\hunter\quest_st396.png). Quest copy lives in the session scratchpad (re-copy from marble ~/erupe/app/bin/quests if needed). stage_to_scene: unplaced sections now shown at origin.

- 2026-10-16 (loop): quest zone transitions decoded (52-byte records, arrival xyz +0x24, rotation +0x30); Varusaburosu arena entry (9530,0,10127). walk.tscn --quest starts the hunter there facing the monster (out\hunter\quest_start.png). Monster HP / stat tables: needs the live client (HP getter known) - static chase via set_actor_hp_encoded callers passes HP in registers.

- 2026-10-23 (loop): MONSTER TEST MODE built (engine commits aa6908e, c859b55): godot/monster_locomotion.gd (engine moves/turns the actor; idle/walk/run picked from actual speed with playback scaled to speed/clip travel; any clip can take over and then moves the monster by its own root travel; auto_roles() detects idle/walk/run for any monster), godot/monster_test.tscn (WASD + orbit camera, clip browser, Tab normal/enraged, P spring physics, R reset), launcher monster_test.bat. Verified: scripted drive log (walk 127 u/s, run 341 u/s, lunge travel 351 u/s), key-event test, 5 models (em130, em011, em011_b, em011_e, em001). Spring physics: STABLE over 60 s in the in-place setup (mean deviation 12-13 units, worst 49); the earlier crumple was the clip loop teleporting the springs (use in_place=true). Flames are BoneAttachment3D (0.000 distance to bone). Own VFX shaders in godot/shaders (heat_flame, heat_haze; a NaN from pow() of a negative made white blobs - clamp). Exports: out\varusaburosu_export, rathalos_export (em011, _b, _e), rathian_export (em001, _b). em001 = Rathian (green), em011 = Rathalos; em011_e looks fire-wreathed (Hardcore candidate, unconfirmed). Rathalos/Varusaburosu/Rathian share clip ids for idle/walk (same 48-bone rig family).

## 2026-10-23 - mhfsdt.bin
Traced the table behind `10afcfd0` to `dat/mhfsdt.bin` (load_mhfsdt_bin 10afcd10). Row 130 (Varusaburosu) has 19 groups x 8
pointers -> 0x28-byte records (id, kind, flag, three floats). Findings in spec/subsystems/monster_attacks.md.
Meaning of ids/groups still open (needs live trace). Hardcore Rathalos variant (em011_b vs em011_e) still to be confirmed by user.

## 2026-10-23 - em002 export
Exported em002 + variant em002_c (192 clips each, .glb ~59 MB each, render previews) to out/em002_export(.zip). Hardcore identity of the
variant unconfirmed (same open question as em011_b / em011_e). No look data (glow/flames) for em002 yet.

## 2026-10-23 - em006 export
Exported em006 + variants em006_b, em006_c (all clips, previews) to out/em006_export(.zip). Variant identity unconfirmed; no look data yet.

## 2026-10-23 - em004 export
Exported em004 + variant em004_b (all clips, previews) to out/em004_export(.zip). Variant identity unconfirmed; no look data yet.

## 2026-10-23 - em008 export
Exported em008 + em008_b (all clips, previews) to out/em008_export(.zip). Variant identity unconfirmed.

## 2026-10-23 - em009 export
Exported em009 + em009_b (all clips, previews) to out/em009_export(.zip). Variant identity unconfirmed.

## 2026-10-23 - em010 export
Exported em010 (no variants, all clips) to out/em010_export(.zip).

## 2026-10-23 - em012 export
Exported em012 (no variants, all clips) to out/em012_export(.zip).

## 2026-10-23 - em013 export
Exported em013 (no variants, all clips) to out/em013_export(.zip).

## 2026-10-23 - em014 export
Exported em014 em014_b (all clips) to out/em014_export(.zip). Variant identity unconfirmed.

## 2026-10-23 - em015 export
Exported em015 em015_b em015_e (all clips) to out/em015_export(.zip). Variant identity unconfirmed.

## 2026-10-23 - em017 export
Exported em017 em017_b em017_e (all clips) to out/em017_export(.zip). Variant identity unconfirmed.

## 2026-10-23 - em016 export
Exported em016 (all clips) to out/em016_export(.zip).

## 2026-10-23 - em018 export
Exported em018 (all clips) to out/em018_export(.zip).

## 2026-10-23 - em019 export
Exported em019 (all clips) to out/em019_export(.zip).

## 2026-10-23 - em020 export
Exported em020 em020_b (all clips) to out/em020_export(.zip).

## 2026-10-23 - em021 export
Exported em021 em021_b em021_c em021_e (all clips) to out/em021_export(.zip).

## 2026-10-23 - em022 export
Exported em022 em022_b (all clips) to out/em022_export(.zip).

## 2026-10-23 - em023 export
Exported em023 (all clips) to out/em023_export(.zip).

## 2026-10-23 - em024 export
Exported em024 (all clips) to out/em024_export(.zip).

## 2026-10-23 - em025 export
Exported em025 (all clips) to out/em025_export(.zip).

## 2026-10-23 - em026 export
Exported em026 em026_b (all clips) to out/em026_export(.zip).

## 2026-10-23 - em027 export
Exported em027 em027_b (all clips) to out/em027_export(.zip).

## 2026-10-23 - em028 export
Exported em028 em028_b (all clips) to out/em028_export(.zip).

## 2026-10-23 - em029 export
Exported em029 (all clips) to out/em029_export(.zip).

## 2026-10-23 - em030 export
Exported em030 (all clips) to out/em030_export(.zip).

## 2026-10-23 - em031 export
Exported em031 (all clips) to out/em031_export(.zip).

## 2026-10-23 - em033 export
Exported em033 em033_b (all clips) to out/em033_export(.zip).

## 2026-10-23 - em034 export
Exported em034 (all clips) to out/em034_export(.zip).

## 2026-10-23 - em035 export
Exported em035 (all clips) to out/em035_export(.zip).

## 2026-10-23 - em036 export
Exported em036 em036_c (all clips) to out/em036_export(.zip).

## 2026-10-23 - em037 export
Exported em037 em037_b (all clips) to out/em037_export(.zip).

## 2026-10-23 - em038 export
Exported em038 em038_b (all clips) to out/em038_export(.zip).

## 2026-10-23 - em039 export
Exported em039 em039_b (all clips) to out/em039_export(.zip).

## 2026-10-23 - em040 export
Exported em040 em040_b (all clips) to out/em040_export(.zip).

## 2026-10-23 - em041 export
Exported em041 em041_b em041_c (all clips) to out/em041_export(.zip).

## 2026-10-23 - em042 export
Exported em042 em042_b em042_c (all clips) to out/em042_export(.zip).

## 2026-10-23 - em043 export
Exported em043 em043_b (all clips) to out/em043_export(.zip).

## 2026-10-23 - em044 export
Exported em044 em044_b (all clips) to out/em044_export(.zip).

## 2026-10-23 - em045 export
Exported em045 em045_b (all clips) to out/em045_export(.zip).

## 2026-10-23 - em046 export
Exported em046 em046_b (all clips) to out/em046_export(.zip).

## 2026-10-23 - em047 export
Exported em047 em047_b (all clips) to out/em047_export(.zip).

## 2026-10-23 - em048 export
Exported em048 em048_b em048_e (all clips) to out/em048_export(.zip).

## 2026-10-23 - em049 export
Exported em049 em049_b (all clips) to out/em049_export(.zip).

## 2026-10-23 - em050 export
Exported em050 (all clips) to out/em050_export(.zip).

## 2026-10-23 - em051 export
Exported em051 em051_b em051_e (all clips) to out/em051_export(.zip).

## 2026-10-23 - em052 export
Exported em052 em052_b (all clips) to out/em052_export(.zip).

## 2026-10-23 - em053 export
Exported em053 em053_b (all clips) to out/em053_export(.zip).

## 2026-10-23 - em054 export
Exported em054 em054_b (all clips) to out/em054_export(.zip).

## 2026-10-23 - em055 export
Exported em055 (all clips) to out/em055_export(.zip).

## 2026-10-23 - em056 export
Exported em056 (all clips) to out/em056_export(.zip).

## 2026-10-23 - em057 export
Exported em057 em057_c (all clips) to out/em057_export(.zip).

## 2026-10-23 - em058 export
Exported em058 (all clips) to out/em058_export(.zip).

## 2026-10-23 - em059 export
Exported em059 em059_b (all clips) to out/em059_export(.zip).

## 2026-10-23 - em060 export
Exported em060 em060_b (all clips) to out/em060_export(.zip).

## 2026-10-23 - em061 export
Exported em061 (all clips) to out/em061_export(.zip).

## 2026-10-23 - em062 export
Exported em062 (all clips) to out/em062_export(.zip).

## 2026-10-23 - em063 export
Exported em063 (all clips) to out/em063_export(.zip).

## 2026-10-23 - em064 export
Exported em064 em064_b (all clips) to out/em064_export(.zip).

## 2026-10-23 - em065 export
Exported em065 em065_b em065_c (all clips) to out/em065_export(.zip).

## 2026-10-23 - em066 export
Exported em066 (all clips) to out/em066_export(.zip).

## 2026-10-23 - em067 export
Exported em067 em067_b (all clips) to out/em067_export(.zip).

## 2026-10-23 - em068 export
Exported em068 em068_b (all clips) to out/em068_export(.zip).

## 2026-10-23 - em069 export
Exported em069 (all clips) to out/em069_export(.zip).

## 2026-10-23 - em070 export
Exported em070 (all clips) to out/em070_export(.zip).

## 2026-10-23 - em071 export
Exported em071 em071_c (all clips) to out/em071_export(.zip).

## 2026-10-23 - em073 export
Exported em073 (all clips) to out/em073_export(.zip).

## 2026-10-23 - em074 export
Exported em074 em074_b em074_e (all clips) to out/em074_export(.zip).

## 2026-10-23 - em075 export
Exported em075 em075_b (all clips) to out/em075_export(.zip).

## 2026-10-23 - em076 export
Exported em076 em076_b em076_e (all clips) to out/em076_export(.zip).

## 2026-10-23 - em077 export
Exported em077 em077_b (all clips) to out/em077_export(.zip).

## 2026-10-23 - em078 export
Exported em078 em078_b (all clips) to out/em078_export(.zip).

## 2026-10-23 - em079 export
Exported em079 em079_b (all clips) to out/em079_export(.zip).

## 2026-10-23 - em080 export
Exported em080 em080_b em080_e (all clips) to out/em080_export(.zip).

## 2026-10-23 - em081 export
Exported em081 em081_b (all clips) to out/em081_export(.zip).

## 2026-10-23 - em082 export
Exported em082 em082_b (all clips) to out/em082_export(.zip).

## 2026-10-23 - em083 export
Exported em083 em083_b em083_e (all clips) to out/em083_export(.zip).

## 2026-10-23 - em084 export
Exported em084 em084_b (all clips) to out/em084_export(.zip).

## 2026-10-23 - em085 export
Exported em085 em085_b (all clips) to out/em085_export(.zip).

## 2026-10-23 - em086 export
Exported em086 (all clips) to out/em086_export(.zip).

## 2026-10-23 - em087 export
Exported em087 (all clips) to out/em087_export(.zip).

## 2026-10-23 - em088 export
Exported em088 (all clips) to out/em088_export(.zip).

## 2026-10-23 - em089 export
Exported em089 em089_b em089_c (all clips) to out/em089_export(.zip).

## 2026-10-23 - em090 export
Exported em090 em090_b (all clips) to out/em090_export(.zip).

## 2026-10-23 - em091 export
Exported em091 em091_b (all clips) to out/em091_export(.zip).

## 2026-10-23 - em092 export
Exported em092 em092_b (all clips) to out/em092_export(.zip).

## 2026-10-23 - em093 export
Exported em093 em093_b (all clips) to out/em093_export(.zip).

## 2026-10-23 - em094 export
Exported em094 em094_b (all clips) to out/em094_export(.zip).

## 2026-10-23 - em095 export
Exported em095 em095_b em095_c em095_e (all clips) to out/em095_export(.zip).

## 2026-10-23 - em096 export
Exported em096 em096_b (all clips) to out/em096_export(.zip).

## 2026-10-23 - em097 export
Exported em097 (all clips) to out/em097_export(.zip).

## 2026-10-23 - em098 export
Exported em098 (all clips) to out/em098_export(.zip).

## 2026-10-23 - em099 export
Exported em099 em099_b em099_e (all clips) to out/em099_export(.zip).

## 2026-10-23 - em100 export
Exported em100 em100_d (all clips) to out/em100_export(.zip).

## 2026-10-23 - em101 export
Exported em101 em101_b em101_c (all clips) to out/em101_export(.zip).

## 2026-10-23 - em102 export
Exported em102 em102_b (all clips) to out/em102_export(.zip).

## 2026-10-23 - em103 export
Exported em103 em103_e (all clips) to out/em103_export(.zip).

## 2026-10-23 - em104 export
Exported em104 em104_b (all clips) to out/em104_export(.zip).

## 2026-10-23 - em105 export
Exported em105 em105_b (all clips) to out/em105_export(.zip).

## 2026-10-23 - em106 export
Exported em106 em106_b (all clips) to out/em106_export(.zip).

## 2026-10-23 - em107 export
Exported em107 em107_d (all clips) to out/em107_export(.zip).

## 2026-10-23 - em108 export
Exported em108 (all clips) to out/em108_export(.zip).

## 2026-10-23 - em109 export
Exported em109 em109_e (all clips) to out/em109_export(.zip).

## 2026-10-23 - em110 export
Exported em110 em110_e (all clips) to out/em110_export(.zip).

## 2026-10-23 - em111 export
Exported em111 em111_e (all clips) to out/em111_export(.zip).

## 2026-10-23 - em112 export
Exported em112 em112_e (all clips) to out/em112_export(.zip).

## 2026-10-23 - em113 export
Exported em113 em113_b (all clips) to out/em113_export(.zip).

## 2026-10-23 - em114 export
Exported em114 (all clips) to out/em114_export(.zip).

## 2026-10-23 - em115 export
Exported em115 (all clips) to out/em115_export(.zip).

## 2026-10-23 - em116 export
Exported em116 (all clips) to out/em116_export(.zip).

## 2026-10-23 - em117 export
Exported em117 (all clips) to out/em117_export(.zip).

## 2026-10-23 - em118 export
Exported em118 (all clips) to out/em118_export(.zip).

## 2026-10-23 - em119 export
Exported em119 (all clips) to out/em119_export(.zip).

## 2026-10-23 - em120 export
Exported em120 (all clips) to out/em120_export(.zip).

## 2026-10-23 - em121 export
Exported em121 em121_e (all clips) to out/em121_export(.zip).

## 2026-10-23 - em122 export
Exported em122 (all clips) to out/em122_export(.zip).

## 2026-10-23 - em123 export
Exported em123 (all clips) to out/em123_export(.zip).

## 2026-10-23 - em124 export
Exported em124 (all clips) to out/em124_export(.zip).

## 2026-10-23 - em125 export
Exported em125 (all clips) to out/em125_export(.zip).

## 2026-10-23 - em126 export
Exported em126 (all clips) to out/em126_export(.zip).

## 2026-10-23 - em127 export
Exported em127 (all clips) to out/em127_export(.zip).

## 2026-10-23 - em128 export
Exported em128 (all clips) to out/em128_export(.zip).

## 2026-10-23 - em129 export
Exported em129 em129_e (all clips) to out/em129_export(.zip).

## 2026-10-23 - em130 export
Exported em130 (all clips) to out/em130_export(.zip).

## 2026-10-23 - em131 export
Exported em131 (all clips) to out/em131_export(.zip).

## 2026-10-23 - em132 export
Exported em132 (all clips) to out/em132_export(.zip).

## 2026-10-23 - em134 export
Exported em134 (all clips) to out/em134_export(.zip).

## 2026-10-23 - em135 export
Exported em135 (all clips) to out/em135_export(.zip).

## 2026-10-23 - em137 export
Exported em137 (all clips) to out/em137_export(.zip).

## 2026-10-23 - em138 export
Exported em138 (all clips) to out/em138_export(.zip).

## 2026-10-23 - em139 export
Exported em139 (all clips) to out/em139_export(.zip).

## 2026-10-23 - em140 export
Exported em140 em140_e (all clips) to out/em140_export(.zip).

## 2026-10-23 - em141 export
Exported em141 em141_e (all clips) to out/em141_export(.zip).

## 2026-10-23 - em142 export
Exported em142 em142_e (all clips) to out/em142_export(.zip).

## 2026-10-23 - em143 export
Exported em143 (all clips) to out/em143_export(.zip).

## 2026-10-23 - em144 export
Exported em144 (all clips) to out/em144_export(.zip).

## 2026-10-23 - em145 export
Exported em145 (all clips) to out/em145_export(.zip).

## 2026-10-23 - em146 export
Exported em146 em146_b (all clips) to out/em146_export(.zip).

## 2026-10-23 - em147 export
Exported em147 (all clips) to out/em147_export(.zip).

## 2026-10-23 - em148 export
Exported em148 (all clips) to out/em148_export(.zip).

## 2026-10-23 - em149 export
Exported em149 (all clips) to out/em149_export(.zip).

## 2026-10-23 - em150 export
Exported em150 (all clips) to out/em150_export(.zip).

## 2026-10-23 - em151 export
Exported em151 (all clips) to out/em151_export(.zip).

## 2026-10-23 - em152 export
Exported em152 (all clips) to out/em152_export(.zip).

## 2026-10-23 - em153 export
Exported em153 (all clips) to out/em153_export(.zip).

## 2026-10-23 - em154 export
Exported em154 em154_d (all clips) to out/em154_export(.zip).

## 2026-10-23 - em155 export
Exported em155 em155_b em155_c (all clips) to out/em155_export(.zip).

## 2026-10-23 - em157 export
Exported em157 (all clips) to out/em157_export(.zip).

## 2026-10-23 - em158 export
Exported em158 (all clips) to out/em158_export(.zip).

## 2026-10-23 - em159 export
Exported em159 (all clips) to out/em159_export(.zip).

## 2026-10-23 - em160 export
Exported em160 (all clips) to out/em160_export(.zip).

## 2026-10-23 - em161 export
Exported em161 (all clips) to out/em161_export(.zip).

## 2026-10-23 - em162 export
Exported em162 (all clips) to out/em162_export(.zip).

## 2026-10-23 - em163 export
Exported em163 (all clips) to out/em163_export(.zip).

## 2026-10-23 - em164 export
Exported em164 (all clips) to out/em164_export(.zip).

## 2026-10-23 - em165 export
Exported em165 (all clips) to out/em165_export(.zip).

## 2026-10-23 - em166 export
Exported em166 em166_d (all clips) to out/em166_export(.zip).

## 2026-10-23 - em167 export
Exported em167 (all clips) to out/em167_export(.zip).

## 2026-10-23 - em168 export
Exported em168 (all clips) to out/em168_export(.zip).

## 2026-10-23 - em169 export
Exported em169 (all clips) to out/em169_export(.zip).

## 2026-10-23 - em170 export
Exported em170 (all clips) to out/em170_export(.zip).

## 2026-10-23 - em171 export
Exported em171 (all clips) to out/em171_export(.zip).

## 2026-10-23 - em172 export
Exported em172 (all clips) to out/em172_export(.zip).

## 2026-10-23 - em173 export
Exported em173 (all clips) to out/em173_export(.zip).

## 2026-10-23 - em174 export
Exported em174 (all clips) to out/em174_export(.zip).

## 2026-10-23 - em175 export
Exported em175 (all clips) to out/em175_export(.zip).

## 2026-10-23 - em176 export
Exported em176 (all clips) to out/em176_export(.zip).

## 2026-10-23 - batch export finished
export_all.sh exported em001-em176 (169 monster zips in mhfz-engine/out, ~24 GB). em118 (pack has no motion entry) and em171 (0 clips) have no .glb: they need a clip-less static export path. Previews for models without clip id 1 (e.g. em077, em130) are missing; the .glb files are fine. Hardcore variant identity still unconfirmed.

## 2026-10-23 - static exports
em118 and em171 exported as static (0-clip) .glb after export_monster learned to skip an empty clip list. All em001-em176 models now have a .glb.
