# Input, Player Control & Camera (subsystem notes)

Status: IN PROGRESS (first checkpoint). Confidence tags: [H] read directly from decomp, [M] inferred from several sites, [L] guess.
Addresses are VAs in mhfo-hd.dll. `DAT_x` = global at VA x.

## 1. Input layer overview

Windows + DirectInput 8 (`DirectInput8Create` in `114ce1e0`; dinput8.dll can be Xidi). Window messages (WM_KEYDOWN/CHAR/IME) are handled separately by `114d3960` (WndProc part: chat/IME text entry, Enter/Esc/Home/End/arrows in the chat box) [H].

### 1.1 Input manager object (singleton, base ~0x1e8e52e0) [M]
Pointers into it are published as globals: `DAT_1e8e5454` = keyboard device (manager+0x174), `DAT_1e8e5458` = mouse device (+0x178), `DAT_1e8e545c` = first gamepad (+0x17c). Manager fields (offsets from `this`):
- +0x170 IDirectInput8*; +0x174 keyboard dev ptr (-> `DAT_1e8e55c0`); +0x178 mouse dev ptr (-> `DAT_1e8e6248`); +0x17c.. gamepad dev ptr array (count at +0x198, max 100; slot 0 = active pad).
- +0x30 mode flags (bit0 cursor in client, bit1/0x22 window inactive?, bit3 chat/IME active (`DAT_1edba1bc+0x15`), bit4 ?, 0x40/0x80 mouse button states).
- +0x40 logical button bitmask (current frame), +0x44 previous, +0x48 pressed edge (= cur & (cur^prev)), +0x4c released edge, +0x68 "any" summary.
- +0x19c/+0x1a0 current/previous "input context" word (from `108dd6e0`), +0x1a4 context-2 word (from `108dd9e0`), +0x1a8 context flags, +0x1b0 context-changed latch, +0x1b4 "last matched mapping" scratch.
- +0x2d0/+0x2d4/+0x2d8 secondary 32-bit mask (F-key style hotkeys) with prev and edge.
- +0x2b4.. mouse-as-stick bitset; +0x2a4 stick-direction accumulator; +0x2a8 "walk-limit" flag (clamps stick magnitude to 0x3c).
Per-frame poll: `114ce430` (`input_manager_update`, 1222 B): re-inits DInput after a reacquire counter (+0x1ac) hits 0 (`114ce1e0`), computes mode flags, calls per-device update loop, then `108de100` (scripted/forced input hook: if `DAT_11c71496` set injects an input sequence), then `114cee30` (mapping -> logical buttons, below), then derives edges (+0x48/+0x4c). [H]
Re-init `114ce1e0`: creates DI8, `114d1f60` keyboard (data buffer 0x100 bytes at dev+0x170, DInput data format), `114d21e0` mouse, enumerates joysticks with callback `114d1620`, `114ce950` reorders pads by the `[GAMEPAD_PRIORITY]` section of mhf.ini (entries "NN" -> "GUID,productname" or `notAvailable`; max 100) [H].

### 1.2 Device objects
- Keyboard device (at `DAT_1e8e55c0`): +0x170 byte[256] key-down state indexed by DirectInput scancode (DIK_*); +0x2b0 bitset[8 dwords] down-bits (same index); +0x270/+0x290/+0x2d0 previous/edge/other bitsets; +0x2f0 byte: modifier summary (low nibble = Shift/Ctrl/Alt flags, high nibble = right-hand variants) [M]. Query helpers: `114d29b0(scancode)` (down byte), `114d2990(scancode)` (down bit).
- Mouse device (`DAT_1e8e6248`): +0x40/+0x48 button mask / edge, +0x180/+0x184 relative dx/dy, +0x18c/+0x190 client-space cursor, +0x194/+0x198 screen cursor, +0x1c4 / +0x1c8 flags, +0x1cc "recenter" request set by many menus. `114d26b0` copies mouse state out as 0x24 bytes + buttons. Cursor clipping `114d2a20`, window mode toggle `114d5420` (fullscreen borderless <-> windowed 640x480 base, `DAT_1e866c70`).
- Gamepad device: +0x40 current buttons (DInput mapped to bit mask), +0x48 edges, +0x58/+0x5c/+0x5c.. stick dead-zone/range shorts, +0x68 summary, +0x1e4.. 0x5c-byte raw state for kbd(0)/pad(1) slots used by the hotkey handlers (`114d0d10`), vibration objects +0x1e4/+0x1e8 [L].

