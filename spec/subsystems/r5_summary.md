# R5 summary: region 0x10800000-0x109fffff (gameplay/actor/AI/UI)

Names: analysis\claude_names\r5.jsonl (later lines supersede earlier ones for the same addr).

## 1. Phase driver and character slots
- 1080fe60 gameplay_phase_driver: phase byte at +8 selects phase 0 (init: stage reset, 6 party slots get network handle + draw callback), 1 (wait), 2 (advance), 3 (scene/camera setup), 4 (selection-style input with 4 choices, cursor global), 5 (confirm/exit). Then 100 slot updates, camera, frame pipeline, then render passes.
- Character slot array: base 0x1dc6b750, stride 0x1050, 100 entries. +0 active, +1 enabled. Per tick: four "apply equipment skill effects" routines (1081e6a0/e030/e250/e390, alt 1081eab0): each piece (item record pointer, level) maps via sorted-id binary search (1081def0) to a 4-entry {skill id, value} list; each skill id selects an effect handler (type<10) from a table with 0x14-byte records. Results are cached per slot and re-built only when the equipped id changes.
- Global session block (DAT_1e7fff3c): +0x14 current stage id, +0x23f8 local player slot, +0x23fa party size, +0x23ff offline/training flag, +0x25c8 per-player ready flags, +0x34 quest type. Master data pointer DAT_1e77dcc4 (item table +0x50 stride 0x48, skill effect lists +0xad8, ...); monster data DAT_1e77dce0 (type table +8 stride 0x34, status records +0x10 stride 0x50 per difficulty, ...).

## 2. Actor (monster/NPC) object (stride 0xef0, array DAT_1ed7ad2c; ESI/EAX implicit this)
+0 active, +3 entity type (<=0xb0), +8 HP, +0xc id, +0x10 valid, +0x60 matrix, +0xa4 yaw (u16, 65536=turn), +0xac position, +0x1dc.. motion windows (stride 0x50) with +0x204 pause, +0x32c motion ids per layer (+0x342 count), +0x678 model resource (+0x24 part array stride 0x1c0, 0x76 parts, matrix+pos at +0x30), +0x7f8 stage id, +0x822.. states (+0x828, +0xa78 state, +0xaa6 enraged), +0x898/0x89c multipliers, status thresholds (+0x86a,+0x878,+0x880,+0xa74...) raised after each trigger up to 30000, aggro counters +0xb08[4] (30000 = full), +0x9f0 AI script set, +0xa5c current script ptr, +0x624 anti-tamper-encoded counter (rot + xor with per-actor key table and 0x5ec0).
Motion system: motion id = group*100+index; window test (108ff5c0/108ff650) used by thousands of event triggers (sound/effect spawn at part). Motion state records (12 bytes) come from per-type tables (108471c0) and are applied by 1084fe60.

## 3. Monster AI bytecode VM (run_actor_ai_script 108696d0)
~119 opcodes 0x01..0x9c,0xff with handlers at 10860dc0..10868680. Conditionals are opcode+sub-byte (0 test, 1 else, 2 end, 3 case end). Opcode families: IF on player masks/state/flags/angle/distance (0x14 ANGLE_CK, 0x22 NEAR_POS_CK), SWITCH on hp percent/state/stage, target selection (0x06,0x11-0x13,0x52,0x53), flag set/clear (0x0c/0x0d), random choice (0x0f/0x10/0x80), calls (0x81 CALL_CONTENTS, 0x82 CALL_SUB_CONTENTS, 0x07 MAIN_JUMP), loop (0x24), state set (0x40), end-of-script/patrol path handler 0xff. See r5.jsonl ai_op_* entries.

## 4. Quest context helpers
DAT_1e8001ec = current quest context (+8 id, +0x64 target entity list, +0x80 quest record). quest_target_role_matches (1087cb30) is inlined in dozens of functions as a 2/5-entry loop.

## 5. Other findings
- UI menus (1080xxxx-1083xxxx): hit-testing of rect lists (108f28b0/108f29b0), tweened values, text drawing 10802400, parameter table accessor DAT_1e77dcdc (chunk table of 0x20-byte entries).
- Network: build_and_queue_actor_sync_packet (109003b0) packet types 1..0xe+; sequence ids 108c72d0.
- Loaders by string: 108fba70 em%03d pac loader, 108fc5e0 npc bin, 1089ef20 stage pac, 108d6420 input config (dead_zone, operate_type, assign).
- Strings in decomp are symbols like s_NAME_<addr>: grep them for hints.

## Open
5.6KB 10842a20, 108728a0, 10849ce0 and the giant state machines 1099b8d0 (26KB), 108760a0, 108bc1b0, 109b2c70 unread. UI regions 1080-1083 only sampled.
