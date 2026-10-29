# MHF-Z client: UI / HUD / menus / text subsystem (engine-neutral spec)

Author: UI subsystem agent (top-down). Source: `decomp\*.c`, DLL static data (read with pefile), `dat\*` containers.
Confidence tags: [H] read directly from code and consistent, [M] inferred from code + data, [L] guess / small-model name only.
All addresses are VAs in `mhfo-hd.dll` (ImageBase 0x10000000). Companion names: `analysis\claude_names\s_ui.jsonl`.
Status: first pass. Menu/HUD screen enumeration is shallow (see section 9 open questions).

## 1. Architecture in one page

* The UI is **not** a retained-mode widget toolkit. Every screen is an immediate-mode function that, once per frame, (a) polls input,
  (b) advances a small state machine held in globals, (c) issues draw calls (sprite by id, text at x,y, colored quad).
* All 2D drawing ends in three primitive emitters that submit **pre-transformed screen-space quads** (D3D9 FVF XYZRHW, `DrawPrimitiveUP`
  triangle strip, 2 primitives): `1000dec0` (flat colored rect), `1000e800` (textured rect, texel UVs), `1000f1d0` (textured quad from a
  14-short record, 4 arbitrary corners). Everything above them (sprites, glyphs, frames, gauges) is decomposed into those rects. [H]
* Coordinates are **integer pixels in the current backbuffer** (`short`), origin top-left, +0.5 half-pixel offset applied by emitters
  (`DAT_116038a8 == 0.5f`). The art/layout was authored for **640x480** (see 3); many screens center themselves with `width/2`, `height/2`.
* Assets: UI sprite sheets are PNG textures in `.txb`/`mhf.bin`; sprite *layout* data are binary "layout resources" (section 5);
  strings come from one localized text bank `mhfpac.bin` (section 6); glyphs are rasterized at runtime with GDI into 32x32 cells (section 4).

## 2. Screen-space renderer (the 2D back end)

### 2.1 `1000dec0` draw_screen_space_colored_quad (`__fastcall`, ECX = pointer to rect record) [H]
Rect record (all `s16` unless noted): `+0 x, +2 y, +4 w, +6 h, +8 u32 ARGB color` (the code reads `*(u32*)(rec+8)`).
Builds 4 verts `{x,y,z=0,rhw=1.0,color}` with FVF `0x44` (XYZRHW|DIFFUSE, stride 0x14). Sets pixel-shader constant register 0xb5 (181) via device
vtable+0x1b4 (SetPixelShaderConstantF) to a flag vector `(1.0 or 0)` depending on `[100083a0()+4] & 0x400`, then SetPixelShader (vtable+0x1ac) with
`DAT_11b8c6e8[iVar]` where `iVar = (DAT_11aa7ce4 & 0x1c ? 2:0) + (DAT_11aa7ce4 & 0x18000 ? 1:0)` (variants selected by render-state bits), SetVertexShader(NULL),
SetFVF, then `DrawPrimitiveUP(TRIANGLESTRIP=5, 2 prims)`. If the shared render-target object `DAT_1e73d3c0` (0x210 bytes, built by `10029cb0`) has
its "post-process active" field `+0x204` nonzero, the quad is drawn twice (once to the normal target, once after `10029bb0`/`10029c00` bind the alternate pair). [M]

### 2.2 `1000e800` draw_textured_screen_quad (rect pointer in arg) [H]
Rect record (s16): `+0 x,+2 y,+4 w,+6 h, +8 u32 ARGB, +0xc u0,+0xe v0 ... ` precisely: `[0..3]=x,y,w,h`, `u32@+8=color`, `[6],[7]=u0,v0` (texels), `[8],[9]=u1,v1` (texels).
UVs are divided by the **current texture's width/height** taken from the texture-slot table (`DAT_11aa7cf4/cf8 + DAT_11b8c654*0xd8`; `DAT_11b8c654` = current
texture slot). Flip flags in the global render-state word `DAT_11b7fe20`: bit 0x100 mirrors U, bit 0x200 mirrors V. FVF `0x144` (XYZRHW|DIFFUSE|TEX1, stride 0x1c).
Positions are `x - 0.5, y - 0.5` (D3D9 half-pixel correction). Same post-process double draw as above. [H]

### 2.3 `1000f1d0` draw_texture_rect_from_slot [M]: textured quad with 4 independent corner positions (used for rotated/sheared sprites: `113ecc60`).

