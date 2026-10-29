# MHF-Z static game data tables (engine-neutral spec) - v1

Subsystem agent: GAME DATA. Sources: DLL decomp (`decomp\<addr>.c`), real files in `C:\Users\Ayman\Desktop\MHFZ\dat`, ReFrontier
(`thirdparty\ReFrontier\FrontierDataTool`, Structs.cs/Program.cs), python helper `tools\mhf_data.py`.
Tags: [H] verified on real data and/or loader code read in full, [M] read from code or partially verified, [L] guess.
All integers little-endian. "ptr" fields are FILE OFFSETS from the start of the decompressed file (the loader rebases them in place).

## 0. IMPORTANT correction to spec\archive-format.md (JKR decoder constants)  [H]
`tools\mhf_archive.py` uses `LEN4 = 0x12` and `copy(c + 0x1b)`. The DLL (disasm of 1158efe0: `1158f157 lea esi,[eax+0x0a]` for the 4-bit-length
case, `1158f11a lea esi,[eax+0x1a]` for the byte-length case) and ReFrontier both use **+0x0a** and **+0x1a**. With the correct constants
mhfdat.bin's LZ stream is consumed to the last input byte (7,043,471 of 7,043,471) and yields a sane 28,723,584-byte image; with the old ones
the stream desyncs (output overshoots; pointer table in the header looks like garbage). Short files decode identically under both only if they
never use those two opcodes. Use `tools\mhf_data.py` (`jkr_decompress`, `unwrap`, `load('mhfdat.bin')`). Case "c == 0xff" (raw literal run of
d+0x1b bytes) never occurs in the data files checked. Type 4 (Huffman bytes) not re-verified.

## 1. File inventory (dat\ top level, install checked) 
| file | disk size | layers | unwrapped | magic / shape | loader (VA) |
|---|---|---|---|---|---|
| mhfdat.bin | 7.0 MB | ECD+JKR3 | 28.7 MB | `mhf\x1a` ver 0x59, relocatable image (sec. 2) | 10af5140 (19,967 B, 3,792 lines) -> base `DAT_1e77dcc4`, size `DAT_1edb9b5c` |
| mhfpac.bin | 1.06 MB | ECD+JKR | 2.26 MB | `pac\x1a` ver 0x0a, relocatable image (sec. 4) | 10afba10 -> base `DAT_1e77dccc`, size `DAT_1edb9b74` |
| mhfinf.bin | 462 KB | ECD+JKR | 1.60 MB | `inf\x1a` ver 6, hdr 0x88 (sec. 5) | 10afae80 -> base `DAT_1e77dcc8`, size `DAT_1edb9b70` |
| mhfsdt/emd/gao/jmp/mec/mfd/msx/nav/rcc/sch/sqd.bin | 0.2-435 KB | ECD+JKR | 0.2 KB-2.5 MB | NO magic; "table of tables" (sec. 6) | 10afcd10/10afa180/10afa670/101cc740/101cc8c0/101ccde0/10afb570/10afb880/10afc870/10afc9d0/101ccf70 |
| rengoku_data.bin | 1.4 KB | ECD+JKR | 8.7 KB | `ref\x1a` ver 1 (Hunting Road / "rengoku") | not located |
| mhf.bin, mhf_90c.bin | 6.4 / 6.9 MB | none | same | pack table, 93 entries: 53 PNG UI atlases + 3 JKR blobs + ~37 layout/script blobs (sec. 7) | - |
| result.bin | 5.7 MB | none | same | pack table, 53 entries, all PNG (7x1024^2, rest 512^2): quest-result screens | - |
| effect.bin, micon64/128.bin, *.txb, others00.txb | | pack tables of PNG/other | | see archive-format.md | - |
Language selection: the mhfinf/mhfpac names are picked by `(&PTR_s_mhfinf_bin_11a45ffc)[ *(int*)(DAT_1e866c5c+0x1db0) ]` (language index): 0 and 2-5 =
`mhfinf.bin`, 1 = `localize-dat\localize-usa-mhfinf.bin`, 6 = `...-kor-...`, 7 = `...-twn-...` (same for mhfpac). mhfdat has no localised variant
in this build (strings inside are mixed Japanese/English: the install is community-translated, low item ids are English, high ids still Japanese). [H]
Loader pattern (all three big files): `buf=malloc(FUN_1000aff0())` ; read file (`.abn` bundle check 1158cb60/1158c940 first, else 1000ad00/1000ae40) ;
ECD decrypt 1158f460 ; verify `*(u32*)(buf+0xc) == 1158f350()` (= seed CRC, else error code 0x10000/0x20000 written to `*param_1`) ; image size = `*(u32*)(buf+0x1c)`
(JKR out size) ; JKR decode 1158f310/1158f240 into a fresh malloc ; check magic/version ; **relocate** (sec. 2.3) ; mhfinf additionally computes an XOR integrity
checksum (seed 0x6d68661a) of the image into `DAT_1e866c1c` and sets bit 3 of `DAT_1e8001f2` when `DAT_1e7ff240==0` (anti-tamper; a modded mhfinf
must not alter the image post-load...it is computed at load so edits are OK) [M].

