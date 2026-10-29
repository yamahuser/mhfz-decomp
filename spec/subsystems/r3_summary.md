# r3 summary: functions 0x10400000-0x105FFFFF (UI / menu / item-box / dialog layer + a few 3D scene renderers)

Region character: almost entirely the **in-game UI layer**: dialog state machines, item/equipment box menus, shop/exchange list drawers,
text drawing helpers, plus a block of 3D scene renderers at 0x105e9xxx-0x105fdxxx. Strings in the binary are Ghidra-labelled
(`s_..._<addr>`); real text (e.g. `%7dGz` = zenny price, `~C02` colour escape, `{k04}` key icon, `MYSET_EX_`, `Lv.MAX`,
`http://members.mhf-g.jp/ingame/harisen_cat/...`, `dat\extend\gacha.txb`, `my_gallery\%s.bin/.gab`) can be read from the DLL by VA.

## 1. Screen/dialog dispatch model (key finding)
- Master dispatcher `10712970` (8.4 KB, outside region): `switch(DAT_1ee268e0)`; **DAT_1ee268e0 = current dialog/screen id** (about 250 ids, 1..263).
  Each id maps to one handler (state machine) which is called every logic frame. Handlers in this region are named `update_dialog_<id>_*`.
  Full id->handler list was extracted (ids 1,9,28/29,44,47,48,50,53,59,67,74,80,83,84,94,96,97/98,104,112,114-116,123/124,132,135,137-139,141-143,148,151,153,156,158-162,168,175,183,184,198,208/209,212,224,227,236,241,245/246 live here).
- Handler pattern: poll input bitmask (`108f7440(0x10)`: bit 0x20 confirm, 0x40 cancel, 0x200 alt, 0x400/0x800 up/down, 0x8000 toggle mouse);
  mouse hit tests `108f29b0` (list of rects), `108f2ad0` (grid cell); message-window poll `10726de0`; fade/transition wait `10719c60`;
  click sound `10b42ef0(0,0)`; sub-state in a per-dialog byte inside the shared scratch block `DAT_1ee268f0` (0xb000 bytes, cleared on dialog open).
- Item box family (dialogs 28/29, 96, 97/98, 104, 123/124, 208/209) share the **menu state object `DAT_11c19414`** (+2 input-active flag, +3 selection, +4 substate, +8 mode,
  +9 tab, +0x38 multi-select, +0x95f.. box menu substate, +0xac0 option count) and back up/restore the save sections (`104c8f50`/`104c8fd0`) so cancel can undo edits.
- Layout is 640-base virtual UI; widescreen shifts x by `(DAT_1ebee5a0 - 640.0)` (DAT_119b5f28 = 640). DAT_1ebee5a0/59c = render width/height.

## 2. Text draw system (corrects earlier names)
`DAT_1e3cbd64` is the **text command context**, not a sound buffer: +0xc x (s16), +0xe y (s16), +0x10 f32 scale, +0x18 u16 cell size (0x1010/0x1212/0x1414 = 16/18/20 px font),
+0x64 font-size level 0..6 (= clamp(scale*0.001*7)), +0x88 style flag, +0x207d0 ARGB colour. `114de7f0` resets, `114de870` begin, `114de910` set colour slot, `114dea50` push string.
`10b71140` / `10b70cf0` / `10b71210` are **printf-style text draw calls** (flag DAT_1ecb1704==0 means draw enabled) -- the other agent's "debug_log_printf" names are wrong in this context.
`10b72180` measures text width; escapes `~Cnn` colour, `{kNN}` button glyph. Item names: table at data root +0x100 (pointer per item id); item records at root +0xfc (0x24 bytes).
Text bank root `DAT_1e77dccc` (UI strings; `+0x244` common labels, `+0x324/+0x328` button hints, `+0x334` menu captions, `+0x3e4` prompts, `+0x4b4` dialog templates, `+0x70c` help lines);
message DB (ids <40000 via `1047a820`: range table at DAT_1e77dcc8+0x14, string = list[id%100]; >=40000 via `10682930`).
Static game data root `DAT_1e77dcc4`: +0x7c melee weapon table (0x34/record, class byte at +3, flag +0x1a), +0x80 gunner weapon table (0x3c/record, class at +4, flag +6),
+0x50/54/58/5c/60 armor tables per kind (0x48/record, flag 0x10 at +4), +0xfc items (0x24), +0x100 item names, +0xe4/+0xe8 per-type counts.

## 3. Save/character data structures
- `PTR_DAT_11a3ee2c` = live character save block (0x24cd4 bytes; backup copy checked each frame): +0x60 money (u32 XOR key DAT_1edb9ba0), +0x64 u16[0x38], +0xd4 **equipment/item instance array (16-byte records, indices <0x1194)**,
  +0x11a14 item box (7000 x 8-byte {u16 id, u16 count, u32}), +0x1f6c6.. and +0x1fd80.. loadout index tables (u16[6]: weapon + 5 armor), +0x1fdb4 flag bitset (0x600 bits), +0x1ff14 second currency, +0x1fda6 rank (xor DAT_1edb9ba8), +0x2051c 400 x 8-byte, +0x21294, +0x214f8 second loadout, +0x229a4 20x5 grid, +0x23bbc party flags.
- Equipment instance (16 B): +0 flags(bit0 present) +1 type (6 melee, 7 gunner, other = armor kind) +2 u16 id +4/+6/+8/+10 u16 attached ids (decorations/upgrades) +12 u32 payload. `10490ff0` adds, `104b7680` validates six-slot loadouts, `104aeef0` snapshots equipped six.
- Character slots (100 x 0x1050 at DAT_1dc6b750) are runtime copies; `DAT_1e7fff3c+0x23f8` = local player slot index, `+0x23ff` = online/party flag.
- Tracked allocator: 512-slot pointer table DAT_1e892f98 (`105cfb50` malloc, `105cfb10` free).
- Event/progress flags: bitsets DAT_1ed7a4e0 (0x413d bits) and save +0x1fdb4; ids 0x26d-0x270 are periodically reset (`104e4c10`, `104df710`).

## 4. Render-side finds relevant to 60 fps / HD assets
- 2D UI quads are pre-transformed and drawn with the 2D pass pair `10010d50`/`10011060` + `1000e800` (textured) / `1000dec0` (solid); sprite atlas: 32px cells, 8 columns (`10446a50`); 1x1 white texel at uv (5,100) for solid lines.
- 3D in this region: `105f8bb0`/`105fd420` render equipped-character preview models (parts per equipment ref, per-player block stride 0xb980 at DAT_1e76ae4c); `105ef110`,`105f0040`,`105f0f70`,`105f1df0` render keyframe-driven timeline objects with linear interpolation between 0x70-byte keyframes (only input is the time value -> easy to feed a fractional tick for 60 fps); `105eaa40` draws scene objects by camera distance; `105e6cb0`/`105eef80` unproject screen->world.
- UI animation uses the frame counter DAT_1ed78564 (blink/cursor) and fixed per-tick state; nothing in the UI layer reads wall-clock time except the daily rotation (`10456320`, server time DAT_1e866cd8).