### 1.3 Key-mapping table (keyboard / pad / mouse -> game buttons) [H structure, M semantics]
`114cee30` (5.3 KB) builds a table of 6-dword records on the stack each frame (28 logical actions x 3 device slots = 0x54 records + 24 fixed pad records):
```
struct MapRec { u32 code;       // DIK scancode / pad button mask / mouse button mask
                u32 modmask;    // required modifier(s) (kbd) or chord mask
                u32 device;    // 1 = gamepad, 2 = keyboard, 3 = mouse
                u32 aux;       // 2 for pad axes etc.
                u32 handler;   // index into handler table 0x11aa07e0 (24 entries)
                u32 out;       // output bit pattern (see below) };
```
- The three device-bytes of each action come from a config word: `FUN_108dbe40(0xf, out[28])` ("keyconfig preset 0xf") returns 28 dwords, byte0/byte1/byte2 = key code for device slots 0/1/2 (ordering per `DAT_1e77dcc4+0x6f8..0x700` preset tables). 24 additional entries come from the profile record `DAT_1e77dc30+0x120` (24 dwords of pad-button codes; default block `DAT_11c71408`/`DAT_11c712e8` when no profile) [H].
- `114d03b0(count, ctxmask, padIdx)` walks records: a record is active when `ctxmask` has bit (record+0x08 device) set... it tests device 1 pad `(pad+0x40 & code)==code`, device 2 keyboard (key byte + modifier nibble match), device 3 mouse (`mouse+0x40 & code`), then calls `handler_table[rec.handler](padIdx, &rec)`.
- Handler table `0x11aa07e0` (24 slots; 0x07 and 0x14 special-cased as "ignore context mask"): 0:`114d0580` 1:`114d0590` (set button bits in output pad report, pad-only) 2:`114d0620` (analog: store stick via record out bits 0x10000..0x800000: L-stick x/y at report+0x1c/0x1e, R-stick +0x28/0x2a; negate for opposite directions) 3:`114d0780` (move key: sets mouse-move-flag bit1 and report bits) 4:`114d0850` 5:`114d08c0` (walk toggle +0x2a8) 6:`114d08e0` 8:`114d09c0` 9:`114d09e0` 10:`114d0a40` 12:`114d0a90` 13:`114d0ae0` 14:`114d0b30` 15:`114d0bc0` 16:`114d0c70` 17:`114d0950` 18:`114d0cc0` 19:`114d0d10` 20:`114d0db0` 21:`114d0dd0` 22:`114d0e10` (F-key bitset +0x2d0) 23: `114d0e10`.
- Context words (decide which mapping groups are active): `108dd6e0` returns the 'screen context' (0x40000000 no local player/transition; 0x2000000 in town/menu overlays; 0x1000000 chat open; 0x8000000/0x10000000 spectator/special; else `(DAT_1199f920[player_type] | 0x40000)<<8` plus 0x10000 (mounted/aiming) and 0x20000 flags). `108dd9e0` returns 'player state flags' (0x80/0x40 = guarding/charging weapon states, 0x08 default, 0x10/0x20 weapon-type-8 ranged states, 0x4/0x1 alive etc.) [M].

### 1.4 Output pad report (what the game logic reads) [H layout, M names]
Static array at `DAT_1e38e4d0`, stride **0x34** per local pad (0x13 shows only pad 0 used):
- +0x00 byte header (0x01), +0x01 byte 0x73 magic, +0x02 s16 = 1; +0x08 u32 **button mask** (low 16 bits = face/trigger buttons, bits 16..23 stick-direction-as-button, mapping in `108ddd50` converts between the two bit orders for UI/net); +0x1c.. two 12-byte stick records `{s16 x, s16 y, s16 magnitude(<=0x7f, deadzone via isqrt), s16 angle16, float angle_rad}` for left stick (+0x1c) and right stick (+0x28), computed by `114d0e40` (atan2, wraps negative to 2pi). A copy of the previous frame is kept at `DAT_1e38e5a0`; a second, "latched for network/replay" copy at `DAT_1e38e4c0`.
- `114d02f0` finalises: packs 4 quantised direction-sector nibbles through table `DAT_119a6ad8` (8x8 sector LUT) and `DAT_119a69a4` into +0x08 bits 4-7 and 16-23 — i.e. stick direction -> 8-way sector code.
- Gameplay consumers: 30 Hz frame-locked; the input is sampled once per logic tick (inside the `108e3f00` call chain) [M].