## 2. mhfdat.bin  (master item/equipment/monster-parameter database)

### 2.1 Header (0xbc8 bytes)  [H]
| off | type | meaning |
|---|---|---|
| 0x00 | char[4] | `mhf\x1a` (u32 0x1a66686d); loader byte 3 is overwritten with 0 after load |
| 0x04 | u32 | version = 0x59 (89) - loader rejects anything else |
| 0x08 | u32 | 0 |
| 0x0c | u32 | header size = 0xbc8 - loader rejects anything else |
| 0x10 | ptr | **count block**: array of u16 counts (3698, 2338, 109, 556, **16701**, 6538, 193, ...) - at file offset 0xcd4180 in this build; ~400 u16 used |
| 0x14..0x33 | u32[8] | zero |
| 0x34..0xbc7 | ptr[0x2ef] | **table pointers** (word index 13..). 735 non-zero. Index = (off-0x34)/4. Each points at a table, string-pointer array or sub-record array |
Counts block index 4 = 16701 = number of items (matches item name array and item record size). Which count belongs to which table is NOT stored; the loader
reads counts as `*(short*)(hdr[4] + 2*k)` with hard-coded k per table (e.g. `+0x400` = count 0x200). Mapping per table is open work (sec. 2.5).
The tables are laid out back-to-back in *descending* pointer order for some groups (armor: leg < waist < arm < body < head), so table size = next higher start.
Offsets 0x34.. 0x38 etc. hold "last array" markers: e.g. `[0xE8]` (end of head armor) and `[0x174]`/`[0x178]` (end markers of ranged/melee).

### 2.2 Relocation scheme (how a rewrite can read the file without the DLL)  [H]
The loader adds the image base to every stored offset in-place. Forms seen in 10af5140:
1. direct `ptr[i] += base` for header words (e.g. `puVar7[4]`, `[0x244]`, `[0x262]`, `[700]`);
2. arrays of pointers terminated by 0 (walk until 0, add base);
3. arrays of fixed-width records where only some words are pointers (e.g. stride 0x24 with ptr at +0x20; stride 9 words, etc.);
4. 2-D structures (table of pointers to lists of pointers to NUL-terminated lists).
A new engine can skip relocation and read offsets directly; every pointer value is `< file size` (verified for all 735 header words) so "value + 0 base" works.

