# MHF-Z file loading and container formats (engine-neutral spec)

Status: 2026-10-13. Sources: Ghidra decomp of `mhfo-hd.dll` (addresses are image VAs, base 0x10000000) and byte-level
inspection of `C:\Users\Ayman\Desktop\MHFZ\dat`. Reference extractor/test tool: `tools\mhf_archive.py` (python -I).
Confidence tags: [H] verified against real files and/or fully read code, [M] read from code, not byte-verified, [L] inferred.
All integers little-endian unless stated.

## 1. Layering overview

A file on disk is zero or more *wrapper layers* around a *pack table* or a raw payload:

```
disk file := [ECD encryption]? -> [JKR compression]? -> payload
payload   := pack table (nested, entries are again "file := ..." recursively) | raw asset (PNG, OggS, MOMO sound, ...)
```
Wrapper detection is by 4-byte magic at offset 0 of each blob (any nesting level): `ecd\x1a` (65 63 64 1a), `JKR\x1a`
(4a 4b 52 1a), `exf\x1a` (65 78 66 1a, sound only). Files with no magic are treated as plain (see 4). Counts from the install
(6836 files): ecd 1348+490+94 (.pac/.bin/.txb), JKR 281 top-level (.bin/.mot), pack-table-only (no wrapper) ~1000, exf 539 (.mus). [H]

## 2. Pack table (the universal container)  [H]

| off | size | type | meaning |
|---|---|---|---|
| 0 | 4 | u32 | count N |
| 4 + 8*i | 4 | u32 | entry i offset (from start of this table blob) |
| 8 + 8*i | 4 | u32 | entry i size in bytes |
| 4+8N ... | | | entry bodies, back-to-back, NO padding/alignment in the files checked |

* Entries may be empty (size 0; e.g. em003.pac entries 3,4 -> unused slots). The runtime treats `size == 0` as "slot absent" and
  tests the size field directly (`buf[2*i+2] != 0`) - fn 108fba70, 1089ef20.
* Entries are themselves arbitrary blobs and are frequently wrapped again (JKR) or are nested pack tables.
* Re-building a table with the same entries reproduces the original file byte-for-byte (tested on em001.pac, em001-hd.pac,
  mhf.bin, st462.pac). So a simple writer is sufficient; offsets are not otherwise validated by anything we saw [M].
* Variants: some `.mot`/`.bin`/`.gab` are pack tables whose header is followed by padding; the same rule holds.
* Known pack-table files: mhf.bin (93 entries; also `mhf.bin.xbox`, `mhf_90c.bin`), effect.bin, result.bin, micon64/128.bin, *.txb
  (charsel, demo, map, ...: entries are PNG textures etc.), *.pac (models, stages), npc\*.bin, weapon\*.bin, *.gab, motion\*.mot.
* A pack entry list is *positional*: game code addresses sub-files by index (see 6 for em*.pac). No names/ids are stored.

## 3. ECD encryption wrapper (`ecd\x1a`)  [H]

Header (16 bytes), payload follows at +16:

| off | size | type | meaning |
|---|---|---|---|
| 0 | 4 | char | `ecd\x1a` |
| 4 | 2 | u16 | key index (0..5), indexes the LCG table below. All shipped files use 4 |
| 6 | 2 | u16 | filename check value (see below). Only evaluated when key index >= 4 |
| 8 | 4 | u32 | payload length (= file size - 16) |
| 12 | 4 | u32 | seed = CRC32 (zlib, standard poly 0xEDB88320) of the DECRYPTED payload (verified on 2 files; also used as key seed) |

Key table (fn context 1158f460, table at VA 0x115df198; each entry {u32 mul, u32 inc}):
`0:(0x4a4b522e,1) 1:(0x10dcd,1) 2:(0x10dcd,1) 3:(0x10dcd,1) 4:(0x19660d,3) 5:(0x7d2b89dd,1)`  (index 4 = Numerical Recipes LCG).