### 2.4 Sprite blitters (thin wrappers selecting a resource "bank" by index in EAX)
* `1096c0f0` draw_layout_group(bank=EAX, group, x, y, w, h, ...) -> `113eeb70` (draws a *layout group*, section 5.4). 531 callers. [H]
* `1096be60` draw_sprite_group(bank=EAX, group, x, y, ...) -> `113edfd0` (draws every sprite of a *sprite group* at x,y). 287 callers. [H]
* `1096bca0` draw one sprite of a group (`113ed9c0`); `1096bd30` fetch rect then draw; `1096c2e0` draw animation-tree (section 5.5) -> `113f0c10`.
* `113ed380` draw one sprite part (scale, rotate, optional 2-D tiling when flag 8): builds a 2x2 scale+rotate matrix, then `113ecc60`; `113ecc60` emits
  the quad as two triangles via `1000f1d0`, handles flips (flag bits 0/1), rotation, color modulate (`ARGB * tint / 255` per channel), snaps corners to integer pixels.
* `1003f080` draw_sprite_by_mode(mode 0: scaled sprite group via `1096be60`; 1: layout group via `1096c0f0`; 2: animation-tree via `1096c2e0`). [M]
* `1003f400` render_screen_quad_entries: 11 fixed entries (stride 0x44 bytes, base = EAX+0x28-... see name file) drawn through `1003f080`, used for
  full-screen backdrops/letterboxed images with **resolution scaling** (see 3). `113aeb50` scale_center_and_submit_draw_rect: scales a rect to
  `screenHeight - 2*margin`, preserving aspect, centers on screen -> `1096c0f0`. [M]
* `10992060` set_clipped_render_rectangle / `10992170` restore: the current UI clip rectangle lives in the camera/render object `*DAT_1edaad60`
  at +0xdc..+0xf0 (x, y, w, h, 0, 1.0f) and is clamped to `[0, DAT_1ebee5a0] x [0, DAT_1ebee59c]`. Backup copy is +0xc4..+0xd8. [H]

