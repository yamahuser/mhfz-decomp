# Region r7 (0x10C00000-0x10DFFFFF): per-monster AI / state machines

Status: work in progress. Names are in `analysis/claude_names/r7.jsonl` (later lines supersede earlier ones for the same address).

## What this region is
Almost the whole region is **per-monster behaviour code**. Each monster species ("kind", the same number as the `emmodel\em%03d` pack, stored in entity byte +3) owns a contiguous block of code. The engine selects it through three per-kind function-pointer tables of 177 entries each (index = kind id):

| table (data VA) | role | signature (conceptual) |
|---|---|---|
| 0x118c3350 | on_spawn / init | (entity) -> resets actor, requests state (major 0, sub 1) |
| 0x118c3628 | ai_update (per frame) | (entity) -> polls hit/damage event, runs motion-event script, dispatches current state tick |
| 0x118c38f0 | request_state | (entity, major, sub, mode) |

Kinds that share a block are variants (subspecies / rare species): e.g. {2,36,71}, {3,69}, {4,5,32}, {7,50}, {8,34}, {9,23}, {12,25,70}, {104,112}. Unused kinds point at stubs 0x10164ca0 / 0x1083e260 / 0x1083e300. Kinds implemented in this region: 2/36/71 (tail), 3/69, 4/5/32, 7/50, 8/34, 9/23, 10, 12/25/70, 97 (T3 only), 100-105, 107, 109, 110, 112, 113, 115, 116, 117, 121, 122/174, 124, 125, 127, 128, 130, 134, 135, 137, 138.

## Monster state machine (engine-neutral)
- Two-level state: **major state** (entity+0x15, 0..8) and **sub-state** (entity+0x14). Previous values are kept in +0x17/+0x16. Inside a state, a step counter (+5) sequences enter -> wait-for-motion-end (+0x1d4 == 0) -> timer (+8, frames) -> exit.
- Canonical default: **(major 0, sub 1) = idle**; many tiny wrappers ("return to idle") set a dirty flag then request it.
- `request_state(entity, major, sub, mode)`: (1) optional HP-threshold interrupts that rewrite the requested state (e.g. HP < 40% / 70% forces an enrage-style special move, stage kept in a rage/phase byte near +0xcc4); (2) dispatch on major to a per-major *enter* handler, which loads the per-kind action parameter row (table 0x118c5760[kind*10] + sub*0x20 -> entity+0xa00..), sets timers, then commits via a shared commit routine (new RNG seed in entity+0x448, flag +0x7cb). `mode`: 0 = locally chained, 1 = fresh AI decision, 3/4 = originated from network replication (replicas with +0xab3 != 0 ignore modes 3/4 from the local AI).
- Major 5 with sub 3: adopt a synchronisation snapshot from the network (position, yaw, owner id copied from a pending record). Major 6/7: dead / removed variants.
- Only the **host** (entity+0x7f8 == local player id at session+0x14) spawns effects/projectiles; replicas (+0xab3) just follow synced state. This matters for any rewrite: authority = quest host.
- Per frame (`ai_update`): poll an event code (shared routine, ~5.6 KB) -> map event codes to state requests (flinch, knock-down, death, capture...) -> run **motion-event script** -> dispatch tick of current major/sub -> decrement misc timers.
- **Motion-event scripts**: the very large functions (e.g. 0x10cf8f20 44 KB, 0x10c84c90, 0x10c98fe0, 0x10c4ebe0, 0x10c0a130, 0x10c2a380, 0x10dc8a90) are `switch(current motion id)` -> windows of animation time `[start,end]` (tested by a shared helper) -> spawn effects, sounds, projectiles ("action nodes"), hit volumes. Motion ids >= 1000 mean the second animation layer (id-1000 indexes the same table).
- **Scheduled effect slots**: 5 records x 0x14 bytes at entity+0x510 (state, id, origin xyz); each id indexes a keyframe list `{u16 frame, u16 type, u16 arg}` terminated by 0xffff (type 1 = positional SE, 2 = sound for random target...).

## Entity ("actor") record fields seen in this region
+0x00 active; +0x03 kind; +0x05 step; +0x08 timer; +0x0c slot idx; +0x14/+0x15 sub/major; +0xa4 yaw (0x10000 = 360 deg); +0xac/b0/b4 position; +0xb8..c0 scale; +0x1dc motion time, +0x1e0 per-tick advance, +0x1d4 finished flag; +0x32c motion id; +0x410 interrupt/reaction mode (0 normal, 2 = forced); +0x45c..0x464 accel, +0x468..0x470 local velocity (rotated by yaw each tick); +0x510 effect slots; +0x534 flag word; +0x624 / +0x6bc obfuscated HP / max HP (rotate + xor with per-slot key; anti-cheat), +0x678 model resource (bone table at ->0x24, stride 0x1c0, bone position at +0x30), +0x708 ground height; +0x7f8 owner player id; +0xa29 needs-sync flag; +0xab3 is-remote-replica; +0xb20 animation speed multiplier (1.0 default); +0xc86 speed/level scalar; +0xc94 move duration; +0xcc4.. rage / phase stages.
Shared helpers (outside region): 0x1084fe60 select motion-table entry; 0x108ff650 "is current motion time inside window"; 0x10848420 part position; 0x10842a20 event poll; 0x10aa0d70/0x10aa0ce0 decode HP/max HP; 0x1087cb30/0x1087cde0 "is kind X active in quest list (mode)".

## Tooling note
Names marked "structural" were derived from switch tables (T2 switch on +0x15, T3 switch on major) and are reliable about *which state* the function serves, but say nothing about gameplay meaning (e.g. what attack sub 0x2c is).
