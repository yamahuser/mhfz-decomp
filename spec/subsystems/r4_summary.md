# Region r4 (0x10600000-0x107FFFFF) - subsystem summary

Status: partial pass (about 156 distinct functions named in analysis/claude_names/r4.jsonl; later lines supersede earlier ones for the same address, e.g. 107ac7c0). Engine-neutral notes; confidence is moderate, many names are inferred from callee sets and data access patterns.

## What lives in this region
Almost entirely game-specific logic, not engine/library code: menu and HUD screens, town-NPC dialogue, shops/inventory, per-character action state machines, mini-games (Mezeporta Festival), and asset-load request helpers. Roughly 50% of functions are single-caller screen/state handlers (one per menu page or event); the few hubs with hundreds of callers are small helpers.

## Global structures discovered
- Session struct `DAT_1e7fff3c`: +0x14 current area/quest id (u16, by far the most used field), +0x23f8 local player slot index, +0x23ff online flag, +0x3c item pouch (224 x 8 bytes: u16 id, u16 count, 2 x u16 extra), +0x28ef.. progress bit-flags (read via test_save_flag_bit), +0x28eb flag block (0xF0 bytes mirrored to player +0x1fc64), +0x294e/+0x29b5 companion counters, +0x29a5 packed 5 bit-fields, +0x3264 per-player name-hide mask.
- Local player save struct `PTR_DAT_11a3ee2c` (about 0x24cd4 bytes): +0x60 money (XOR-obfuscated with key `DAT_1edb9ba0`), +0x1ff14 capped (9,999,999) currency counter shown as "Gz", +0x1fc64 daily block, +0x1fda6, +0x22d08 per-area selection record, +0x23b88 another counter shown as "Gg", +0x1f6c6 selected item index, item entries 0x10 bytes (+0xd5 type 6 weapon / 7 armour, +0xd6 id).
- Master data root `DAT_1e77dcc4`: +0xfc item table (stride 0x24, ids up to 0x413c: +3 max stack, +0xc price, +0x16 usable flag, +0x1c category, +0x1e currency selector), +0x7c weapon table (stride 0x34), +0x80 armour table (stride 0x3c), +0x884 file-name tables for "load_*" data.
- Text/string root `DAT_1e77dccc`: array of pointers to string tables (+0x244 common words, +0x40 message table of 8-byte {style, text*} entries, +0xaac, +0x7e4, +0x7e0 ... menu pages).
- Character slots (0x1050 bytes, 100 at 0x1dc6b750; a 16-entry second array at 0x1e2a8170): +0x0c owner player index, +0x10 NPC/remote flag, +0x14/+0x15 action id/sub-id (previous in +0x16/+0x17), +0x5 phase byte, +0x32c current motion id (group*100+index, +0x32e = layer-2 motion = +100), +0x324 duration/2, +0x31c start frame, +0x448 per-action random seed (16-bit LCG x*0xb0 mod 0xff53), +0xa4 facing angle (16.16-style wrap 0x10000), +0xb7c name string, +0x418 action flag word.
- Actor/NPC table `DAT_1ed7ad2c`: 40 entries x 0xef0 bytes: +0 active, +0x510 id (NPC type), +0xac/+0xb0/+0xb4 position, +0xbc collision radius, +0x51c waypoint array pointer, +0x55c waypoint index, +0xb20 time scale. Waypoints are 5-dword records (xyz, action id, extra); routes can switch by in-game time of day (`DAT_1ee24964` seconds, split at 0xa8c0 = 12h; day = 86400 s).
- Text renderer context `DAT_1e3cbd64`: +0xc x, +0xe y, +0x18/+0x19 glyph cell w/h, +0x64 scale tier 0..6, +0x207d0 ARGB colour. UI is laid out for 640x480 and centred on the real backbuffer (`DAT_1ebee5a0` x `DAT_1ebee59c`).

## Subsystems
1. NPC dialogue/script engine: `start_npc_dialogue` (10726640) selects the entry node by evaluating per-NPC condition lists (flags, clock), `update_npc_dialogue_node_input` (10726a50) runs node types (yes/no, wait, jump), `execute_npc_dialogue_action` (10726de0) applies the node's action (buy, give item...). Tables at 0x118e4d10/14/18/1c indexed by NPC id.
2. Message windows: `open_message_window_with_text` (1079dc70) lays out, `draw_message_window` (1079e2d0) renders, `run_message_box_state_machine` (107ca5f0) handles flow and results; shared state in `DAT_1edf9fb0`/`DAT_11c3bb..`.
3. Menu primitives: cursor step helpers with wraparound and sound (10718140/1071822x/10718290/107183b0), panel frames by style (106a3320), sprite blit (106a3720), counters (106a2b80), amount badges (Gz/Gg/RP), pulsing highlight.
4. Inventory/shop: pouch add (106d68e0), price calc (106f94d0), affordability (1061f600), purchase execution (106f84b0), discount/charge (106f7b90/106f7c50), item icon with overlays (106fd0c0).
5. Character state machine: begin_player_action family (106aafa0, 106a8850), set_player_motion (106a8390/106a82d0), update_player_slot_controller (106b5140), position broadcast (106efbd0), player block sync to server (107a0c50).
6. Asset loading (relevant to HD injection): helpers build file names then read through the pack layer into tracked malloc buffers (`DAT_1e892f98`, 0x200 entries) and upload textures into 0x80-byte texture slots (0x500 slots). Names seen: `weapon\w<letter><NNN>.bin`, `effect.bin`, `mytra.bin`, `my_gallery\*.bin`, `npc\npc13p_NN.txb`, `npc\n%02u_c%04u.bin/.txb`, `stage_hd_som_NNN.pac` / `stage_hd_sef_NNN.pac` (HD file tried first, fallback `stage_som`/`stage_sef`), `load_um_NN.bin`, `load_us_NN_NNN.bin`, `load_NNN_NN_NNN.bin`, `sound\<bank>` (bank names from a table at 0x11879468; chosen by area id), `others00.txb`, `ryoudan_*` (guild resources), `lobby/mezfes_minigame/*`. JKR-compressed files are detected by the magic 'JKR\x1a'.
7. Mini-games (Mezeporta Festival, 0x10730000-0x10780000): share a 0xb000-byte work area at `DAT_1ee268f0`, result screens via add_result_screen_line (max 5 lines).
8. Networking touchpoints: packets sent only when online (`PTR_DAT_11a5358c[0xcf6c]`/session+0x23ff); player data block (0x180 bytes) sent as type 3 when changed, position as type 6.

## Open questions
- Which currencies map to +0x60 (XOR), +0x1ff14 (Gz), +0x23b88 (Gg), `DAT_1e506968` (RP).
- Meaning of area-id group {0xca,0xcb,0xcc,0xce,0x1bd} (special event areas, own sound bank) and the longer list in is_quest_with_special_player_slot_handling.
- Whether the 0xef0 actor table is NPC-only; hunting monsters likely use another structure.
- Full decoding of the big screen handlers (106b9260, 106e9e40, 1079e2d0 internals, 107e1430...).