### 2.3 Table inventory with verified strides  [H unless noted]
Ptr slots are header offsets (hex). Region size = distance to next table start. Entry stride confirmed by repeated field patterns/ReFrontier.
| header slot | start (this build) | size | stride | count | content |
|---|---|---|---|---|---|
| 0x100 | 0xb9c0a0 | 0x10500 | 4 | 16704 | **item name** string pointers (index = item id; Shift-JIS/ASCII, NUL-terminated); array ends where item records... see 0xFC |
| 0xFC | 0xbac5a0 | 0x92ca0 | **0x24** | 16701 | **item records** (sec. 2.4). ReFrontier ModShop edits +0x0c (buy) and +0x10 (sell) |
| 0x12C | 0xb8bb40 | 0x10560 | 4 | 16728 | item *description* pointer array (NOT aligned with ids: starts with ~3 extra entries; index = id + k) [M] |
| 0x50 | 0x833f40 | 0x1008d8 | **0x48** | ~14.5k | **armor: head** (ReFrontier `eoHead`=slot 0xE8 = 0x934818) |
| 0x54 / 0x58 / 0x5c / 0x60 | 0x7474c0 / 0x65ad00 / 0x569d40 / 0x47c420 | 0xeca80 / 0xec7c0 / 0xf0fc0 / 0xed920 | 0x48 | ~13.4k each | armor: body / arm / waist / leg. Each table is sparse: index = armor id within class, many all-zero rows |
| 0x64..0x74 | 0x46e000 .. 0x4391e0 | ~54-58 KB each | 4 | ~13.5-14.5k | per-class armor *name* pointer arrays (ReFrontier soStringHead=0x64, Body 0x68, Arm 0x6C, Waist 0x70, Leg 0x74; ends at 0x60,0x64,..) |
| 0x7c | 0x987b20 | 0xdf0c0 | **0x38** (ReFrontier old 0x34) | ~16.3k | **melee weapons** (end = slot 0x90 = 0xa66be0). Names via slot 0x88 |
| 0x80 | 0x949d00 | 0x3de00 | **0x3c** | 4224 | **ranged weapons** (end = slot 0x7c). Names via slot 0x84 |
| 0x84 / 0x88 | 0x934860 / 0x938a60 | 0x4200 / 0x11280 | 4 | 4224/17568 | ranged / melee name pointer arrays |
| 0xad8 | 0xcd9040 | ? | 16 | ? | **equipment skill-effect lists**: 16-byte rows = 4 x {i16 effect_id, i16 value}; referenced by FUN_1081def0 (sec. 3) |
| 0x2ac... | | | | | (quest/shop/monster tables: see open questions) |
Item/armor/weapon *shop* arrays (stride 8, `{u16 itemId,...}`) are found by byte pattern in ReFrontier ModShop (needle `0F 01 01 00 00 00 00 00 03 01 01 00 ...`). [M]

### 2.4 Item record (0x24 bytes)  [M - names/semantics partly guessed from sample rows]
| off | type | meaning |
|---|---|---|
| 0x00 | u16 | 0 in all samples |
| 0x02 | u8 | type/category (1 consumable, 2, 3 books, 4 materials...) [M] |
| 0x03 | u8 | max stack (0x63=99, 0x14=20) [M] |
| 0x04 | u8 | 0x00/0x20: flag bits |
| 0x05 | u8 | sub-category / icon colour row (0x24, 0x23, 0x14, 0x09...) [L] |
| 0x06 | u8 | flags (0..4) [L] |
| 0x0c | u32 | buy price (zenny) [H via ModShop] |
| 0x10 | u32 | sell price [H via ModShop] |
| 0x14 | u32 | rarity-ish (6,5,4,2,1...) [L] |
| 0x18 | u16 | icon / sort id (1,2,3,0x85,0x86,...) [L] |
| 0x1a | u16 | icon sprite index (0x4a9d...) [L] |
| 0x1c.. | 8 bytes | zero |
Items 1-3 "Book of Combos 1-3" are the first real rows; row 0 is all zero except 0x03.. (placeholder).

### 2.5 Armor record (0x48) - ReFrontier layout, header of rows checked  [M]
`+0 i16 modelIdMale, +2 i16 modelIdFemale, +4 u8 flags (bit0 male, bit1 female, bit2 blade, bit3 gunner, bit5 SP), +5 u8 rarity, +6 u8 maxLevel,
+8..+0xb ?, +0xc i32 zennyCost (ModShop sets 50), +0x10 i16 baseDefense? ...` followed by resistances (5 x i8 fire/water/thunder/dragon/ice), slots,
5 x {u8 skillId, i8 points} at 0x38..0x41? (exact offsets: see ReFrontier Structs.cs ArmorDataEntry; the first-row bytes of this build
(`0f 00 11 00 0f 00 07 0b ... 64 00 00 00 01 00 02 00 ... 07 00 49 00 81 00`) agree with that field order for the first 0x20 bytes). Full validation of
every offset for the Z build is still to do.