### 2.5 Render-state glue
`10010d50(mode)` / `10011060()` bracket every UI draw (select/restore blend-state set; mode 0 = untextured/opaque, 1 = textured alpha). Sprite element
blend byte (+0x1a) 0..4 selects between render-state presets (`10b705e0` + `DAT_1ed52890` state cache). Texture binding: sprite element has a
*local* texture index which maps (via the resource's texture list) to a *global texture slot* (u16) then through `DAT_1ecda320[slot*2]` to the loaded
D3D texture; texture slots live in a table at `0x11aa7d80`, stride **0xd8** (216 bytes; +0 = IDirect3DTexture9*, +0x274-ish dims at `0x11aa7cf4/cf8`
negative-offset fields). `11aa7ce4` is the current render-state mask. [M]

## 3. Resolution, scaling, aspect ratio (important for an HD UI)

Config (`mhf.ini` `[SCREEN]` -> parsed into a config struct at `DAT_1e866c5c`; copied by `1158ec70`):

| ini key | config offset | globals after load |
|---|---|---|
| (windowed/fullscreen mode) | +0x1d74 | `DAT_1e866c70` (0 = windowed, 1 = borderless fullscreen at monitor, 2 = exclusive fullscreen) [M] |
| WINDOW_RESOLUTION_W | +0x1d78 | `DAT_119dd740` (clamped min 640), `DAT_119dd738` |
| WINDOW_RESOLUTION_H | +0x1d7c | `DAT_119dd744` (clamped min 480), `DAT_119dd73c` |
| FULLSCREEN_RESOLUTION_W/H | +0x1d80 / +0x1d84 | `DAT_1e866c68 / 6c` (clamped min 640x480; 0 = use window size) |
| (use-monitor-size flag) | +0x1d90 | if nonzero fullscreen size := monitor rect (`MonitorFromPoint` + `GetMonitorInfo`) |
| language id | +0x1db0 | selects text bank file, DBCS lead-byte table, fonts |

* Static defaults are 640x480 (`119dd738/73c/740/744 = 0x280/0x1e0`). The shipped user ini requests 1280x720 (or 1600x900 / 1920x1080 in `mhf2.ini`).
* The **render width/height used by the UI** are two globals: `DAT_1ebee5a0 = width`, `DAT_1ebee59c = height` (set in `114d5cb0` window creation, `114d6130`,
  and `114d6e20` device reset; `_DAT_119dd768 = width/height` is the aspect ratio used by perspective projection). 3D viewport = full backbuffer, aspect = w/h,
  so ultrawide already gets a correct 3D aspect (vertical FOV is `*(DAT_1edaad60+0xb8)`; Hor+). [H]
* **UI scale rule** (seen in `1003f400`): `scale = height * (1/480) * (height > 480 ? 0.85 : 1.0) * entryScale` (`DAT_119b6360 == 1/480`, `DAT_119b6310 == 0.85`).
  I.e. screen-sized art (backdrops, fades) is scaled by **height/480** (with an extra 0.85 factor above 480 lines) and optionally centered by
  `(W/2 - sz/2, H/2 - sz/2)` (entry flag bit 0). Other screens position by absolute pixel numbers in a **640x480-ish virtual space**
  and center with `W/2`, `H/2` (e.g. `10b984e0`: `x = W*0.5 - const`, popup 0x240x0x1b0). So windows/dialogs are *not* stretched: at 1280x720 they stay the same
  pixel size and sit in the middle of a larger canvas; only full-screen images scale. [M]
* Implication for a rewrite: treat the UI as a 640x480 (4:3) design canvas drawn at 1:1 pixels, centered; full-screen images scale by height/480 and
  are letterboxed/centered (`113aeb50`: size from height minus 2*margin, aspect preserved). HUD elements anchored to screen corners need
  case-by-case review (open question 9.3).
* Window handling: `114d5420` toggles fullscreen/windowed; `114d6e20` handles device-lost reset (saves ~100 render states, `IDirect3DDevice9::Reset` with
  params at `DAT_11aa7c88`, restores states, re-creates `DAT_1e73d3c0`).

## 4. Text and font system

### 4.1 Text overlay object `DAT_1e3cbd64` (the "text/render struct", also holds pass id at +0x64) [M]
Layout (offsets in bytes):
* `+0x10` pass/pixel-shader id, `+0x14/+0x16` s16 cursor x/y, `+0x18` u8 glyph cell width, `+0x19` u8 glyph cell height/line spacing source, `+0x60` int flag
  "half-width mode" (digits narrower), `+0x64` render pass (2,4,3 set by `1080fe60`), `+0x88`.
* `+0x1c .. +0x34` : seven int counts, and per group a pointer table (`group = *(ptr)(count_slot+0x1c)`, string pointers at `group+0x10`, stride 0x14)
  = the seven *registered text groups* scanned by `114df4c0` collect_unique_text_glyphs. [M]
* `+0x8c` index of next glyph to rasterize, `+0x90` number of glyphs queued, `+0x94 + i*2` : queue of char codes (s16).
* `+0x794 + code*2` : u16 map char code -> atlas slot (0xFFFF = not yet allocated); table of 0x10000 entries. `+0x20794` = next free slot (int);
  `+0x20798 + page*4` = texture-slot id of atlas page `page`.

### 4.2 Glyph atlas (dynamic) [H]
* Cell = **32x32 px**; one 256x256 page holds 64 cells (8 columns x 8 rows); cell for slot `s`: `x=(s & 7)*32, y=((s & 0x3f)>>3)*32`, page `s>>6`.
* Max **0x380 = 896 glyphs** (14 pages). `114df4c0` pre-scans the seven text groups on screen entry and assigns slots (stops when 0x37f exceeded -> returns 1);
  `114df330` (process_pending_texture_tiles) then rasterizes queued glyphs per page: locks the D3D texture (vtable+0x4c LockRect), calls `114d3410` per cell, unlocks.
* `114d3410` rasterize_gdi_glyph_to_rgba: char code in EAX (hi byte = lead byte for DBCS), uses a **GDI memory DC** `DAT_1e38e67c` with a pre-selected font:
  `GetTextExtentPoint32A` + `ExtTextOutA` into a 32x32 8-bit DIB (`DAT_1e38e678`), then writes pixel = `(gray << 24) | 0x00FFFFFF` (white with coverage alpha)
  into the 32-bit texture. Single-byte chars use the left 16 columns (rest cleared); double-byte use the full 32. So **fonts are system fonts** (face/size
  chosen elsewhere with `CreateFont`; INI `FONT_SIZE`) — a rewrite should rasterize with any TTF at cell size 32 (single-byte = 16 px wide cell).
* `114defe0` render_glyph(code, textObj, shadow): looks up slot, draws a 1000e800 quad from the cell (w = 16 for SBCS, 32/`cellW` for DBCS by `+0x18/+0x19`),
  optional 4-direction outline pass when `param_3 != 0` (draws the glyph in black at (-1,-1),(0,0),(-1,+1),(+1,-1) with alpha derived from brightness), style
  codes at `rec+10`: 2 = grey background rect (0xff808080), 3 = highlight rect (0xff57ffff) with inverted text color. [M]
* `114deec0` render_text(str, rec): walks the string; `\n` (0x0a) resets x to rec x and adds line height (`rec+9`); lead-byte test through bitmap
  `PTR_DAT_119defb4[language]` (32 bytes, bit per lead byte); skips 0x8140 (ideographic space) and 0x20; advance = cell width (`rec+8`) for DBCS, 2/3 of it for SBCS
  (or 1/2 when flag `+0x60`). [H]
* Lead-byte tables: languages 0-5 -> `0x119def74`: lead bytes 0x80-0x9F and 0xE0-0xFF (Shift-JIS/CP932); languages 6-7 -> `0x119def94`: 0x80-0xFF
  (Korean CP949 / Traditional Chinese Big5). [H]
* Language ids (config +0x1db0) [M]: 0 = default/Japanese `mhfpac.bin`, 1 = USA (`localize-dat\localize-usa-mhfpac.bin`, plain-byte strings, no SJIS
  translation), 6 = Korean, 7 = Taiwan; 2-5 reuse `mhfpac.bin`. `114df610` sjis_string_to_wide_or_copy: for lang != 1 converts SBCS bytes to 2-byte cells using a
  translation table `*(DAT_1e77dccc+0x134)` (char*2), so the Japanese build renders ASCII through the same 2-byte path.

### 4.3 Higher-level text API [M]
* `10802400` draw_formatted_text_at(x, y, fmt, ...) (vsnprintf 0x200) and `10b70d50/10b70f30` (debug/overlay text, optional ARGB color) fill the overlay record and call
  `114deec0`. `106c3950` / `107e4120` add drop-shadow (`114dea50`). `10b71370` draw_tagged_text_block parses in-string tags (see 4.4);
  `10b71210` formats into a 1 KiB buffer first; `10b72180` measure_tagged_text_extent; `10b72010` strip_tags.
* `10b72c50` set_text_overlay_depth_from_layer(layer 0..6) -> overlay depth.
* Text is drawn **immediately in the same frame** (no retained text objects). Because glyphs are allocated lazily by pre-scan of registered groups, strings built at
  runtime must go through the registered groups or they will not have atlas slots (unregistered code -> 0xFFFF slot -> probably skipped). [L]

### 4.4 In-text tag language [L]
`10885800` parse_text_tag_token_ascii classifies tokens: 0 end, 4 newline, other for a tag introducer; used by measuring/stripping/drawing. Exact tag
syntax (color codes, icon insertion, wait) not yet decoded. See open questions.

## 5. UI sprite/layout resources ("layout banks")

### 5.1 Where they live
`dat\mhf.bin` (normal) or `dat\mhf_90c.bin` (the "90C graphics" variant; path string at `0x1197a130`) is a **pack table** (u32 count, count*(u32 off,u32 size))
of 93 entries (mhf.bin). Entries 0-6, 11-13, 50-59 are PNG textures; 7-10,14 nested tables / JKR blobs; **entries 15-49 are layout resources**.
`1096bba0` initialises 26 banks from the list at `0x1188217c` (12-byte records `{id, texList*, "dat\mhf_90c.bin", nextId}`): entry ids
15,16,17,19,20,22,23,27,28,31,32,33,35,36,37,38,39,40,41,43,44,45,46,47,48,49. Each bank is loaded by `113ecae0` (reads entry `id` with `1000ae90`
via `fopen/fread` using the 0x810-byte pack header, `malloc`, then pointer-fixup `113f12f0`). Loaded banks are held in `DAT_1e80db58`
(0x2284 bytes = int count + 32 slots x 0x114): slot = `{int inUse; char name[~256]; ... +0x108 id; +0x10c ptr? ...}`; slot+`0x10c/0x110` = resource
pointer, `+0x110`/`+0x114` = size. Bank index -> slot via `DAT_1e7fe468[bank]` (26 ints). `113f1380` allocates the bank holder; `113f13d0` frees one. [M]

### 5.2 Resource container (all little-endian) [H]
```
u8  type = 0 (container)   u8[3] pad
u32 total_size
u32 id/version      (e.g. 0x1f02, 0x1e35: probably a content hash or ID; not used by renderer)  [L]
u16 child_count     u16 pad
u32 child_offset[child_count]      ; relative to container start; fixed up to pointers by 113f12f0
children (each starts with u8 type, u32 size at +4): laid out back to back
```
Children by position: child0 = **sprite table** (type 2), child1 = **layout table** (type 3, optional), child2 = **animation tree** (type 4, optional).
`113f12f0` relocates: type 0: the child offset array; type 4: three offsets at +8,+0xc,+0x10. Types 2 and 3 need no relocation (offset tables are relative).

### 5.3 Type 2: sprite table (child0) [H]
```
+0  u8 type=2 ; +4 u32 size ; +8 u32 offset_to_group_offsets (=0x10) ; +0xc u16 group_count
+0x10 u16 group_offset[group_count]   ; relative to child start
group: u16 sprite_count, u16 ?, then sprite_count * 28-byte records:
```
Sprite record (28 bytes = 14 x u16), offsets from record start:
| off | type | meaning |
|---|---|---|
| +0x00 | u8 | kind/unused (0) [L] |
| +0x01 | u8 | flags: bit0 flip U, bit1 flip V, bit2 select blend preset (`DAT_1185df50[bit]`), bit3 **tiled** (repeat src rect to fill dest w,h) |
| +0x02 | u16 | local texture index -> `texList[idx]` (global texture slot id) |
| +0x04 | u32 | vertex color ARGB, multiplied by caller tint (channel * tint / 255) |
| +0x08 | s16 x4 | source rect in texels: u, v, w, h |
| +0x10 | s16 x2 | destination offset x, y (relative to draw origin) |
| +0x14 | s16 x2 | destination size w, h (scaled by caller scale) |
| +0x18 | u16 | rotation, angle units = `*DAT_119b5f1c*DAT_119b5f34` (turns->radians-ish; 0 = none) [M] |
| +0x1a | u8 | blend mode 0..4 (0/1/3 = default, 2 = mode 2 preset, 4 = mode 1 preset) |
Dest rect fields are what `113f1110` ui_element_rect returns: (x, y, x+w, y+h). `113f1190` computes a group's bounding box (initial +-0x7fff).

### 5.4 Type 3: layout table (child1) [M]
Same header shape (u16 group offsets at +0x10, group count at +0xc). Group: u16 element_count, then **16-byte elements (8 x u16)** whose first byte is a type:
type 3/5 = sprite-group placements (tinted by `uVar11` color multiply), 4 = text/callback area (invokes caller-supplied callback with x,y,w,h and font
size bytes written to the text overlay `+0x18/+0x19`), 6 = clip rect (`113eefa0` finds it). Handler table `0x119a622c[type]`: types 1,2,7(?) -> `113ee140`,
`113ee5d0`, `113ee720` (sprite-group / scaled variants). `113eeb70` draws a whole layout group scaled by (param_10, param_11) with a 9-slice-like stretch
(elements store offsets relative to the group size so frames/panels scale). [M]

### 5.5 Type 4: animation tree (child2) [M]
Header: `+8 -> node block`, `+0xc -> key block`, `+0x10 -> offset table`; counts at `+0x14` (node count) and `+0x18` (key-array count) [read in `113f0c10`]
(`113f0c10(animId, res, ...)`: node = `nodes + offsetTable[animId] * 0x14`). Node record (0x14 bytes): `+2 s16 child count; +4 u16 sprite/group id (0xFFFF = group
reference by +6); +6 u16 element/group index; +8 u16 track id; +10 s16 track key count; +0x14 children follow, each size `*(s16*)node*10`...` (children packed after the
parent). Track = array of 0x24-byte keys (9 dwords): `+0 u32 time (frames; negative values wrap +2^32 offset)`, then x, y (positions), scale x/y (+0x10/+0x14), rotation
(+0x20 s16), color, `+0x22` interpolation flag. `113f0fa0` interpolates linearly between keys (`113f0d40`). `11405a00` is a per-node visibility/loop filter. `113f0650` draws the
tree recursively (node -> sprite group `113ed9c0` or layout group `113eeb70`), accumulating position/scale/rotation/color. [M]

### 5.6 Texture list per bank
`texList` (u16, 0xFFFF-terminated) holds the **global texture-slot ids** the bank's sprites index (values like 0xb09, 0xb47 = slots in the 4253-entry slot space;
slot ids >= 0x5ed are the per-monster ranges in archive-format.md). The slots are filled when the corresponding `mhf.bin` PNG entries (and `.txb` packs)
are loaded; mapping slot -> pack entry is by loader code (e.g. `10011af0` creates D3D textures from PNG memory). Mapping table not decoded. [L]