Decryption (stream cipher, byte at a time; state `s`, all u32 arithmetic mod 2^32; implemented in `ecd_decrypt`):
```
s    = ((seed | 0x10000) >> 16) | (seed << 16)        ; rotate by 16 (bit16 forced on before shifting right)
s    = s*mul + inc
prev = s & 0xff
for each cipher byte c:
    s  = s*mul + inc
    t  = c ^ prev
    hi = t >> 4;  loc = s
    repeat 8 times:  b2 = hi;  hi = ((b2 ^ loc) & 0xff) ^ t;  loc >>= 4;  t = b2
    plain = (b2 << 4) | (hi & 0xf)
    prev  = plain                                     ; the PLAINTEXT byte feeds the next byte
```
(The loop body is a literal restatement of decomp 1158f460; verified: outputs start with JKR/pack-table/ `pac\x1a` data
and CRC32(plain) == header seed for every tested file; 167 sampled ECD/JKR files unwrapped with 0 failures.)

**Filename check (header u16 @6)** [M, algorithm partly unresolved]: when key index >= 4 the loader computes
`h = ~(crc32-like(UPPERCASE(basename+extension))) >> 7` (16 low bits) and requires `h == u16@6`; on mismatch the file is
returned undecrypted (so later parsing fails). Fns 1158f510 (and the same logic in the exf opener 114d9c70). My attempts to
reproduce the value with zlib CRC32 under 8 variants (init 0/~0, case, final ~) did NOT match the observed header values, so the
exact seed/init of the hash is unknown (open question Q1). Consequence: do not rename ECD files on disk without checking this.
Also: the name used is passed by the caller or, if null, read from the string the loader appended after the file bytes (see 7).

**Plaintext is accepted.** 1158f510 returns immediately when the magic is not `ecd\x1a`, so an unencrypted file with the
same name is loaded as-is by the file-layer [M, strong]. This is the easiest way to inject modified assets (no encryptor needed).
An encryptor is not implemented (the cipher is invertible per byte by trying 256 cipher values; not needed so far).

## 4. JKR compression wrapper (`JKR\x1a`)  [H]

Header 16 bytes (fn 1158f240 parses it):

| off | size | type | meaning |
|---|---|---|---|
| 0 | 4 | char | `JKR\x1a` |
| 4 | 2 | u16 | version (files: 0x0108) |
| 6 | 2 | u16 | type: 0 = stored, 2 = (second Huffman-ish mode, decoder 1158f220 not seen; no files use it), 3 = LZ, 4 = Huffman-coded-bytes + LZ |
| 8 | 4 | u32 | offset of compressed data (always 0x10) |
| 12 | 4 | u32 | decompressed size |