### 2.6 Weapon records  [M/L]
Ranged (0x3c): `+0 i16 modelId, +2 u8 rarity, +3 u8 maxSlots?, +4 u8 class (0..13 index into classes below)`, price, rawDamage ... (ReFrontier RangedWeaponEntry).
Melee (0x38 in Z; ReFrontier's 0x34 layout is one dword short): `+0 i16 modelId, +2 u8 rarity, +3 u8 class, +4 i32 zenny, +8 sharpnessId i16, +0xa rawDamage i16,
+0xc defense i16, +0xe affinity i8, ...` - NOT yet re-verified on Z rows.
modelId -> model file: id<1000 `we###`, <2000 `wf###`(id-1000), <3000 `wg###`, <4000 `wh###`, <5000 `wi###`, 6000-6999 `wk###`, 7000 `wl###`, 8000 `wm###`
(ReFrontier GetModelIdData; these are the `dat\extend\w?###.bin` bundle names listed in archive-format.md sec. 6).
Class ids (Japanese in ReFrontier): 0 Great Sword, 1 Heavy Bowgun, 2 Hammer, 3 Lance, 4 Sword&Shield, 5 Light Bowgun, 6 Dual Swords, 7 Long Sword,
8 Hunting Horn, 9 Gunlance, 10 Bow, 11 Tonfa, 12 Switch Axe F, 13 Magnet Spike. Elements: 0 none,1 fire,2 water,3 thunder,4 dragon,5 ice,6 flame,7 light,8 thunder-ultimate,
9 tenshou, 10 heat-freeze, 11 black flame, 12 sound, 13 dark, 14 crimson, 15 wind, 16 resonance, 17 scorch-zero, 18 imperial-sound. Ailments: 0 none, poison, paralysis, sleep, blast.
eqType bits (ranged "eqType"): 0 normal, 1 SP, 2 Gou-shu, 4 evolved, 8 HC.

## 3. In-memory item/skill *effect* table (static, in the DLL)  [H structure, M semantics]
* `DAT_118dea08`: array of **0x71 (113) records x 0x14 bytes** = 10 x u16 each; immediately followed (at 0x118df2dc = base + 0x71*0x14) by the callback table
  `PTR_FUN_118df2dc[10]` = {10818c50, 10819760, 10819d40, 1081a010, 1081ace0, 1081b480, 1081bef0, 1081cb50, 1081d500, 1081da40}, then 0, 1.
* Record word 0 (`(u8)table[id*0x14]`, u16 in practice) = **effect type 0..9** selecting the callback; type counts: 0 x80, 1 x13, 4 x7, 3 x5, 9 x3, 2/5/6/7/8 x1.
  Words 1..9 are type-specific parameters (e.g. type 4 rows hold signed offsets 0xfff6, 0xfffc and timers 0xd9b8/0xf6a0/0x0140; type 9 rows hold 0x1555,0x0ccd,500,30,30
  = fixed-point rates). ID range 0..0x70; ids >0x70 are rejected (`if (0x70 < id) break;`).
* Consumer: per character slot (records of 0x1050 bytes at `DAT_1dc6b750`, 100 slots) the tick functions `1081e6a0` (slot0 item at +0x690), `1081e030` (slot1 +0x694),
  `1081e250`, `1081e390` (render-side pass for model attachment, passes `param_1+0xe90` effect list and a 0x1c-byte state per entry at `+0xfe0`), `1081eab0` do:
  1. pick set id: `*(u16*)(slot+0x38e)` or `+0x396` depending on mode (quest type at `*(DAT_1e7fff3c+0x14)` = 0xc9 etc.);
  2. if it changed, `list = FUN_1081def0(setId)`: binary search in a sorted array of `{u16 setId, u16 listIndex}` (count at `*EAX`, array at `EAX+4`) and return
     `listIndex*0x10 + *(DAT_1e77dcc4 + 0xad8)` -> 4 x {i16 effectId (<=0x70), i16 value}; clear the 0x70-byte state at `slot+0x730`;
  3. for up to 4 entries: `type = DAT_118dea08[effectId*0x14]`; if `<10` and callback non-null: `callback(slot, state, ..., level u16 @item+0x20, ptr @item+0x24, entry.value, &table[effectId])`.
  The 0x1c0-byte *part record* (`FUN_10848680(partIdx)`, partIdx capped at 0x75) is the model part the effect (glow/aura/trail) attaches to.
  => This is the **equipment visual-effect system** (weapon/armor glows, trails; ids <= 0x70, ~10 behaviour types), driven by data rows in mhfdat (+0xad8 lists).
  It is not the game-play skill table (that lives in mhfpac sec. 4 and the armor rows).

## 4. mhfpac.bin (skills, UI strings, tables)  [H header, M content]
Header: `pac\x1a`, ver 0x0a, +8 = 0, +0xc = 0x1124 (header size), +0x10 = ptr to u16 count block (0x1395a0 here; counts 18,17,607,106,2,8,21,3,4,2,3,10,4,5,153,33,...), then
pointer table from 0x14. Loader (10afba10) relocates ~0x80 tables incl. 3-/4-/5-/8-/10-/0x13-word records, 0x5c-word records (4 ptrs x 23), nested pointer lists, the table at
`[0x12]` of exactly 0x1a7 (423) 2-word ptr pairs, and 5/8 x lists keyed by `count@+0x20`. After load `byte3` of the magic is cleared.
Verified string tables (ReFrontier offsets still valid; strings English in this install):
| header slot | meaning | count |
|---|---|---|
| 0xA20 (start) .. 0xA1C (end) | **skill-tree names** ("None","Passive","Fate","Backpacking","Auto-Guard","Guard",...) | 232 |
| 0xA1C .. 0xBC0 | **active-skill names** ("No Skill","Para Halved","Negate Para",...) | 536 |
| 0xFBC .. 0xFB0 | Z-skill names | [M] |
| 0xb8..0xc0 | skill descriptions (ReFrontier) - in this build slot 0xb8 points to a different table (strings "pac"); description offsets moved [open] | |
Armor rows (sec. 2.5) reference skill-tree ids via 5 x {u8 id, i8 points}; a skill-tree id indexes the 232-entry tree name array; "active skill" id indexes the 536 array; the mapping
from points to active skill is in tables inside mhfpac (open).

## 5. mhfinf.bin (quests)  [H header, M quest rows]
Header: `inf\x1a`, ver 6, +8=0, +0xc = 0x88 (header size; loader enforces `==0x88`), +0x10 = ptr to descriptor block (0x6a060) whose first i16 = N tables,
+0x14 = ptr to table-of-tables (0x6a0a0): per table `{u16 count, u16 ?, u32 ptr}`; ptr[...]-lists of quest row pointers are rebased (rows pointed to have a 0x28 pointer to a
sub-record with 8 string/data pointers). Pointer slots 0x18..0x84 each have an i16 length at `descriptor + 2k`.
ReFrontier quest block starts in the *old* build: {0x6bd60:95, 0x74100:62, 0x797e0:99, ...} (stride 0xa0? row = 0x40 fixed bytes + 0x5c skip + GRP ints + 0x90 skip + 4 string ptrs + 0x10)
- these absolute offsets belong to the older file and must be re-derived for this build: quest row fields {level u8 @4, courseType u8 @6, fee i32 @0xc, zennyMain/Ko/SubA/SubB i32,
time i32 (frames, 30/s), then 3 goals {i32 type, i16 target, i16 count}; goal type codes 1 hunt, 0x101 capture, 0x201 kill, 2 delivery, 0x1002 guild flag, 0x8004 damage}.

## 6. Header-less table files (mhfsdt/emd/gao/jmp/mec/mfd/msx/nav/rcc/sch/sqd)  [H shapes, L semantics]
No magic. Each begins with a short array of u32 values that are *file offsets pointing forward into the same blob* and/or counts; the blob is a "table of tables" read through
the loader's per-file fixup function. Observed starts (u32): 
* mhfjmp (4645 B): `7a0 6a0 4 680 5 0 0 0` then Shift-JIS strings ("-----", ...). mhfrcc (2556 B): `5c0 7 580 8 5a0`; strings (Japanese names). mhfmec (960 B): `1c0 10 40 1 a0 5 60 d`.
* mhfsch (1216 B): repeating 0x20-byte rows `{u32 0x7db, u32 7, u32 0x14, u32 0xc, 4 x -1}` (0x7db = 2011 = year? / event schedule rows) - looks like an **event schedule** table.
* mhfmfd (35,680 B): `60, 3e20, 3b80, 2f00, dc8, 970, 37a0, 1f` header of 0x60 bytes of pointers/counts then tables. mhfmsx (15,072 B): `120 21 01890186 018b018a ...` (0x120 hdr, 0x21 entries, u16 ids).
* mhfnav (15,272 B): `60 3940 13 3c 20 d ...` nav/menu data (0x13 = 19 entries of 0x3c bytes?). mhfsqd (16,036 B): descending offsets `14c0 2360 2300 22c0 1f00 ...`, strings Shift-JIS full-width digits.
* mhfemd (2.57 MB): `60 26b1e0 2710a0 7a0 20dbc0 360 21fa7c ...` large; loader 10afa180. mhfgao (219 KB): `32d00 40 223b8 223a8 2c420 ...`; loader 10afa670. mhfsdt (779 KB): leading zeros then `10f 0b0420 ...`; loader 10afcd10.
Full decoding deferred (see open questions). Loader functions each: read file, ECD, JKR, verify, relocate - same boilerplate as sec. 1.

## 7. mhf.bin / result.bin / effect.bin  [H]
Pack tables (archive-format.md sec. 2). mhf.bin entries 0-8 and 11-13, 15.. are UI texture atlases (PNG 128x64, 256x256, 256x512, ...); entries 9,10,14 JKR-wrapped
blobs (410 KB / 19 KB / 19 KB); entries 15.. begin with `{u32 0, u32 size-ish}` = layout/animation blobs for 2D UI (not decoded). result.bin: 53 PNG (quest-result/guild screens). These need
no table parser: index = positional id used by UI code.

## 8. Rewrite guidance
1. Implement `ecd -> jkr -> image` once (see mhf_data.py). Treat mhfdat/mhfpac/mhfinf as read-only relocatable images: keep the byte image, resolve a `ptr` by indexing into it.
2. Expose typed views: items (0x24), armor per class (0x48), melee (0x38), ranged (0x3c), skill name arrays, effect lists (+0xad8) and the 113-row static effect table
   (transcribe it from the DLL .data: 0x71 x 10 u16).
3. Language: mhfpac/mhfinf have per-language variants; mhfdat does not (item/weapon/armor names are inside it).

## 8b. Map grid cell accessor (111a5080)  [M]
`FUN_111a5080(this, x:i16, y:i16)` (3217 callers) returns `layerBase + (y*200 + x)*0x28`, where `layerBase = *(int*)((u8)this[3]*0xc0 + 0xb0 + *(int*)(DAT_1e77dce0+0xc))`
(layer index = byte at this+3, layer descriptors 0xc0 bytes). x >= 200 or a null layer returns the dummy cell `DAT_116c76a4`. So the map grid is 200 columns of
0x28-byte cells, y-major, owned by the area/map object `DAT_1e77dce0` (not mhfdat). Cell fields not decoded.

## 9. Open questions
* Q1 exact mapping count-block index -> table, all 735 header slots named (only ~25 identified). Next step: for each loader loop in 10af5140 (look for `*(short*)(puVar7[4] + 0xNN)`) record slot, stride, count index.
* Q2 Z armor/weapon field offsets beyond the first 0x20 bytes; melee 0x38 layout.
* Q3 the 0x2c4-stride record table at DAT_1dbbb441 and the 0x28-byte grid records from 111a5080 (not examined: out of time).
* Q4 mhfinf quest row offsets for this build; mhfpac skill->points tables; mhfdat monster/quest/shop tables.
* Q5 the sorted `{setId, listIndex}` array passed to 1081def0 in EAX (which global; likely a table in mhfdat).

## Weapon rows -> models (2026-10-16)
Melee rows (0x34) and ranged rows (0x3c): +0x00 u16 global weapon model number, +0x03 u8 class (melee: 0 Great Sword, 2 Hammer, 3 Lance, 4 Sword and Shield, 6 Dual Swords, 7 Long Sword, 8 Hunting Horn, 9 Gunlance, 11 Tonfa, 12 Switch Axe F, 13 Magnet Spike; ranged 0-3 own numbering). Model numbers are unique across classes (except 0) and live in dat/extend/w<letter><half>.abn: letter = 'efghijk'[model/1000] (j / 5000s unused), half = 000 if model%1000 < 500 else 500, entry name w<letter><model%1000:03>.bin (entries are model packs: fmod + 4-bone skeleton + PNGs). 21714 of 21787 named rows resolve (test_weapon_models). Melee row 1 = model 10 (we010, an iron-style great sword).

Melee row fields confirmed by name (2026-10-16): +0x04 u16 price (Iron Sword 1320, Iron Sword+ 1910, Buster Sword 2750, Royal Flawless 50000), +0x0a u16 raw attack (60 / 70 / 80 / 230). +0x16 u8 rises along upgrade lines (1, 2, 3, 9, 10, 190, 255): rarity or tree index, unconfirmed. Names (header 0x88 pointer array) are cp932 text, English in this install.

Melee row element / affinity / sharpness (2026-10-16, from name patterns over ~40 named weapons): byte +0x0f element type 1 fire (Red Wing, Rath Blaze, Flame Syphos), 2 water (Plesioth line, Aqua Spear), 3 thunder (Kirin Bolt, Thunderspear), 4 dragon (Dragon Killer, Dragon Breaker), 5 ice (Icesteel, Frost Edge); byte +0x10 element value / 10 (Red Wing 38 = 380; rises along upgrades: Kirin Bolt 25/28/33/44). s16 +0x0c affinity % (Kirin Bolt line 2/6/10/16, Royal Flawless 20) - likely. u16 +0x18 sharpness table index, shared within a family (Plesioth 23, Rathalos 24, Kirin 71/72) - table not located yet. Bytes +0x11/+0x12 look like status type/value (Dragonwood weapons: 2 / 28), +0x0e, +0x13, +0x15 small counts (slots?) - open. Confirm with in-game values (user).

SHARPNESS (2026-10-16, from client function 10a98750): header slot 0xac -> array of u32 pointers indexed by weapon class (0..13; classes share tables: GS/HBG/LBG/LS/Bow 0x1902d00, hammer/HH 0x1902500, lance/GL 0x1901d00, SnS 0x1901500, DS 0x1900d00, tonfa 0x1900500, SAF 0x18ffd00, MS 0x18ff500 in this build). Gauge = table + (melee row byte +0x08) * 16: 8 cumulative u16 thresholds red, orange, yellow, green, blue, white, purple, (8th) up to 400. Colour level = number of thresholds below the current sharpness value (+1 from a skill-like check). CORRECTION: +0x18 is NOT the sharpness index (meaning open). The weapon's starting/maximum sharpness value is separate (byte +0x09 candidate).

Sharpness at runtime (2026-10-16, client 108b80c0 / 10a98750 / 102e3b40 / 10a694f0): hunter struct s16 +0xb26 = current sharpness, s16 +0xb2c = maximum, byte +0xb2f = cached colour level. Each landed hit subtracts 3 by default (skill-like checks change it to 1 or 6, or halve it; a per-class extra comes from mhfdat header 0xa8c table [class] s16), clamped to 0 and never above the max. Sharpening sets current = max. Where the max comes from (weapon row field vs gauge minus a fixed amount) is still open - read +0xb2c live.