## 6. Strings / text bank

* One localized pack: `mhfpac.bin` (ECD+JKR wrapped -> 2,259,385 bytes unwrapped) or `localize-dat\localize-{usa,kor,twn}-mhfpac.bin` (chosen by
  `PTR_s_mhfpac_bin_11a4601c[language]`). Loaded by `10afba10`: header magic `'pac\x1a'`, version `0x0a`, loaded via `1158c940`/`1000ad00`, **checksum** at +0x0c
  verified (`1158f350`), then the header's section offsets (u32 array from +0x10) are rebased to pointers and each section's table of N-int rows (rows of 3,4,5,3,0x13...
  ints, terminated by a zero first int) is relocated. Pointer `DAT_1e77dccc` is the in-memory bank. Magic bytes in file: `70 61 63 1a 0a 00 00 00 00 00 00 00 24 11 00 00 a0 95 13 00 ...`. [M]
* Accessors:
  * `DAT_1e77dccc + 0x40` : **message table**, 8-byte entries `{u8 style, ..., u32 textPtr@+4}` indexed by message id; `1079dc50(id)` -> `1079dc70(text, style, 0)`
    opens the generic message window (style low 7 bits, bit 7 = no cursor, `DAT_11c3bc42`=style; window geometry computed from the longest line: width `((chars*5+0x1e)*2)`, centered at x=0x140/y=0xe0 of a 640x480 canvas). [M]
  * `1047a820` select_text_entry_by_id: ids `< 40000` look in a range table `*(DAT_1e77dcc8+0x14)` (4 ushort per range: first id etc.), returning pointer array; sub-string = `id % 100`, extended ids >= 40000 handled by `10682930`.
  * `1047a8a0` get_text_string_ptr_by_id_and_index; fallback string `*(DAT_1e77dccc+0x33c)+8`.
  * `DAT_1e77dcc4` (item master table, stride 0x24, icon info at +5/+0x1c), `DAT_1e77dcc8` (text range index), `DAT_1e77dce0` (class tables) are sibling sections of the same bank (`10af5140`, `10afae80`).