LZ stream (decoder 1158efe0; bits MSB-first from a flag byte fetched on demand, `rd()` = next *byte* from the byte source):
```
bit() : if no bits left: flag = rd(); 8 bits left;  return next bit from MSB
loop until out_size bytes produced:
  if bit()==0: out += rd()                                   ; literal
  elif bit()==0:                                             ; "10"
      n = (bit()<<1 | bit()) + 3 ; d = rd() ; copy n bytes from (out_end - d - 1)
  else:                                                      ; "11"
      a = rd(); b = rd(); d = ((a & 0x1f) << 8) | b
      if a & 0xe0:  n = (a >> 5) + 2 ; copy n from (out_end - d - 1)
      elif bit()==0: n = (4 bits MSB-first) + 0x12 ; copy
      else: c = rd()
            if c == 0xff: copy (d + 0x1b) literal bytes taken straight from rd()
            else:         n = c + 0x1b ; copy
```
Copies are byte-wise (overlap allowed; distance d+1). [H: the 0x12 constant was found empirically; 0x03 fails.]
Type 3: `rd()` reads raw bytes from data_off. Type 4: `rd()` decodes one byte from a Huffman tree (fn 1158eec0):
at data_off: u16 `root`; then (root-0xFF) nodes of 2 x u16 (child for bit 0, child for bit 1; value <= 0xFF = leaf byte, >= 0x100 =
internal node id; node k lives at table index (k-0x100)); bitstream (MSB-first, byte-aligned, shared by ALL rd() calls including flag
bytes and offset bytes) begins at data_off + root*4 - 0x3fa (= right after the node table). Start at node `root`.
Sample counts: motion/*.mot and load/*.bin are JKR type 3/4; ECD+JKR combined occurs in mhfpac.bin etc. The runtime decodes
into the destination without a size guard other than `out_size`, so a larger decompressed size needs a larger destination buffer (see 8).

## 5. EXF sound wrapper (`exf\x1a`) - .mus  [L]

Header: magic, u16 key idx (4), u16 name check (lowercased basename, only when idx>=4; fn 114d9c70), u32 @8 (0 in samples),
u32 @12 seed. 16-byte key words derived `k0=(mul*seed+inc)^seed` ... (fn 114d9bd0; table 0x115fccb8, idx4 = {0x2e90edd,3}). Used as
a streaming-read callback for libvorbis (`OggS` inside; 223 .mus files are already plain `OggS`). The keystream use is NOT resolved;
a naive repeat-XOR and a reuse of the ECD cipher both fail (Q3). Irrelevant to models/textures.

## 6. Other container types seen

* `.abn` ("mha\x01") bundles [H structure, M semantics]: `dat\extend\*.abn`, `dat\wd000snd.abn`. Header: magic `mha\x01`, u32 index_off,
  u32 count, u32 names_off. Index at index_off: count x 20-byte records {u32 name_off (relative to names_off), u32 data_off, u32 size,
  u32 padded_size, u32 ordinal}. Names are NUL-terminated strings (`we000.bin`, `f_arm000.bin`, `wd000.snd`). Data blobs are pack tables or
  MOMO sound banks. The game ("pack_read" logging in 1158c420/1158c5b0) hooks these: a request for a loose path
  like `dat\extend\we123.bin` is matched against a static table of bundle names (VA 0x115f4798: we000/we500/wf000/.../f00_arm/m00_body/...,
  fns 1158cb60, 1158c940, 1158ca50) by prefix + numeric suffix; if the numeric id falls in the bundle's range and its size != 0, the bytes are read
  from the .abn at data_off; otherwise the loose file is used. A warning is logged if size > caller buffer size but the read is not aborted. [M]
* `MOMO` (4d 4f 4d 4f): sound bank in .snd/.snp (version u32, header size 0x40...). Not analysed.
* Textures: PNG (89 50 4e 47) stored directly as pack entries, decoded by a memory texture-create call (fn 10011af0). Slot-based (see 7).
* `ffff0900`/`ffff0800` blobs in load\*.bin = script/loading-screen data after JKR (not analysed). `pac\x1a` seen as payload of mhfpac.bin after ECD+JKR.
* `.xbox` copies of mhf.bin/mhf_90c.bin are plain pack tables (unused on PC).

## 7. File-load path (task pump 115904c0)  [M/H]

* 1024-slot ring of 0x4c-byte task records (index DAT_1e866ce4, `& 0x3ff`), table at 0x1e866d40; `DAT_1e866ce0` = busy flag.
  Record: +0 u32 type, +4 destination buffer ptr, +0x0c NUL-terminated filename (inline, up to 0x40 bytes), +4..+0x14 also
  hold callback args for types 1/4.
* Types handled by 115904c0: 1 = call fn(p[2..5]); 2 = whole-file read of `task+0xc` into `task+4`; 3 = overlapped read in flight
  (polled with GetOverlappedResult); 4 = polled callback; 5/6/7 = hand off to a worker thread (event DAT_1e866d14/d18) that runs fn 115903a0.
  Next record: fn 11590230 advances the ring.
* Type 2 (and 115903a0) flow: first ask the .abn bundle layer (1158c940 sync / 1158ca50 overlapped) whether the filename is bundled;
  if not, `CreateFileA(GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING)` + `GetFileSize` + `ReadFile` into `task+4` (overlapped flag 0x40000000 when
  `DAT_1e866ca4 & 0x200`). **After the file bytes, the loader appends the filename string at dest+filesize** (loops copying NUL-terminated name).
  This is the "name after payload" later consumed by the ECD name check (1158f510 uses `buf + size + 0x10`). The destination buffer
  therefore needs filesize + strlen(name)+1 bytes.
* Synchronous variants: 108e27d0 (fread whole file via 1000ad00 into buffer, then ECD decrypt via 1158f510; returns 0 on failure) and
  108e2850 (same but silent: used as "does an HD file exist" probe); both take the destination in a register and compute the size with
  1000aff0/1000b0b0. Pattern: `if (!load(hd_path)) load(sd_path)`.
* Asset roots under `dat\`: emmodel\ + emmodel-hd\ (monsters), stage\ + stage-hd\, extend\ (.abn, equipment/player parts), motion\, load\, npc\,
  weapon\, sound\ (+ sound\mus), my_gallery\, ryoudan\, campaign\, efeq\, parts\, mhf_90c\, plus top-level `*.bin/*.txb` data files.

### Path resolution for monsters (fn 108fba70 loader, 108fc420 variant; format strings at VA 0x1199ffa0..0x119a00bc)  [H]
For monster id `NNN` (decimal, 3 digits, `%03d`) it picks a suffix by predicates (set tests 1087cb30, 1087bb00, 1087bb50, 1087c030):
`_e`, `_d`, `_c`, `_b` or none (and `_b_%d` / `_%d` with a variant number for ids 0x5d, 0x95), then tries, in order:
1. `dat\emmodel-hd\emNNN[suffix]-hd.pac`   (HD file; 3.5 MB for em001)
2. `dat\emmodel\emNNN[suffix].pac`        (SD fallback)
The same for stages: `stage-hd\stNNN-hd.pac`, `stage\stNNN.pac`, `stage-hd\somNNN.pac`, `sefNNN.pac`, `nsoNNNN.pac`. The HD DLL therefore prefers HD
files when present; the engine's sets of recognised suffix classes are the source of truth for the suffix (not derivable from the filename).

## 8. em*.pac layout and loader limits (what breaks if you change a file)

Observed layout, em001 (SD 7 -> HD 7 entries; HD adds entry 6; table is ECD-wrapped on disk, entries sometimes JKR). Index = pack entry:

| idx | SD em001 | HD em001-hd | consumer |
|---|---|---|---|
| 0 | nested pack x2: [0] JKR mesh blob (326 KB unpacked), [1] raw 12.9 KB | same, mesh 854 KB (2.6x vertices) | model/mesh -> fn 108f88e0 via model slot (`FUN_108f88e0(slot, base, 0, 0x5ed+slot*0x48, 0, 0x20900, 2)`) |
| 1 | pack x4 PNG 256x256 | pack x12 PNG 512x512 | texture set A: fn 108df890/108df7d0 -> create D3D textures from memory |
| 2 | JKR -> pack x100 (motion/animation set) | identical (same bytes) | fn 108fd380 (when size != 0) |
| 3 | nested pack x2: JKR + raw | identical | second model (e.g. shadow/part): own slot |
| 4 | pack x3 PNG | identical | texture set B: base 0x631+slot*0x48 |
| 5 | ECD-wrapped pack x3 (config/param tables) | identical | fn 113d5a90 when count > 5 and size != 0 |
| 6 | (absent) | 2297-byte material table | fn 108fcd70, loaded only when count > 6 and size != 0 |

Fields/limits the loader enforces (fn 108fba70 unless noted):
1. **Static destination buffer**: file buffer pointer `DAT_1ed528bc` = fixed arena `0x1c404740`; the next arena begins at `0x1d204740`
   -> **14 MiB (0xE00000) for the whole unwrapped pac (plus the appended filename)**. ECD decrypt happens in this arena. The texture/model
   scratch arena `DAT_1ed528b8 = 0x13404740` has 0x9000000 (144 MiB) up to the pac arena. Arenas are laid out in 108e33a0 and are `memset`-
   cleared at startup; none is bounds-checked. HD em001 unwrapped = 3.56 MB. Growing a pac past ~14 MiB overwrites the adjacent arena (crash) [M].
2. **Per-slot texture index space**: texture set A is registered at global slot base `0x5ed + monsterSlot*0x48`, set B at `0x631 + monsterSlot*0x48`
   (so set A may hold at most 0x44 = 68 textures before colliding with set B; one monster slot spans 0x48 = 72 ids). Model materials reference
   textures by *index into entry 1/4*, remapped to `slot_base + idx` (loop in 108f88e0 using `DAT_1ecda320`). If you reorder/add textures, the
   indices stored inside the mesh blob (entry 0) must be consistent. HD em001 uses 12 textures vs 4 SD: the HD *mesh blob* is different, so
   **textures and mesh are a matched set; swapping only one side desynchronises indices**. [M]
3. **Material-table validation (entry 6, HD only; this is a direct crash source)**: fn 108fcd70 parses entry 6; format:
   optional 1-byte version prefix (present when first byte >= 0x20), then 16-byte header {u8 group_count, 15 padding bytes (0xCC)},
   then group_count x { 16-byte group header {u8 material_count, 15 pad}, material_count x 100-byte material record }. Legacy form (<0x20) uses 0x60-byte records.
   (em001-hd: 0x20, 5 groups, 22 materials: 1+16+5*16+22*100 = 2297 - exactly the file size.) Material record = 25 x f32-ish: color vectors
   (diffuse/ambient/specular-like, 4x f32 each, observed 1,1,1,1 / .5,.5,.5,1 / ...), and shininess-like trailing floats; copied into the model's
   material table (stride 0x8c bytes per material, fields 1-4, 9-0xc, 0x16-0x19, 0x1a-0x1c, 0x1f-0x22).
   The loader then **requires group_count == the model's object/mesh count** (slot field @+0x2c) and **each group's material_count == the model's
   per-object material count**; on mismatch it shows a `MessageBoxA` titled "Error" naming the pac path and discards the data. Therefore: any
   HD model whose mesh-object/material counts differ from entry 0 must ship a matching entry 6; entry 6 must be edited/regenerated whenever
   materials are added/removed. For SD pacs (no entry 6) this check is skipped (defaults are applied by the second loop at the end of 108fba70).
4. Entries 5/6 are consulted only if the pack count is > 5 / > 6 (`*buf > 5`, `> 6`), so an HD pac with only 6 entries is valid.
5. Count field `buf[0]` must cover all consumed indices; consumer tests `size != 0` per entry, so absent parts use size 0.
6. JKR outputs are decoded into the pointer the sub-loader supplies; there is no size passed beyond header `out_size`, so make header size exact.
7. The monster slot id is not stored in the file; it is a runtime assignment (`FUN_108f80a0(1)` allocates a 0x80-byte slot in the table at DAT_1ed528d0).
   Allocation can fail (negative return -> loader aborts silently) when too many models are resident; HD content that holds more simultaneous
   textures raises that pressure.
8. D3D texture creation (fn 10011af0) takes the PNG blob and its size directly; PNG dimensions are not constrained by the pack format.
   (Not verified: any hard limit on texture width/height or total VRAM budget elsewhere.)

## 9. Extracting / listing

`python -I tools\mhf_archive.py info <file>` (layers + whether root is a pack table), `unwrap <file> <out>`, `list <file>` (entries of unwrapped table),
`tree <file>` (recursive listing, depth 4), `extract <file> <dir>` (entries -> `0000.bin`...; wrapped sub-entries stay wrapped), `repack-test <file>`.
Library functions: `unwrap(buf)`, `ecd_decrypt(buf)`, `jkr_decompress(buf)`, `pack_table(buf)`, `pack_build(blobs)`.
Tested: 167 random ECD/JKR files (<400 KB) unwrap with 0 errors; 4 files repack byte-identically.

## 10. Open questions

* Q1: exact ECD filename hash (init/seed of the CRC-like fn 1158f350, which receives its start state in EAX from the caller) - affects renamed files.
* Q2: whether the task-pump read path (type 2) applies the ECD/JKR layers or the callers do it afterwards (the em loader calls 108e27d0, which does ECD itself;
  JKR for sub-entries is applied by the sub-loaders: 1158f240 has 89 callers).
* Q3: EXF keystream (see 5); JKR type 2 mode (fn 1158f220).
* Q4: meaning of every field in the entry-0 mesh blob and of the 100-byte material record; per-monster-id suffix predicate tables (1087cb30/1087bb00/1087bb50/1087c030).
* Q5: whether replacing `em00x-hd.pac` with an unencrypted file really loads (the DLL path says yes, untested in game).
* Q6: texture format limits (D3D device caps) and the actual per-slot texture count cap from `DAT_1ecda320` (array of ~4253 words).
* Cross-check against mhvuze/ReFrontier (not fetched in this session): JPK/ECD terminology there matches (ECD = encryption, JPK = JKR compression types 0/2/3/4),
  consistent with what was derived here independently.

## 11. Evidence index (function addresses)
115904c0 task pump; 11590230 ring advance; 115903a0 threaded read; 1158c940/1158ca50/1158c420/1158c5b0/1158cb60 .abn bundle lookup+read;
1158f510 ECD open; 1158f460 ECD decrypt; 1158f350 CRC-like table hash (table 0x115ded98 = standard CRC32 table); 1158f240 JKR header;
1158efe0 JKR LZ; 1158ef30/1158ef50 bit/copy helpers; 1158eec0 JKR Huffman byte; 114d9c70/114d9bd0/114d96a0 EXF open/key/stream cache (0x2800-byte blocks);
108e27d0/108e2850 load+ECD; 1000ad00/1000adb0 fread-whole-file; 108fba70/108fc420 monster pac load; 108fcd70 material table; 108f88e0 model init;
108df7d0/108df890 texture-set registration; 108e33a0 arena layout (0x1c404740 pac arena = 14 MiB).
