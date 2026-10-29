# Region R2 (0x10200000-0x103FFFFF) - subsystem summary

Engine-neutral notes from reading decompiled functions of the MHF-Z client DLL in the address range
0x10200000-0x103FFFFF (about 4,900 functions). Names live in `analysis/claude_names/r2.jsonl`.
Confidence is per-entry there; statements below are marked (verified) when read directly from code,
(inferred) when deduced from field usage, (guess) otherwise.

## 1. What the region contains (by address)

| Range | Content |
|---|---|
| 0x10200000-0x10277000 | "Action object" type modules (one module per object type id, 0xa0..0x1ba) - spawner, per-state dispatcher, per-subtype handlers, small helpers |
| 0x10277000-0x10312000 | Character action state machines for actor class 6 (hunter / main player class, inferred), plus smaller modules for classes 1 and 5 |
| 0x10313000-0x1033c000 | Per-class state accessors/handlers for actor classes 0x0a, 0x0c, 0x0d (reads/writes of the per-player extended block) |
| 0x1033d000-0x1033f000 | Accessors of the per-player block that are class independent (countdown sub-struct at +0x92c, +0x738 record, etc.) |
| 0x10340000-0x10344c00 | MSVC std::string implementation + a tiny HTTP/1.0 client used to upload screenshots (/api/ss/bbs/upload.php) |
| 0x10345000-0x103fffff | Game UI: screen draw/update functions (character creation, rankings, item lists, dialogs, hunter-rank cards, ...), event schedule helpers (0x1039c000-0x1039d000) |

## 2. Actor / character record (verified fields)

The 100-slot array at `DAT_1dc6b750` (stride 0x1050; slot index = player/NPC slot) is the "actor" record
passed as `param_1` to nearly everything in the 0x102xxxxx range. Offsets used here:

- +0x00 active flag, +0x03 **actor class** (observed 0,1,5,6,0x0a,0x0c,0x0d; class 6 owns by far the most handlers; semantic meaning of the number is a guess - possibly the controlled-entity kind/weapon class),
- +0x05/+0x06/+0x07 sub-state / step counters of the current action (handlers do `if(+5==0){init; +5=1}`), +0x08 u32 countdown (decremented each tick),
- +0x0c u16 player slot, +0x10 non-player / remote flag, +0x12 flag,
- **+0x14 action id, +0x15 action category**, +0x16/+0x17 previous id/category (every transition shifts the pair down),
- +0x448 u16 per-actor pseudo random seed advanced as `x = x*0xb0 mod 0xff53` on each transition (deterministic LCG - important for netplay sync),
- +0x7f8 owner session id (compared with `ctx+0x14`), +0xa0/+0xa4/+0xa8 orientation (s16 yaw scaled to 65536), +0xac/+0xb0/+0xb4 world position (float xyz), +0xb8 time scale,
- +0xc24 float animation speed multiplier (reset to a constant by each action change; scaled for class 6 when weapon style is 2/3),
- +0xd42 u8 style/mode selector (0..3). Global override `DAT_1ee08ce4` (enabled by `DAT_1ed52953`) replaces it - used by almost every handler to branch (style 0-2 vs 3),
- +0x678 ptr to model resource: resource+0x24 = part (bone/attachment) table with stride 0x1c0, local position at part+0x30, count at resource+0x20 (max 0x75 parts).

Global session context `DAT_1e7fff3c`: +0x12 flag (netplay/host), +0x14 u16 local session id, +0x23f8 local player slot,
+0x23ff demo/replay flag, +0x27 mode byte (4 = special mode), +0x34 current quest/area id. The idiom
"(query_mode==1 && ctx+0x12) || actor.slot == ctx.localSlot" = "this actor is controlled locally" appears hundreds of times;
state changes for local actors are broadcast with `109003b0` (sync packet) while remote actors only mirror.

Action transition idiom (inlined in dozens of handlers; also in `102d5ec0`): save previous (cat,id), write new pair, zero +5/+7,
advance LCG seed, reset animation speed, reset combo/input buffer bytes, notify net/local-input hooks.

## 3. Per-player extended block (verified layout skeleton)

`DAT_1e2a32f0`: 8 blocks x 0x9d0 bytes, indexed by actor slot (<8). Accessed only when the actor is non-remote and the session is not in demo mode.
- block+0x1c0..0x24f: class specific state union (cleared with a 0x90 byte memset on reset). Class 0x0c uses u32s at +0x1c0/+0x1c4/+0x1c8/+0x1cc, flags at +0x1d0, u16[] at +0x1dc/+0x1e0, sub-struct at +0x1f8; class 0x0d uses flags at +0x21c (bits 1,2,4,0x20,0x40,0x80,0x400,0x800,0x8000), u8 at +0x224, level at +0x226, nibbles at +0x22d, float timer +0x234, slot fields +0x23a..0x245, u16[] gauges +0x24a.
- block+0x2ac: s16[] timed status/buff counters, hard limit 18000 ticks (10 min at 30 Hz) - `apply_actor_timed_buff_value`.
- block+0x92c..0x9c8: a countdown/charge sub-struct (two float timers, stage int, u16 at +0x9c4).
- block+0x738: pointer-like record used by equipment checks (u16 id list at +0x30/+0x3e).