* Dialog/NPC text: `dat\load\*.bin` (192 small files named like `001_00_000.bin`) hold quest/NPC/story text pages [L, contents not decoded]; NPC conversations
  `10726640 start_npc_dialogue`, `10726a50` node input, `10726de0` actions (8-byte action table).
* Text encoding is **Shift-JIS (CP932)** on the Japanese client with 2-byte glyph cells; the USA/KOR/TWN banks use their own code pages (ASCII in USA).

## 7. Input conventions used by menus [M]
Menus read a button mask in an argument/EAX: `0x20` confirm, `0x40` cancel, `0x400` right, `0x800` left, `0x1000` down, `0x2000` up, `0x8000` close/back, `0x10`/`0x4000` etc.
`108f7440(mask)` polls pad; mouse support uses rect lists: `108f28b0` hit test of 4-short rects (x0,y0,x1,y1) against `DAT_` cursor, `108f29b0` repeated, `108f2ad0` grid cell
index in a rect (columns x rows), `108f2bc0` single rect (flags 0x100040 etc.). Cursor movement helpers with wrap-around: `10718290` (vertical), `107183b0` (horizontal),
`10718220/107181a0` (with SE index), sounds via `10711af0 play_ui_sound_effect_by_index` (table at `0x118e6b38`, 8 bytes/entry) and `10b42ef0`.
Rects used by menus are computed from the screen center, e.g. `x = W*0.5 - K`.

