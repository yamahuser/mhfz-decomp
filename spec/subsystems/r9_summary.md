# Region 0x11000000-0x111FFFFF: player weapon-class state machines, action nodes, effect helpers (r9)

Names: `analysis/claude_names/r9.jsonl`. This region continues the r8 region (0x10E00000-0x10FFFFFF): same architecture. Confidence is honest; structure is solid, per-move semantics mostly NOT decoded. Some addresses appear more than once in the jsonl: the LAST entry wins (later entries are corrections).

## 1. Weapon-class modules ("bands")
* At least 13 further modules (call them X1..XD here; r8 used A..U) each implement the player action state machine for one actor class group. Each has a dispatcher `set_state(actor, kind, id, mode)`:
  X1 11015070, X2 11041b50, X3 110719a0, X4 110967d0, X5 110c12d0, X6 110ddbd0, X7 110f6140, X8 1110c640, X9 1112fbe0, XA 11142f20, XB 11169f30, XC 11178b60, XD 1119b920 (+1119c160 variant), plus 1117ef60 (smaller). Probably the 14 weapon types plus style variants (unverified).
* Dispatcher skeleton: if actor+0xab3 (remote/network-driven) and mode is 3/4 ignore; else refresh replication snapshot (10869350) and load a parameter set (10853780); switch on `kind` 0..4 to per-kind handlers (kind 0 = return-to-neutral/cleanup, 1 = movement, 2 = mid, 3 = large attack set, 4 = consumable/status); kind 5 = post-hit hook (10aa6aa0/10aa6b00); default commits through 10850d70 (reseeds a per-action LCG x*0xb0 mod 0xff53 into actor+0x448).
* "begin idle" wrappers per module: set flags +0x50e/+0x4e3/+0xab2/+0xa29, reset +0xb20 speed scale to 1.0 and phase +0x410, tail-call the dispatcher (e.g. 11009a90, 110244b0, 1109b040, 1114fb80).
* Per module: `on_action_end_by_id` switch (calls shared buff-slot cleanup 10857xxx), `tick_update` (counters from motion frame +0x1e0, two sub-state flag bytes), `set_substate(byte)`.
* Giant per-module functions: (a) *motion event scripts*: `switch(actor+0x32c motion id)` with hundreds of motion-window tests (108ff650) that spawn effects/sounds/screen shake at frames (e.g. 110d6510, 1118b340, 11162ae0, 11173110, 111068f0, 110ef490, 1113f950, 111265a0, 110825a0, 1107aee0, 1106cbd0, 11013260); (b) *motion sound schedule setup* tables (e.g. 11020e20): repeated calls 1085cce0(frame, sound id, kind).

## 2. Actor record (stride 0x1050 / 0xef0 variants; 40-entry table at DAT_1ed7ad2c with stride 0xef0 is seen in several scans)
+0 active, +3 class id byte (ASCII-like 'P','Q','T','o','[','|' ...; indexes tables at DAT_1e77dce0), +0xc id u16, +0x10 is-player, +0x14/+0x15 action id/category, +0xa0/0xa4/0xa8 rotation (+0xa4 = yaw, 16-bit wrap), +0xac..0xb4 world position, +0xb8 scale, +0x1dc.. motion windows (stride 0x50), +0x204 windows disabled, +0x32c motion id (+1000 variant), +0x410 phase, +0x448 per-action random word, +0x624 / +0x6bc HP encoded twice (rotl5 / rotl3 of hp XOR key table XOR 0x5ec0: anti-tamper; alive test = decoded > 0), +0x678 model res (+0x24 part table, stride 0x1c0, 0x76 parts, pos xyz at +0x30), +0x7f8 area generation (compared with *(DAT_1e7fff3c+0x14) before any effect), +0xab3 remote flag, +0xb20 speed scale, +0xc86/0xc94/0xc9f gauge, +0xd7c sub-object with virtual methods 0xa44/0xa4c.
Per-type parameter tables: `*(DAT_1e77dce0+0xc) + type*0xc0 + 0xb0`, 0x28-byte records, 200 columns (accessors 111a5080/111a5010/111a4fc0 - 3000+ callers).

## 3. Controller class (111a8xxx-111a9xxx)
Thiscall methods on a controller object: this+0 vtable (slots 0xa38 request_action(kind,id,mode), 0xa60, 0xa74, 0xaa8 spawn-at-position), this+4 = actor record. Helpers: part position, spawn effect with offset/lifetime, yaw-turn over a motion window (111a8510), is-frame-in-range (111a8250).

## 4. Action nodes (game event objects)
Allocated by 111d4e20 from a free-pointer stack, linked in a doubly-linked active list (head DAT_1ecb1660; lock DAT_1e73ad88), each with a buffer block from a 0xA00-byte occupancy map (DAT_1ec9d740, blocks of 0x200 at DAT_1ed528c0; alloc 11353f70, free 11354020). Node fields: +4 type (0,1,2,3,4,5,7,8,9,0x9a,0x1fb), +6 action id, +8 substate (0 init, 1 run, 3 finish, 6 dead), +0x28 per-type callback (dispatch by substate), +0xac owner actor, +0x38..0x40 position, +0xf2 generation. Many `queue_actor_action_node_typeN` producers fill them from the owning actor. Type 8 (111e97b0 -> 111e9a80 init, 111eb5e0 update 22 KB, 111f10f0 finish) is the largest. Effect objects (11405d70/11405d10) and sound/light slots (10b8f620, table DAT_1ecde5e0 stride 0x20) are parallel pools.

## 5. Other findings
* 1082d680: screen-shake/rumble request record (DAT_11c4a3c8..); 11130bb0 writes a similar record.
* Local LCG state DAT_1ed5f2a2 (x*0xb0 mod 0xff53) used for cosmetic randomness; DAT_1ed5f2a0 for gameplay.
* Unknown: weapon identity of modules; meaning of 10857xxx buff helpers; kind semantics.
