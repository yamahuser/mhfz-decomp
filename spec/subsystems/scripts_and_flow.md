# Scripts, quests and top-level flow (subsystem agent "s_scripts")

Sources: decomp\*.c, plus direct DLL reads (jump tables) via pefile. Confidence tags: [H] read directly from code/disasm, [M] inferred from several call sites, [L] guess.
Status: first pass. Open questions at the end.

## 0. Corrections to earlier notes
1. `10ab4df0` is the **quest script VM** (one script per quest, run from the quest runtime update `10aa8da0`). It is not a cutscene interpreter. [H]
2. `10cf8f20` (44 KB) is **not a script interpreter**. It is a per-motion-id effect/SFX/hit trigger switch: `switch(*(u16*)(actor+0x32c))` over motion ids 0x3eb..0x4aa, called once per tick per actor (param_2 = actor/player record, param_1 = this/owner). Each case tests the animation frame/phase (`FUN_108ff650(frame_const)`, `actor+0xb0/+0xb8` = current frame/speed) and fires effects (`1143f4f0(effect_id, 0x80, scale)`, `114265d0`, `10cf7360`). Prelude: sets mask bits in `actor+0xb5c` from the weapon/stance bytes `actor+0x56c/0x56d`. Only reached via function pointer (no static caller). For a rewrite: model as data table {motion id -> list of (frame, effect id/sound id)}. [M]
3. The mode table at `0x11aa0574` (indexed by `DAT_1e8e35a0`, dispatched in `11405950`) is **not** the game mode machine. It is a 5-state **HTTP image/banner downloader client** (see section 6). [H]
4. The real top-level flow is the scene pointer `DAT_1edb98c4` / scene id `DAT_1edb98c0` plus the game-state block `DAT_1e7fff3c` (section 3). [M]

## 1. Quest script VM (`10ab4df0`, `void/short run_quest_script(player_rec, pc)`)
Called from `10aa8da0` (update_quest_runtime) each tick while quest phase `[q+0]==0` and `[q+0x22] != -1`. Returns the new pc, stored back to `[q+0x22]`; -1 = script finished. [H]

Program: `q = DAT_1e8001ec` (quest runtime). Code pointer `[q+0x58]`: array of **8-byte instructions** = 4 x s16 `{op, a, b, c}`. pc is an instruction index. Message/string table pointer `[q+0x5c]` (u32 offsets, added to base `DAT_1ed528f4`).

Execution model: the VM loops. Each handler either **continues** (executes next instruction in the same tick) or **ends the tick**. "End tick + advance" = the instruction is done, next tick resumes at pc+1. "End tick, no advance" = polling/wait (same instruction retried next tick). The Ghidra pseudo-C hides the `inc esi` before the shared tail, so read the table below, not the decomp, for advance behaviour. Return value = pc, except if checkpoint op 0x31 was executed in this call, then it returns the pc of that 0x31 op (so next tick restarts there) until op 0x32 clears it. [H]
After the loop (tail): handles quest ids 0x9d1d..0x9d23 (`10ff3dd0` special event), and a deferred check of flag `DAT_1ed52893==0x80`. [M]

Pre-loop (every call, even before the first instruction) [H/M]:
- if quest state `game+0x23fe == 2` (accepted, not started) and quest time `[q+0x10] >= 0`: handle the countdown announcements (time-left messages at the thresholds in tables `0x1187f2b0/0x1187f2c8`, `10ab17b0` formats "N minutes"), and select whether the timer ticks (`10ab33d0(flag)`). When `[q+0x10] <= 0` (time up): jump the script to the `0x1a` label whose id is `[q+0xa]` (timeout handler) or, if quest flag `[q+0x80]->+0x97 & 0x20`, to op 0x26; sets `[q+0xadc]=1`.
- pending jump requests: `[q+0xb]` (set by op 0x23; fires when `10ab4ab0()==1`) and `[q+0x143]` (set by op 0x2c; fires when `[q+0x144]!=0`): jump to label with that id and clear the request. Label search = first instruction with op 0x1a and `a == id`, execution resumes at label index + 1.