## 8. Screen state machines (what exists)
| address | name | notes |
|---|---|---|
| `10b98eb0` update_menu_dialog_state | 1742 B, 3 callers | state byte `DAT_1dc6b670` (0 idle/list, 1,7 closing wait, 2 closed, 3 sub-choice (`10b9c340`), 4 selection dialog (`10b9b500`), 5 detail/confirm (`10b9bbe0`), 6/8 paged detail with left/right page change, `DAT_1dc6b674` page index, `DAT_1dc6b676` page count, `DAT_1dc6b67e` current entry/help id). Returns 0 (continue), `0x40` (cancelled), `0x8000` (closed). Lives in the state block at `0x1dc6b6xx` (just below the 100 character slots). Pass-in arg = pad button mask. [M] |
| `10b984e0` update_modal_fade_and_dismiss_state | state `DAT_1dc6b6cc` 0 init (`10b98460`), 1 fade-in (`DAT_1dc6b6c8 += DAT_118e45b0` until 1.0), 2 wait for confirm (mouse rect 0x240x0x1b0 centered) -> sfx (`10b42ef0`), 3 fade-out then `108df700(0x108c,1,0)` (screen-change request) + sfx. [H] |
| `10b98910` update_menu_selection_flow | opening delay, bounded item navigation, dismissal, secondary selection. [M] |
| `10b995c0` dispatch_ui_state_handler | position transform + common reset then per-state handler dispatch. [M] |
| `10b9b500` handle_selection_dialog_input / `10b9bbe0` handle_menu_selection_and_dispatch | centered selection dialog: refresh on selection change, commit/cancel. [M] |
| `10839260` update_selection_screen_state_machine (8.3 KB, no static callers => dispatched) | input polling, held-input repeat, countdowns, transitions; the big list-selection screen. [M] |
| `10801a30`, `108050e0`..`10806290` | five parallel small "menu_screen_a..e" handlers; state bytes `DAT_1e76bcb8..bcbc`; tween targets (`10802ce0`), slide animations (`108043e0`). [L] |
| `11405950` per-frame client mode dispatch | table `PTR_LAB_11aa0574[DAT_1e8e35a0]` of per-mode handlers; see NOTES.md. |
| `10b6bb60` set_ui_screen_state_and_fade; `108870f0` set_fade_transition_from_table (0x1c-byte descriptors) | screen id stored at `DAT_1e7fff3c+0x24fe`; transitions via fade descriptors. [L] |
Dialog/UI ids: `DAT_1ee268e0` = current dialog/screen id (e.g. 0x46, 0x58, 0x59 special cases), `DAT_1ee268e8` sub-state.
The full list of screen ids and their handlers is **not** yet enumerated (see 9).