## 4. Action object pool (verified)

Pooled 0x200-byte objects (allocated by `111d4e20` under critical section `DAT_1e73ad88`, freed by `111d4ed0`):
- +0x04 u16 **type id** (0xa0..0x1ba, ~31 spawners found), +0x06 subtype/variant (bounded per type: 0x14..0x5c), +0x08 u8 lifecycle state: 0 init, 1/3 run, 2/4/5/7/9 ending, 6 free,
- +0x0e owner player slot, +0x28 per-type update dispatcher, +0x1c pointer to a per-type extension block (0xb0-0xd4 bytes, zeroed on spawn),
- +0x38..0x40 position, +0x44..0x4c origin position, +0x2c..0x34 copy of owner orientation, +0x90/+0x94/+0x98 s16 timers (window start/end), +0xac owner actor, +0xe0 attached sound/effect slot,
- +0xf2 u16 session id (must equal `ctx+0x14` for the object to emit effects locally), +0x158/+0x15c flag words (bit 1: cancel if owner action changes, bit 2: cancel if owner weapon changes, 8: ending, 0x2000: expired),
- +0x174 pointer to type definition record found by binary search in an id-sorted table (stride 0x1c, `DAT_1e77dcd4`, count `DAT_1e7ff40c`), +0x178 per-subtype record (stride 0x10).
The type definition holds hit/volume parameters (0x28-byte per-subtype record copied into the extension block).
Each type module provides a spawner `spawn_action_object_t<id>(owner, subtype, optional position)`; many thin wrappers add parameters
(`spawn_t0a7_object_at_part`, ...) and place the object at a model part position (`get_model_part_world_position`).
Which in-game skill / attack each type is remains unknown.

## 5. Schedule / event windows (verified)

`DAT_1e866cd8/cdc` hold the current server time (64-bit seconds); `DAT_1e81839c[3]` / `DAT_1e8183a8[3]` are start / end times of three scheduled event windows;
`is_event_period_active`, `is_any_event_period_active`, `get_event_period_calendar_info` evaluate them (calendar uses a +9 hour offset). A session flag byte (ctx+0x3e9d) can force events on.

## 6. UI drawing convention (verified from many callers)

UI code writes into a global draw-state struct (`DAT_1e3cbd64`): +0x0c s16 x, +0x0e s16 y, +0x10 float scale (quantised `(int)(scale*K)` clamped 0..6 into +0x64 = font size index), +0x18 u16 text style word (0x1212, 0x1414, 0x1616, 0x0e0e = cell size pairs),
+0x88 flags, +0x207d0 ARGB colour; then calls a text printer (`10b70cf0`, printf-style, name from other agents is probably wrong) or panel/sprite helpers (`106a3720` window panel, `106a3320` framed panel, `10489190` line).
Screen coordinates are computed relative to the screen centre: `x = screenW(DAT_1ebee5a0)*0.5(DAT_116038a8) - constant`. UI "screens" are numbered by `DAT_1ee268e0`
(0x8c, 0x16, 0x3b, ... ) with a state object (0xb000 bytes at `DAT_1ee268f0` for list screens). Text-input mode notifies the window procedure with
`PostMessageA(hwnd, 0x7e9, enable, 0)` (IME on/off). Strings of the UI come from a text table directory `DAT_1e77dccc` (offsets such as +0x244, +0x2b0, +0x10d4).

## 7. Screenshot upload / HTTP client (verified)

`10340900` builds a job (host, "dummy.jpeg", path "/api/ss/bbs/upload.php"); `10342750` wraps it with a "token" form field; multipart headers are built by
`10341540` (field) and `10341680` (jpeg file part); `10341820` builds the "POST ... HTTP/1.0" header; `10341a00` opens a TCP socket (gethostbyname, connect);
`10341ab0` sends body; `10342230` receives (30 s timeout, 16 KiB buffer) and `103413e0` strips the HTTP header. Engine-neutral: this is only a screenshot-to-BBS feature, not game networking.

## 8. Helpers worth re-implementing

- `get_model_part_world_position(entity, partIndex)`: rotate part local offset by the entity/part matrix, add entity position.
- std::string helpers (0x10340d00-0x10343200) are MSVC CRT - not game logic.
- `sjis_strstr`: Shift-JIS aware substring search (lead bytes 0x81-0x9f, 0xe0-0xfc).
- `find_item_combination_index`: 16-entry recipe-like table whose id pairs are XOR-obfuscated with 0xA55A (anti-tamper style obfuscation of static data).

## 9. Open questions

- Exact meaning of actor class values and which action ids map to which weapon attacks (needs the dispatch tables at runtime).
- Type id -> skill mapping of the ~31 action object modules.
- Other agents' names for `10b70cf0` (debug_log_printf_b) look wrong: in this region it is used as the main UI text print routine.