## 2. mhf.ini options (section [OPTION] unless noted) — `1158e380` loads, `1158d450` saves (`WritePrivateProfile*` against `<install>\mhf.ini`, path from `DAT_1e866c5c+0x14` + name at +0x186c)
Input/camera related (global byte; value semantic [L] unless known):
| key | global | note |
|---|---|---|
| CAMERA_TYPE | `DAT_1ecb2f4a` | camera control scheme for melee (read as byte) |
| CAMERA_BOW | `DAT_1ecb2f49` | bow camera |
| CAMERA_GUN / CAMERA_GUN2 | `DAT_1ecb2f44` / `DAT_1ecb2f50` | bowgun cameras |
| CAMERA_TYPE_BOWGUN / CAMERA_TYPE_ARCHER | `DAT_11a3efbc` / `DAT_11a3efbd` | newer per-class camera type (default 0 / 0xff) |
| CAM_PITCH_MODE / CAM_PITCH_SPEED / CAM_AIMKEY_MODE | `DAT_11a3efb9/ba/bb` | (aim key default 3) |
| CHAT_KEY_TYPE | `DAT_1ecb2f4c` | forced to 0 right after load (`1158e380` sets it 0 after `1158e310`, which rewrites the key to the string "keyconfig" unless input type is 4) [H] |
| FKEY_TYPE / DISP_FKEY | `DAT_1ecb2f4f` / `DAT_1ecb2f4e` | F-key bar |
| MOUSE_ENABLE / MOUSE_RANGE | `DAT_1ecb2f51` / `DAT_1ecb2f52` | mouse play |
| GUNNERCTRL / SCOPECTRL | `DAT_11a3ef93` / `DAT_11a3ef95` | gunner/scope control modes |
| VIBRATION | `DAT_1ecb2f43` | pad rumble |
| DISP_DIRECTION, ESC_DIR_TYPE, DISP_CTRL_ICON, SOFTKEYBOARD, ICONDSP_ONOFF, AUTOUSE_ONOFF, OPE_GUIDE, PLATE_DIRECTION, ZPLATE_CHANGE, GK_ACCOMPANY | `DAT_1ecb2f4d`, `DAT_11a3ef86`, `DAT_11a3ef8b`, `ef8c`, `ef8d`, `ef8e`, `efb4`, `efbe`, `efbf`, `efb6` | HUD/control hints |
Also [GAMEPAD_PRIORITY] (01..99 -> GUID,name) and a key `GAMEPAD_*` handled by `114ce950`. keyconfig file names: table `PTR_s_keyconfig_cfg_11889ba8` = {"keyconfig.cfg","keyconfig2.cfg","ASSIGN_DLU"?} indexed by `config+0x1820 & 1` (config = `DAT_1e866c5c`; +0x14 = install dir). `108d6050` loads (file <512 KB; parse via `108d5360/108d5e30/108d6420`), `108d7540` saves (`108d75e0`), `108d7cf0` existence check [H]. Format of the cfg body: see open questions.
Rebind UI primitives: `108db5f0` (pad/keyboard capture: reads keys 0..255, mouse via `114d26b0`, rebinding into profile+0x120[24] swapping duplicates), `108dbfa0` (keyboard rebind into the 28x4 byte table, validates against list at `DAT_1e77dccc+0x4c`), `108db8f0`, `108d9240` (store), `108d5960` (apply).

## 3. Player/character data (see also game-state agent)
Game-state block `DAT_1e7fff3c`: +0x23f8 byte = local player slot index; +0x23ff byte = "spectator/other mode" flag; +0x0e/+0x12 flags. Character slots: base `0x1dc6b750`, stride **0x1050** (100 slots); per-slot: +0 active, +1 enabled, +3 type (1/5 = hunter-ish, 0x0a etc.), +0x14 **current action/state byte** (`DAT_1dc6b764`; values seen: 1,5,7,9,0xb,0xf,0x13,0x14,0x1d,0x1e,0x1f = weapon-ready-type states; 0x0c,0x57,0x5b,0x78,0x7b = special locks), +0x15 sub-flag, +0x329.. etc.

(Sections for player state machine, movement/collision, camera follow to be completed below.)

## 4. Camera (carried from NOTES.md plus new)
State struct `DAT_1edaad60`: eye +0x80, target +0x8c, up +0x98, dir cache +0xa4, near +0xb0, far +0xb4, FOV +0xb8. LookAt builder `10baee10`; scripted camera `1081fe90`.

## 5. 30 Hz assumptions
Input is polled once per logic tick; edges (+0x48/+0x4c) are single-tick; the `+0x1ac` re-init counter, `DAT_1e811a1c` (4-tick countdown after mouse click), and cursor-recenter requests are per-tick counters. A 60 fps sim must scale or keep the input sampling at 30 Hz.

## Open questions
- cfg file byte format (`108d6420`), meaning of preset 0xf table, exact bit meanings of the 32 button bits (need confirming through `108e28d0`, `10a81d20` consumers).