## 9. Open questions / next steps
1. Enumerate screen ids -> handler functions (dispatcher table at `0x11aa0574`; ui ids in `DAT_1ee268e0`).
2. Decode the `mhfpac.bin` section table (what each of the u32 section pointers at +0x10.. is) and the in-text tag syntax (`10885800`).
3. HUD anchoring: which HUD elements anchor to screen edges vs the 640x480 center (needs reading of in-quest HUD draw functions; `106a1xxx` zenny/RP/GG amounts use fixed pixel positions).
4. Map global texture slots (`0x11aa7d80`, `DAT_1ecda320`) to `mhf.bin` / `.txb` entries (the loader that fills `PTR_DAT_11882180` texList values).
5. Font face/size creation call (CreateFont) and the effect of INI `FONT_SIZE`.
6. Verify rotation units constants `0x119b5f1c/34`, node record fields in 5.5, layout element types in 5.4 with a runtime dump.
7. `.txb` files (`dat\*.txb`, 18 files): confirmed **pack tables of PNG textures** (sizes 128..1024 pow2, mostly 8-bit palette, some 4-bit / 1-bit / 32-bit RGBA);
   per-screen atlases: init(512x512), title(3 x 1024), charsel(9), map(59 x 256), stg(21 x 512), others00(36 x 1024x512), loadfw, kunren, net_connect... No sprite-coordinate data inside the txb; coordinates are in `mhf.bin` layout resources or hard-coded in code. HD replacement = replace the PNG and (if size changes) adjust the code/layout UV rects (texel coordinates are absolute and divided by the texture width read at runtime from the slot table, so a **2x texture requires 2x source rects**).
8. `micon64.bin`/`micon128.bin`: pack tables of 64x64 / 128x128 PNG item icons (103 entries) [H]; icon atlas draw `10446a50` uses 8-column atlas of 32x32 cells (`DAT_`..). [M]
