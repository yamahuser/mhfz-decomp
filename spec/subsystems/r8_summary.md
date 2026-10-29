# Region 0x10E00000-0x10FFFFFF: player actor / weapon-class state machines (r8)

Engine-neutral summary of what this ~1.9 MB code region does. Names live in
`analysis/claude_names/r8.jsonl` (one JSON per function). Confidence is
honest: structure is solid, per-move semantics are mostly NOT decoded.

## 1. What the region is

The whole region is **per-weapon-class (or per-style-group) player action state machines**.
There are at least 21 independent "modules" (I labelled them A..U locally; letters are
mine, not the game's). Each module is a C++-style class with a very large vtable
(controller slot `+0xa38` = `set_state`, so the vtable has >600 virtual methods;
most per-move functions have 0-1 static callers because they are reached through it).

Module dispatcher (the "set_state" entry) and the address span of its callers:

| Mod | set_state | callers live in | notes |
|-----|-----------|-----------------|-------|
| A | 10ec2a40 | 10e01xxxx-10e0axxx, 10ec1-3 | classes incl. 0x2b '+', 0x7c '|' |
| B | 10eea7b0 | 10ec5-10ee9 | |
| C | 10f0e990 | 10efe-10f09, 1019f/101a0 | class 0x11 |
| D | 10f303a0 | 10f18-10f30 | tracks a sub-object at actor+0x519 |
| E | 10f4e970 | 10f32-10f4e | class 0x15 |
| F | 10f75ea0 | 10f68-10f75 | |
| G | 10f8d730 (6 KB) | 10f5a-10f8d | class 0x30 |
| H | 10fa0fe0 (7.6 KB) | 10f9e-10fb5 | |
| I | 10fe2630 | 10fc4-10fe1 | class 0x41 'A'; stance modes in actor+0x410 |
| J K L ... | 10ec0a20, 10ef2cb0, 10f5ce40, 10f10090, 10f649a0, 10ff4680, 10fec720, 10ed6d00, 10e1f4b0, 10e91480, 10e61660, 10e15610 | smaller modules/controllers | |

Which game weapon each module is has NOT been identified (no strings). They are
probably the 14 weapon types plus style variants, but this is a guess.

## 2. set_state contract

`set_state(actor, kind, id, origin)`:
* `kind` 0..9: transition category. Kinds 0-4 each have a handler per module
  (kind0/kind1/kind2/kind3/kind4); kind 5 = post-hit/knock-back style hook
  (sub-id 3/4 and 10aa6aa0()==1 -> 10aa6b00), kind 8 sub-id 0x98 -> 10aa2840.
  Kind 4 handlers switch on `id` and run "side effect" helpers (10857xxx family).
* `id`: sub-state / motion state number (meaning per module).
* `origin` 3 or 4 with remote actor (`actor+0xab3 != 0`) => request ignored
  (remote actors are driven by the network; local actors call 10869350
  to refresh the replication snapshot).
* Handlers end with `10850d70(kind)` = commit/broadcast state change
  (when `DAT_1ed52870==0` it advances a local LCG `x*0xb0 mod 0xff53`, stores
  the seed in `actor+0x448`, and forwards to 10a7ff00).
* "begin state" prologues (wmX_begin_state_prologue) reset `actor+0xb20`
  (float, reset to `DAT_1199cb64`), `+0x410` (stance mode 0/1/2),
  `+0x4e3`, set `+0xa29`/`+0x50e` flags and call the dispatcher.

## 3. Actor (player character) record, offsets seen in this region

| off | meaning (confidence) |
|-----|---------------------|
| +0x00 | active byte; +0x01 enabled |
| +0x03 | class/style id 0..0xb0 (>0xb0 clamps to 1 in tables) selects rows in tables at `DAT_1e77dce0` (struct: +8 stride 0x34, +0xc stride 0xc0, +0x14, +0x28 stride 0x5a rows) and `PTR_DAT_118c5760`/`PTR_DAT_11a4e9c0` |
| +0x08 | countdown / duration int written by many states (e.g. 0x1e-gauge*k) |
| +0x0c | ushort index, +0x10 byte is-player flag |
| +0x14/+0x15 | action type / phase bytes of the current action |
| +0xa4 | yaw as 16-bit angle (0..0xffff, 0x8000 = half turn) |
| +0xac,+0xb0,+0xb4 | world position x,y,z |
| +0xb8 | scale float |
| +0x1dc..+0x204 | motion timing windows, 0x50 bytes each: start float, length float, +0x1e8 cap, +0x1ec flag; `+0x204` != 0 disables windows (108ff650 tests "time inside window N") |
| +0x32c | current motion/item id |
| +0x410 | stance mode (0/1/2/4) |
| +0x678 | model/motion resource; `res+0x24` = attach point table, 0x1c0 stride, up to 0x75 points, xyz at +0x30 |
| +0x7f8 | owner network player id (compared with `*(DAT_1e7fff3c+0x14)` = local id; effects/sound are only spawned for the locally owned actor) |
| +0x880..+0x893 | pending consumable effect (type +0x892: 1,2,4,5,7; flags +0x893) used by 10857xxx helpers |
| +0xa29,+0x50e | state flags |
| +0xab3 | actor is remote (network driven) |
| +0xb20 | float reset on every state entry |
| +0xc86 | ushort gauge (max from table), +0xc94 float gauge value, +0xc8d active, +0xc9f mode |
| +0xcc4,+0xcc5 | gauge bytes 0..100 |
| +0xd18 | 9 shorts of equipped ids |

Local player manager `DAT_1e8001ec`: +0x64 = list of bound ids, +0x80 =
equipment record (+0x91, +0x98 flags 0x80/0x2000, +0xb4.. slot states).
`DAT_1e7fff3c`: global session (+0x14 local player id, +0x34 style group, +0x23f8 slot).
`1087cb30(id, state)`: "does the player have id bound with button state"; used 1.9k times.

## 4. Shared helpers used everywhere (outside region, named by role)

* `108ff650(window, actor, time)` in-window test (callers 20k).
* `1085cbd0`/`1085cc60` emit sound/effect at an attach point (effect id, attach idx in EAX).
* `10848420` fetch attach point xyz; `1143f4f0`, `10b44420` emit effect/sound variants.
* `114dd030` spatial sound request (listener relative).
* `10855830` yaw16 from two points; `108e4910` build rotation from 16-bit angles.

## 5. Open questions
* Mapping of modules A..U to real weapon types; meaning of `kind` values.
* Meaning of the `10857xxx` helpers (consumable/buff application?).
* Vtable layout (where each module's vtable lives in .rdata).

## 6. Additional structure found (later pass)

* **Per-tick module update** (vtable entry, no static callers): `wmX_actor_tick_update` (e.g. 10e0ab70, 10ed0b00, 10f09330, 10f279a0, 10f45e10, 10f71ba0, 10fb5bf0, 10fd6930). Common prelude: 10858c80 (status/timer tick), 10858420, 108585b0; then module-specific helpers and virtual calls (+0xa60, +0xa68, +0xabc..+0xaf0). Smaller modules poll `10842a20` for an event code (hit/reaction) and issue `set_state(kind 5/4, id, origin 3)`.
* **Per-frame movement integrator** per module (`wmX_apply_motion_velocity`): rotates local velocity (+0x468..0x470) by yaw16 (+0xa4) and adds to position (+0xac..0xb4) when stance mode +0x410 is 2 (1 or 2 in module I); motion sub-effects initialised by `wmX_init_motion_substate` (state byte, flags +0x55d/+0x55e, counter +0x560).
* **Move event scripts**: ~155 small functions (`move_script_*`) test frame windows (108ff650) and fire effects/sounds; frame numbers are float globals. Large `*_motion_frame_event_table` functions do the same for whole modules.
* **Motion timelines as data**: `m*_register_motion_event_timeline` (switch on motion id 0x3e9.., calls 1085cce0(frame,id,..); random-range pick via 10b430f0) and `m*_motion_sfx_timeline` (switch on motion id, triples frame/sfx/attach via 10ec35f0 family). These embed per-motion sound/effect timelines (e.g. 10ec3740, 10ed1910, 10ef31d0, 10f13810, 10f76570, 10fe2d90) -- extract per case for a data table in a rewrite.
* Timers decrement by 2 per tick in some modules (10f481e0): units are 1/60 s while logic ticks at 30 Hz.
* Actor +0xb20 appears to be the motion playback speed scale (1.0 = DAT_1199cb64); +0xb71 a percent bias (100 nominal); window times are scaled by it.
* Obfuscated health: ushort at actor+0x624 rotated/XORed with per-slot key table (10f4d360, 10f0a960).
* Class motion table: `DAT_1e77dce0+0xc` -> per-class pointer (stride 0xc0) to <200 entries of 0x28 bytes; +0x20/+0x22 shorts are start/end frames.
* Effect emitters: 1143f4f0/1143f3f0/114265d0 spawn pooled effect objects (11405d70) only for the locally owned actor; 1124c160 spawns type-0x93 world objects under critical section DAT_1e73ad88.

## 7. Coverage
~3280 functions in the region have an entry in r8.jsonl. About 150 are hand-read (conf 0.4-0.6); ~2800 are auto-classified (conf 0.2-0.3, names `mXXXX_<category>_<addr>` from call-set/literal features: move_phase_script, move_window_script, move_event_script, motion_update, action_predicate, state_transition_helper, id_switch_helper, effect_spawner, helper). Treat auto entries as routing hints only.