### Opcode table (op = first s16). C = continue same tick, E+ = end tick and advance, W = end tick/no advance until condition true, [H]=read from handler
| op | name (proposed) | semantics |
|---|---|---|
| 0x01 | set_objective_mode | `[q+0x160] = a` (u8: 1..4 clear-condition mode, see 4.3). E+ [H] (jumps to advance, ends loop? handler at 10ab5290 does inc+continue = C) |
| 0x02 | add_objective | `10ab39c0(a)`: find free slot among 3 at `[q+0x16c+8*i]`, store flags `a|0x10` (copy at `+0x18c`), id from regs si/di = b,c (`+0x170` s16 = id, `+0x172` s16 = value/target). C |
| 0x04 | add_time | `[q+0x10] += (u16)a` (quest timer, 30 ticks/s). E+ |
| 0x05, 0x1a | label | `0x1a a` = label id a; both are no-ops when executed. C |
| 0x06 | if_objectives_ok | evaluates `10ab3ee0(0)` / `10ab41e0()`; if either == 1 -> next instruction (C); else skip forward to the next op 0x07 (endif) and continue after it. i.e. `0x06 ... 0x07` block |
| 0x07 | endif | no-op marker (also the target of 0x06 skip). C |
| 0x09 | set_counter | `[q+0xc] = a`. E+ |
| 0x0a | wait_counter | `--[q+0xc]`; if `> 0` W (stay) else E+. With 0x09 gives "wait a ticks" |
| 0x0b | show_message | push string `table[a]` to the system message queue (`11355490`, ring of 0x14 x 0x214 at 0x1e375450). E+ |
| 0x0c | wait_area | W until `(u16)player[+0x7f8]` (that player's current area id) `== a`, then C |
| 0x17 | goto_saved | `[q+0x22]=[q+0x24]; pc=[q+0x22]`. C |
| 0x18 | wait_player_state | W until `player[+0x15]==4 && player[+0x14]==0`, then C |
| 0x1b | quest_success | `[q+0xa]=a`; big "quest cleared" sequence: system messages, notifies score/rank (`10a60510`,`10b9acd0`,`10aa17c0`,`1136e2e0`...), writes time left `[q+0x14]/0x708` minutes, sets `DAT_1edaae6a`, clears `[q+0xadc]`, sets event for network (`10ac1a90`...). Ends script run (returns from the VM). [M] |
| 0x1c | goto | jump to label `a` (index of label + 1). C |
| 0x1e | end_phase | `pc=-1`; `q[0]++`, `q[1]=0` -> quest runtime advances to phase 1 (ending countdown). E |
| 0x1f | quest_fail | `q[6]=6; game+0x23fe=6`; `pc=-1`; `10abff10()` finalize; clears `0x1ecb2c30[0x180]`; messages; |
| 0x20 | notify_event | `[q+0x26]=a`; `10aaa020`: queue network quest-event type 6 with arg `[q+0x26]` into `[q+0xac2..]`. C |
| 0x21 | wait_item_count | `10a96de0(a) (quest delivery/count lookup in the 30 x 8-byte table at player+0xa18: {id,count,..})`; W while result `< b` (signed) |
| 0x23 | set_jump_request | `[q+0xb] = a`. E+ |
| 0x24 | if_obj_value_le | `10ab4440(a)` (value of objective with id a, 0..2; -1 if none) `<= b` -> next (C), else W(no advance). |
| 0x25 | begin_ending | `game+0x23fe=5; q[6]=5`; message; sets event 0xa (network), `[q+0xadc]=1`. C |
| 0x26 | quest_start_marker | Entry point of the quest body. Also executed as instruction: resolves target monster (`[q+0x9c]` actor: `10aa4030`,`10aa0d70` -> `[q+0x140]`, per-monster table `[q+0x7b0+2*type]`), sets `q[6]=3; game+0x23fe=3`, sets bit `1<<(game+0x23f8 + 8)` in `[q+0x138]`, posts event 0xb, pc advances. C |
| 0x28 | if_hp_ratio / threshold | compares `[q+0x140] - a` against an obfuscated (rotate/xor with key `DAT_11a422c4`, 0x5ec0) value in the target actor (`actor+0x624`, `DAT_1edb768e[...]`). If less: skip to next op 0x29 (block `0x28 ... 0x29`); else store the decoded value back to `[q+0x140]`. Anti-cheat protected value. C |
| 0x2a | if_online_ok | `1085b7b0()==1`: if game state `23fe` not in 3..7 call `10ab3a40(0,0x200)`; C; else skip to op 0x2b |
| 0x2c | set_jump_request2 | `[q+0x143] = a`. E+ |
| 0x2d | wait_all_players_ready | W until `([q+0x138] & 0xf00)==0xf00` or player record `+0x328 != 0` or `game+0x25c8+slot == 1`; else E+ |
| 0x2f | set_timeout_label | `[q+0xa] = a` (label id used when timer hits 0). E+ |
| 0x30 | if_obj_value_gt_goto | `10ab4440(a)`; if `b < value` -> next (C) else goto label `c` (index of 0x1a with id c) +1 |
| 0x31 | checkpoint_set | remember this pc as resume point (see execution model). C |
| 0x32 | checkpoint_clear | forget it, `pc+1`. C |
| 0x33 | check_objective_complete | online mode: if both/any objective flags `&0x31==0x31` calls `10aa2430(1|2)` and jumps pc to -1 (finish). E |
| 0x34 | request_end_if_not_ended | if game state not in 3..7: `10ab3a40(0,0)` (finish quest through the common end path). C |
| 0xFFFF (-1) | end_of_script / success_entry | marks end; as executed op: `ctx flag 0x1ed52893=0x81`, resolves target monster as 0x26, sets `q[6]=3,23fe=3`, event 2. Used by `10aa60f0`/`10ab3ee0` as the "scripted quest start" jump target when there is no 0x26. |
| 0xFFFE (-2) | ending_handler_entry | entry of the ending sequence: `game+0x23fe=5; q[6]=5`, event 4 with `DAT_1e7ff234`; used as jump target when objectives are completed (10aa1650/10aa1700/10ab3ee0). |
Unknown / unhandled ops (0x00,0x03,0x08,0x0d-0x16,0x19,0x1d,0x22,0x27,0x29,0x2b,0x2e) : "W" (end tick, no advance) - used only as block terminators (0x29, 0x2b) skipped by the forward scans.
Op 0x1b/0x26/0x1f/0x25/0xFFFF/0xFFFE side-effects are heavy (UI messages, network packets); an engine rewrite should treat them as named quest events: `QuestStart`, `QuestClear`, `QuestFail`, `EnterEnding`.

## 2. Quest runtime object (`DAT_1e8001ec`, size 0xd40, checksummed by the main loop) [M]
| off | type | meaning |
|---|---|---|
| +0x00 | u8 | phase: 0 = script running, 1 = ending countdown / results, 2 = transition (quest cleared/failed handoff, sub 0..2), 3 = post |
| +0x01 | u8 | substate of the phase |
| +0x06 | u8 | quest status mirror of `game+0x23fe` |
| +0x08 | u16 | quest id (also `game+0x30`, `DAT_1ed7d418`) |
| +0x0a/+0x0b | s8 | timeout label id / pending jump label |
| +0x0c | i32 | wait counter (ops 9/10) |
| +0x10 | i32 | time remaining, **30 ticks per second** (0x708 = 1 minute of game time) |
| +0x14 | i32 | time limit (max) |
| +0x22/+0x24 | s16 | script pc / saved pc (-1 = none) |
| +0x26 | u8 | event argument |
| +0x2c | u32 | quest flags (0x400000 co-op target, 0x4000000, 0xc000000 final-stage...) |
| +0x58 | ptr | script (8-byte instructions); +0x5c ptr message offset table |
| +0x80 | ptr | static quest definition record (+0x2e u16 id, +0x97/+0x98 flag bytes, +0xc4 int) |
| +0x9c | ptr | target monster/actor (+3 = monster kind byte, 't'=0x74 special) |
| +0x138 | u32 | per-player done mask (bit i for slot i, bit i+4/+8 variants); +0x13c countdown |
| +0x140 | s16 | monster HP threshold register (obfuscated source) |
| +0x160 | u8 | objective mode 1..4 |
| +0x16c | 3 x {u32 flags, s16 id, s16 val} | objective slots; flags 0x01 present, 0x10 active, 0x20 reached, 0x40 failed/done-request, 0x100, 0x400 handled; second copy at +0x18c |
| +0x7b0 | s16[] | per monster-kind scratch |
| +0x914 | i32 | saved remaining time (used by results) |
| +0x930 | i32 | secondary countdown |
| +0xac2.. | event record {u8 code @ac2, u16 @ac4, u16 @ac6, u16 @ac8, u16 @aca} | outgoing quest event, sent with `10905390(6, slot)` (network) ; codes seen 2,4,6,10,11,12,13,16 |
| +0xadc | u8 | "event pending/flush" flag |
| +0x1dc..+0x1e4 | | secondary timer {area id s16, ..., time i32 capped 90000} |

Online flag `DAT_1ed52870` (non-zero = multiplayer), `DAT_1ed52951` (offline/solo-in-network flag). `10905390(type, slot)` = send quest event to server/other clients when online; `114e1d30` flushes. [M]

## 3. Game state block (`DAT_1e7fff3c`, 0x3ee0 bytes, checksummed) [M]
| off | meaning |
|---|---|
| +0x00 | top state (see 3.1) |
| +0x01 | quest-load phase 0..5 (dispatched in `1089b860`) |
| +0x02 | load step 0..7 in `1089a240` |
| +0x12 | load-complete flag |
| +0x14 | **current area/stage id (s16)**; `0x17b` and `0x187` get special handling (limiter, results) |
| +0x30 | quest id (s16) |
| +0x34 | int: quest/area category (0x47..0x4e = tutorial-like set) |
| +0x23f8 | local player slot index (0..3) |
| +0x23fa | party size |
| +0x23fe | quest status: 0/1 none, 2 accepted/preparing, 3 running, 4 cleared (final), 5 ending sequence, 6 failed (final), 7 aborted/retired, 8 cancelled/invalid |
| +0x23ff | non-quest-world flag (0 = quest mode; 1 = town/guild "free" mode, no quest runtime) |
| +0x25c8.. | per-player state bytes (value 1 = connected/alive?) |
| +0x3d0c | s16 countdown |

### 3.1 Top-level scene driver
Scene function pointer `DAT_1edb98c4`, scene id `DAT_1edb98c0` (8 = in-quest/world scene whose function is `10899d90`, alternatives `1089d790`, set at `108fcee0`). `10899d90(scene_rec)`: phase byte `[rec+8]` 0 = one-time setup, 1 = running; then `switch(*game)`:
0 = init (`10899fc0`, `11543120`), falls to 1 = load/run quest session (`1089b860`, below), 2 = `1089be10` (quest end / return to town: clears delayed queue, area exit), 3 = `1089c780`, 5 = `1089cb50` (calls `10b7acd0` frame pipeline), 6 = `10771490`+`1089ce60`, 7 = `1089cfc0`. [M]
`1089b860(game+1)`: 0 `1089a240` (quest/area load: picks quest id, creates runtime via `10aa4d60`, `10b738a0` reset players, steps 0..7), 1 `1089a7d0`, 2 `1089ab60`, 3 `1089b2e0` (calls scripted camera `1081fe90(1)`), 4 `1089b6d0`, 5 `1089b780`. [M]
`1080fe60(phase_rec)` is the gameplay-phase driver of another scene (phase byte `[rec+8]` 0..5 -> `108103b0`, `10810660`, advance, `10810bf0`, `10812630`, `10812ad0`; 100 character slots, camera, render passes). It is installed through a function pointer written at `1089a723` (inside `1089a240`'s neighbourhood, function `1089a240` itself loads it) so it is the in-quest tick of the scene. [L]

## 4. Quest runtime tick `10aa8da0` (called once per tick) [H/M]
1. Marks done-bits for players whose `game+0x25c8+i != 1` or whose input flags set; decrements `[q+0x162]`.
2. Phase switch on `q[0]`:
 - 0: if `q[6]` in (7,8) stop; if `q[6]==4` or `6` and so on; runs `10ab46b0`, `10ab3ee0(1)` (objective check, may jump pc to op -2), `10aa3f50`, **the script VM** `10ab4df0`, `10aa9e60`, `10aaa080`, `10aa8920`, `10aa8d50`; if quest flags & 0xc000000 -> `10aa1610`.
 - 1: results countdown: sub 0..6. sub 2 stores remaining time `[q+0x914]`; sub 4 does reward/rank bookkeeping (`10ac0210`, anti-cheat xor `DAT_1e76af1c ^ DAT_1e76a5cb` of remaining time); sub 5 counts `[q+0x10]` down (set to 300/1800/`105cf840(...)` ticks) printing "N minutes" messages; sub 6 when timer hits 0 -> `q[0]++`.
 - 2: wait for all players (bitmask `[q+0x138]`), final state 4 on success.
 - 3: determines final `game+0x23fe` = 4 (clear, `q[6]==4`) or 6 (fail) and posts the result event `11355280(3,3,slot)`.
3. Timer: `10ab33d0(n)` decrements `[q+0x10]` by n each tick unless paused; clamps >=0.
Quest status transitions: 2 -> 3 (`op 0x26`/`10aa60f0`) -> 5 (objectives done via -2 handler, `10aa1650`) -> 4 (clear) / 6 (fail: `op 0x1f`, timeout) ; 7 = retire (`10aa5fd0`); 8 = cancel (`10aa62b0`, `10aa62e0`). `10aa4d60` = quest initialisation (called from load step 0; picks quest definition via `1047a820` / `10682930` (id < 40000 or >=), copies difficulty flags `DAT_1ed7d3a0`, etc.).

## 5. Delayed-action queue (`10b42d40`, called each tick from `108e3f00`) [H]
Actually a **delayed spatial sound-effect queue**. Storage: header at `0x1e7ff760` (u16 flags bit0 = any active; byte `0x1e7ff762` = init state 0/1/2), 32 entries x 0x20 bytes starting `0x1e7ff764`. Entry layout (shorts unless noted):
| off | meaning |
|---|---|
| +0x00 | u16 flags: bit0 active, bit1 fired |
| +0x02 | s16 area id the sound belongs to (entry dropped if != current area `game+0x14`) |
| +0x04/+0x05/+0x06/+0x07 | s8 args: sound bank/id, sound id, channel..., passed to `114dd030` |
| +0x08 | 4 bytes: position pointer/payload |
| +0x10 | s16 post-fire countdown (entry freed at 0) |
| +0x12 | s16 pre-fire delay in ticks (decremented each tick; at 0 the sound is requested via `114dd030`, flag bit1 set) |
Enqueue `10b42ba0(entry*)` copies 0x20 bytes into the first free slot, sets flag0 and header bit0; duplicate check `10b42b50` compares (+2,+4,+5,+6). Producer `10b42bf0`. Whole queue cleared by `memset(0x404)` in `10b42e80` and quest end `1089be10`. Skipped when `[player_slot+0x1dc6bf4a]`!=0 or `DAT_1ed52895`!=0 (paused/cutscene). `114dd030(sound, pos*, bank, ...)` = 3D sound request (listener-relative via `DAT_1dc6b710`; volume curve from sound table `[DAT_1e77dcc4+0x548]` stride 0x14). Runs at tick rate: per-call decrement. [H]

## 6. "Client mode" table at 0x11aa0574 = HTTP image banner client [H]
`DAT_1e8e35a0` mode 0..4: handlers `11405200` (idle, 1 byte `ret`), `11405210` (start: calls vtable+0x10/+0x14 of request object `+0x184`, `+0x1c0=2`), `11405280` (evaluate HTTP status in `+0x188`: 200, 400/403/404, 500/503/600; retry counter `+0x1c4`<4 else give up), `11405450` (success: takes image blob pointer `obj+0xf4`, `11405780` decodes it into a texture slot `DAT_1e8119ec`, mode 4), `114054a0` (displaying, tiny). Entry `11405180(url)` starts a request when idle (`lstrcpy(DAT_1e8e33e0, url)`, mode 1). `114054b0` tears down. `11405950` runs per frame from `108f4150` / `1079e2d0` / `10b75150`: runs the mode handler, then draws the image centered (`114058d0`: x=(screen_w/2)-w/2, y offset 0x96 when not fullscreen flag `DAT_1e8e3598&2`). Not game logic: skip in a rewrite or replace with a banner fetch. 

## 7. Scripted camera / cutscene controller (`1081fe90(flags)`) [M]
Data: script pointer `DAT_11c4a0d4` (first byte 0 = none), current instruction ptr `DAT_11c4a0dc`, init flag `DAT_11c4a0d0`. 6 "channels" of 0x80 bytes at `0x11c49dd0` (type byte at +0x70), init handlers `PTR_FUN_118c93e8[i]`, per-tick handlers `PTR_FUN_118c9400[type]`. `1082f860` pulls next instruction, `1082f910(n)` is a delay/step check, `1082e3d0`/`1082c580` update. After channels run, if flag `DAT_1e774bd0&0x20` the eye/target override (6 floats at `DAT_11c4a100..114`) is written into the camera struct `DAT_1edaad60+0x80..0x94` (+0xb8 fov when flag 0x40) and `10baee10` rebuilds the view. Special cases: area `0x1cf..0x1d5` use preset table `0x118c93a0` (stride 0x18); quest id `0xcff0` calls `10820a70`. Callers: ~12 (quest phases, `1089b2e0`, `1089be10`, etc.). Per-tick: not to be repeated per rendered frame (see NOTES.md).

## 8. Open questions
- Exact names of the 6 camera channel types and their instruction set (needs table read at 0x118c93e8/0x118c9400 and 0x118c9390).
- Meaning of quest-flag bits in `[q+0x2c]` and `definition+0x97/0x98`.
- Which function installs `1080fe60`/`10899d90` into `DAT_1edb98c4` for each scene id; full scene id list.
- Contents of motion-event table in `10cf8f20` (per weapon): 137 cases x many sub-branches.
- Anti-cheat obfuscation (`DAT_11a422c4`, `DAT_1e76a5cb`) used for HP/time values.
