# MHF-Z 3D model / mesh / texture format (engine-neutral spec)

Status: first full pass, 2026-10-13. Source of truth = static reading of `mhfo-hd.dll` decomp (`decomp\<addr>.c`, base 0x10000000)
**plus** verification against the real game files in `C:\Users\Ayman\Desktop\MHFZ\dat` (`emmodel\*.pac` = SD, `emmodel-hd\*-hd.pac` = HD).
Everything in sections 1-5 was reimplemented in Python (`tools\mhfpac.py`, `tools\mhfmodel.py`) and run over **all 303 SD and 278 HD
monster pacs with zero parse errors**; index ranges, weight sums, material partitions etc. all check out (details in section 11).

Confidence tags: **[V]** verified on real data AND matches decomp; **[D]** derived from decomp only; **[I]** inferred / guess.
"Evidence" addresses are functions in the decomp (`FUN_xxxxxxxx`). All structure sizes are 32-bit little-endian x86.

---------------------------------------------------------------------------------------------------

## 0. Big picture (what a rewrite needs to know)

```
dat\emmodel[-hd]\emNNN[_x][-hd].pac           (monster; ECD-encrypted in ~85 % of files, plain otherwise)
  = PAC archive of 6-7 entries
      0  archive[ JKR(fmod model) , JKR(fskl skeleton) ]
      1  archive[ PNG textures... ]            <- model 0 textures
      2  JKR( motion / animation bank )        (not covered here, see 9.4)
      3  archive[ JKR(fmod), JKR(fskl) ]       <- optional 2nd model (parts / alt)
      4  archive[ PNG textures... ]            <- model 3 textures
      5  JKR( archive[3] of tables )           (effect / hit tables, not covered)
      6  (HD only) per-mesh material-parameter table (section 6.4)
```
Pipeline in the DLL: read whole file -> (ECD decrypt) -> split PAC -> JKR-decompress model+skeleton into a fixed arena ->
parse chunk tree -> build D3D9 vertex/index buffers + material records + bone records -> textures via
`D3DXCreateTextureFromFileInMemoryEx` straight from the PNG bytes.

---------------------------------------------------------------------------------------------------

## 1. Container layers

### 1.1 ECD (`'ecd\x1a'`) outer encryption  [V]
Evidence: `FUN_1158f510` (verify+call), `FUN_1158f460` (cipher), key table at VA `0x115df198`, CRC table `0x115ded98`.
Loader accepts **plain files too** (returns immediately if magic != ecd) -> a modded file does not need to be encrypted.

| off | size | field |
|---|---|---|
| 0x00 | 4 | magic `65 63 64 1a` |
| 0x04 | u16 | key index `k` (0..5). Files seen: 4 mostly |
| 0x06 | u16 | name check (only enforced when `k >= 4`): `(CRC32reg(UPPER("NAME.EXT"), seed=hdr[0x0c]) >> 7) & 0xffff` (the register value *before* the final NOT; seed is the raw header field, not 0xFFFFFFFF). Name = upper-cased file stem+extension of the real path (or an embedded name appended after the payload). **Renaming an encrypted file breaks it.** |
| 0x08 | u32 | payload size |
| 0x0c | u32 | seed (random per file) |
| 0x10 | size | ciphertext |

Key table (mul, add) per index: 0:(1246450222,1) 1,2,3:(69069,1) 4:(1664525,3) 5:(2100005341,1).
Cipher (per byte, state u32): `s0 = ((seed|0x10000)>>16 | seed<<16)*mul+add; dl = s0&0xff;`
for each byte: `s = s*mul+add; t = c ^ dl; a = t>>4; cp = s; repeat 8: {d2=a; a = a ^ (cp&0xff) ^ t; cp >>= 4; t = d2;}`
`plain = ((d2<<4)&0xff) | (a&0xf); dl = plain`  (so the keystream depends on the previous *plaintext* byte).
Reference implementation: `tools\mhfpac.py: ecd_decrypt`. No content CRC is checked (the second CRC call in `FUN_1158f510` has its result discarded).

### 1.2 JKR compression (`'JKR\x1a'`)  [V]
Evidence: `FUN_1158f240` (header/mode), `FUN_1158efe0` (LZ token decoder), `FUN_1158eec0` (Huffman byte getter), `FUN_1158ef30/ef50` (bit/copy helpers).

| off | size | field |
|---|---|---|
| 0 | 4 | `4a 4b 52 1a` |
| 4 | u16 | version (0x0108) |
| 6 | u16 | mode: 0 = raw copy, 2 = (huffman-wrapped raw; unused in data), 3 = LZ, 4 = Huffman-coded bytes + LZ |
| 8 | u32 | offset of payload from start of JKR block (0x10) |
| 12 | u32 | **decompressed size** |

LZ token stream (mode 3/4), flag bits MSB first, 8 per flag byte; every "byte" fetch goes through the Huffman getter in mode 4:
`0` = literal; `10 b1 b0` = copy len `(b1b0)+3`, dist byte+1; `11` = two bytes `h,l`: `dist=((h&0x1f)<<8|l)+1`, `len=(h>>5)+2` if `h>>5 != 0`;
else `0 b3b2b1b0` len = nibble+10 (0x0a); else `1 c`: `c==0xff` -> raw copy of `dist_field+0x1b` literal bytes, else len = c+0x1a (26).
Mode 4 Huffman: after the u16 `L` at payload start comes a table of `(L-256)` nodes, 2 x u16 children each (value < 256 = leaf byte, else node id);
decode starts at node `L`, bit order MSB first, child index `(node-256)*2+bit`; coded bit stream begins at `payload + 4*L - 0x3f9`
with the byte at `-1` as the first bit-buffer byte.
**Mode 0 (raw) is accepted**, so a mod tool needs no compressor. Reference: `tools\mhfpac.py: jkr_decompress`.

### 1.3 PAC archive  [V]
`u32 count; { u32 offset, u32 size } * count` (offsets absolute from start of this block; entries may have size 0).
Entries can themselves be PAC archives (nested, offsets relative to the nested block) - `FUN_108df4b0`, `FUN_108df7d0`.
If an archive item is not JKR it is `memcpy`'d with the table size (`FUN_108df4b0`), so uncompressed items work.

Monster pac entry roles (from `FUN_108fba70` checks `hdr[4]!=0`, `[6]`, `[8]`, `[10]`, `[12]` (needs count>5), `[14]` (needs count>6)):

| entry | content | evidence |
|---|---|---|
| 0 | nested PAC of 2: `JKR(fmod)`, `JKR(fskl)` | `FUN_108df4b0` -> dest A, dest B |
| 1 | nested PAC of N PNG images (texture array for model 0) | `FUN_108df7d0` |
| 2 | JKR animation bank (`FUN_108fd380`) | not decoded here |
| 3 | optional 2nd model (same layout as 0) | `FUN_108f8140` path |
| 4 | PNG array for model 3 | |
| 5 | JKR nested PAC of 3 small tables | `FUN_113d5a90` |
| 6 | **HD only**: per-mesh material parameter blocks | `FUN_108fcd70`, section 6.4 |

File selection (`FUN_108fba70`, strings @0x1199ffa0..): tries `emmodel-hd\em%03d[_b|_c|_d|_e]-hd.pac` first, falls back to `emmodel\em%03d[...].pac`.
Suffix chosen by predicates `FUN_1087cb30(id,0x10)`, `FUN_1087bb00`, `FUN_1087bb50`, `FUN_1087c030` (monster-variant tables); ids 0x5d/0x95 use `em%03d_%d.pac`. **So an HD file, if present, always wins.**

---------------------------------------------------------------------------------------------------

## 2. FMOD chunk file (model)  [V]

Everything is a tree of chunks. **Chunk header = 12 bytes: `u32 type, u32 count, u32 size`** where `size` is the total byte length
*including* the header (next sibling = this + size). The meaning of `count` depends on the type (child count for containers,
element count for arrays). Helper getters: `FUN_10002680` (i-th child of the first type-2 chunk), `FUN_10002740` (i-th child of type 9), `FUN_100028f0` (i-th child of type 0xa),
`FUN_10002630`/`FUN_100026f0` (counts of type 2 / type 9).

### 2.1 Top level
```
root  type=1 count=4 size=filesize
 +0x0c  type 0x20000 count=1 size=0x10  payload: u32 'hdr' (0x020b1c00 / 0x040b1c00 / 0x060b1c00 / 0x080b1c00 / 0x0a0b1c00 seen; top byte 2..10 even, meaning [I] unknown)
 +0x1c  type 2  count=M   container of M meshes
 ...    type 9  count=N   container of N material chunks
 ...    type 0xa count=N  container of N texture descriptors (one per *texture reference*, see 5.3)
```
Order in all 581 real files: `0x20000, 2, 9, 0xa`. [V]

### 2.2 Mesh chunk (type 4, child of type 2; count = number of children)
| child type | count = | payload | meaning | conf |
|---|---|---|---|---|
| 5 | number of strip groups (always 2) | children of type 0x30000 and 0x40000 | triangle-strip index lists, see 2.3 | V |
| 0x50000 | #materials used by this mesh | `u32[count]` | **global material indices** (into the type-9 list) this mesh uses; a strip's material value indexes *this list* | V (lists of all meshes partition 0..N-1 exactly) |
| 0x60000 | #strips (all groups, in order) | `u32[count]` | per-strip local material slot (index into 0x50000 list) | V |
| 0x70000 | V = vertex count | `float3[V]` position | | V |
| 0x80000 | V | `float3[V]` normal (unit length: 805/805 within 1 %) | | V |
| 0xa0000 | V | `float2[V]` uv (0..1) | optional: absent -> untextured vertex format | V |
| 0xb0000 | V | `float4[V]` vertex colour R,G,B,A in **0..255 float** (255.0 = white) | | V |
| 0xc0000 | V | variable records: `u32 n; { u32 bone, float weight_percent } * n` | skin weights (n<=4; weights sum to 100.0, bone ids 0..bones-1) | V (n=1..3 seen) |
| 0x100000 | #bones used | `u32[count]` | list of **skeleton bone ids** used by this mesh (skinning palette); only on some meshes | V presence, [I] use (see 6.3 palette) |
| 0x120000 | V | `float4[V]` per-vertex vector (**tangent** xyzw) | HD models only (268 of 278); needed for normal maps | V presence / D role (`FUN_10003190`, GPU decl TANGENT) |
| 0xe0000 | 1 | `u32 n; u32[n]` all 0xffffffff in samples | unknown (26 SD models only; 2 HD) | I |
| 0xf0000 | 1 | 18 dwords: `[0]=0x10000 (version)`, `[1..17]` render-state selectors | per-mesh render state, see 2.5 | D |

A mesh with no 0xc0000 is **rigid** (format code 0x25/0x35); one with 0xc0000 is skinned (0x4135) - `FUN_10002af0` dispatch:
0xc0000 present -> `FUN_10003790`; else 0x120000 present -> `FUN_10003190`; else `FUN_10002bf0`.
Verified on 303+278 files: all 0x70000/0x80000/0xa0000/0xb0000/0xc0000 counts per mesh are equal (**single index space, no separate
position/normal/uv index arrays**) and max strip index = V-1.

### 2.3 Strip groups
Chunk type `0x30000` and `0x40000` (count = number of strips S):
`S` records back to back: `u32 head; u32 index[head & 0x7fffffff]`. `head` bit31 = per-strip flag (unseen in samples, loader keeps it as 0x8000 vs 0x4000
tag in the converted stream and uses it to decide whether a degenerate join needs an extra index; behaves as "strip starts with odd parity" [I]).
Primitive type = **triangle strip** (`D3DPT_TRIANGLESTRIP`, prim count = len-2). Winding (verified on 4 models): for even triangles `(i,i+1,i+2)`
`cross(p1-p0, p2-p0)` points along the vertex normals; odd triangles are the parity-swapped ones (standard strip convention).
Group `0x30000` vs `0x40000`: the converter writes group id 0 / 1 per strip (skinned path, `FUN_10003790` flag 0x200000); the second group is a different draw set
(likely second render pass such as alpha / double-sided) [I - no pass semantics proven].

### 2.4 Material chunk list (type 9) and texture descriptor list (type 0xa)  [V]
Type 9 children: type=1,count=1,size=0x110 (SD, 1 texture) or 0x118 (HD, 3 textures) -> payload dwords (`FUN_100027b0`):

| dword | type | field | runtime dest (+off in 0x8c record) |
|---|---|---|---|
| 0..3 | float4 | colour block A (0.5,0.5,0.5,0 in samples) | +0x24 (acts as *specular* RGBA) |
| 4..7 | float4 | diffuse RGBA (1,1,1,1) | +0x04 |
| 8..11 | float4 | ambient RGBA (1,1,1,0) | +0x14 |
| 12 | float | specular power (50.0) -> stored as int | +0x48 |
| 13 | u32 | number of texture references `T` (1 SD, 3 HD; 0 = untextured; max 4) | |
| 14..63 | | zeros in all samples | |
| 64..63+T | u32[T] | **indices into the type-0xa descriptor list**, one per texture stage | +0x44, +0x4c, +0x50, +0x54 (unused = -1) |

HD stage semantics (checked by decoding PNG palettes of em001-hd): stage0 = diffuse (brownish, has tRNS alpha), stage1 = tangent-space **normal map**
(mean colour 127,128,252), stage2 = grey **specular/gloss** map. SD has stage0 only.

Type 0xa children: type=0,count=1,size=0x10c, payload dwords `{ u32 image_index, u32 width, u32 height, zeros[61] }`.
`image_index` = **index into the PAC texture array (entry 1)**. Width/height were 256/256 (SD) and 512/512 (HD) in every sample and match the PNGs;
the runtime only reads `image_index` (`FUN_100027b0` reads `desc+0xc`), so w/h look informational [D].
Example HD em001: 22 materials, 66 descriptors, 12 images (each distinct (diffuse,normal,spec) triple reused by several materials).

### 2.5 Per-mesh render-state block (0xf0000)  [D, semantics partly open]
`FUN_10002560` copies the 18 dwords; `FUN_108f82b0` turns them into the packed state key (`*param_1`) and a flag word:
- key bits: `1 | (s[9]&1)<<1 | (s[0xb]&0xf)<<2 | (s[0xc]&0xf)<<6 | (s[0xd]&3)<<10 | (s[0x10]&1)<<12 | (s[0x11]&3)<<13 | (s[4]&1)<<15` (s = block dwords; `[0]` is the version)
- lookup tables (ints, in DLL .data): `s[1]`->`0x118863fc` (sets bit 0x2), `s[8]`->`0x11886404` (bit 0x8000), `s[5]`->`0x1188640c` (skin/palette class 0x100..0x700), `s[2]`->`0x11886430`
  (light-mask 0x4..0x18), `s[9]`->`0x11886440` (bit 0x20000), `s[7]`->`0x11886448` (bit 0x4000), `s[3]`->`0x11886450` (0x20/0x40/0x60); `s[0xa]` 5/6 -> pass type 0x5000000/0x6000000.
- Example (em118 rigid mesh): `[0x10000,0,0,0,0,2,0,0,1,0,0,2,1,0,0,0,0,0]`. Meshes without the block (all of em003) get defaults (`FUN_108f88e0` iVar<0 branch).
The D3D meaning (blend/cull/z/alpha-test) is **not yet named** - see open questions.

---------------------------------------------------------------------------------------------------

## 3. Vertex / index data as the GPU sees it (renderer contract)

### 3.1 Vertex attribute mask ("format code")  [D]
Evidence: `FUN_10002bf0` / `FUN_10003190` / `FUN_10003790` (converters), `FUN_10007050` / `FUN_100070c0` / `FUN_10007120` (layout), `FUN_10013440` (consumer switch).

| bit | attribute | size |
|---|---|---|
| 0x0001 | position float3 | 12 |
| 0x0004 | normal float3 | 12 |
| 0x0010 | texcoord0 float2 | 8 |
| 0x0020 | colour0 D3DCOLOR | 4 |
| 0x0040 | colour1 D3DCOLOR (never produced from files) | 4 |
| 0x0080 | 4-float extra | 16 |
| 0x4000 | tangent float4 | 16 |
| 0x0100 (+0xf00 class) | skin: UBYTE4 bone indices + UBYTE4 weights (0..255 scaled from percent, fixed up to sum 255) | 8 |

Index/stream flags (first dword): `0x1000` indices present, `0x20000` triangle strips, `0x100000` strips carry a per-strip material id, `0x200000` strips carry a per-strip group id.
Combined code (`mesh[0]|mesh[3]`) values handled by the draw switch (`FUN_10013440` 0x138c..): `0x21025 / 0x121025` rigid no-uv, `0x21035 / 0x121035` rigid + uv,
`0x225135 / 0x325135` skinned (+tangent). (`0x1_ ...` = per-strip material ids differ.)

File->converted vertex (packed, before GPU repack):
- rigid, no uv (0x25): `pos f3 | nrm f3 | colour D3DCOLOR` = **28 B**
- rigid, uv (0x35): `pos | nrm | colour | uv f2` = **36 B**
- skinned (0x4135): `pos | nrm | colour | uv | tangent f4 | bone_idx u8x4 | weight u8x4` = **60 B** (tangent zero-filled when 0x120000 absent)
- colour packing: file floats (r,g,b,a in 0..255) -> `A<<24|R<<16|G<<8|B` (D3DCOLOR).
- skin packing: first 4 (bone,weight) pairs; `weight_u8 = (int)(percent*2.55) & 0xff`; residual added to the last non-zero weight so sum = 255; zero weights shift left (`FUN_10003790` lines 350-375).

D3D9 vertex declarations the DLL builds for the *shader* path (dumped from `0x11979ef0 / 0x11979f20 / 0x11979f60`, created in `FUN_100121b0`):
```
static  (stride 52): POSITION f3 @0, NORMAL f3 @12, COLOR0 D3DCOLOR @24, TEXCOORD0 f2 @28, TANGENT f4 @36
skinned (stride 72): POSITION f3 @0, BLENDINDICES D3DCOLOR(ubyte4) @12, BLENDWEIGHT f4 @16, NORMAL f3 @32, COLOR0 @44, TEXCOORD0 f2 @48, TANGENT f4 @56
plain   (stride 28): POSITION f3 @0, NORMAL f3 @12, COLOR0 @24
```
Skin weights are expanded from u8 to float4 and bytes get swizzled to BLENDINDICES on the CPU (`FUN_10007120` case 0x100). Vertex shaders are loaded from a packed
JKR resource (`FUN_1000ae90(buf,9)`, 9 variants x 4 sub-variants, `FUN_100121b0`); variant picked by `render_flags & 0xf00` class (0x38 stride in `DAT_11b8c708`).

### 3.2 Index buffer / strip merging  [D]
`FUN_100073b0` (size pass) + `FUN_10007560` (fill) merge consecutive strips that share the same (material, group) into **one** strip by inserting degenerate
joins (repeat last index + first index; one extra when the 0x8000 flag differs), and write a draw-range table `{u16 index_count, u16 start/material..., ptr}` (8 B/entry, terminated by 0xffff).
Index buffer = `D3DFMT_INDEX16` (format 0x65), `D3DUSAGE_WRITEONLY`, `D3DPOOL_MANAGED` (`FUN_10007b00`) => **a mesh must have < 65536 vertices.** Vertex buffer: WRITEONLY, MANAGED, length = V*stride.
Draw (`FUN_1001a1e0`): `SetStreamSource(0, VB, 0, stride)`, `SetIndices(IB)`, then per range `DrawIndexedPrimitive(TRIANGLESTRIP, 0, 0, V, start, count-2)`.
Per-range material slot ushort selects which of the up-to-32 bound material blocks is active (`FUN_1000c390(0x3a+i, material, state)`).

### 3.3 Draw call chain (for the engine contract)  [D]
`10b86ce0` actor -> `10b81e30 render_character_model_parts` -> (per mesh) `10bbe150` animation/bone transform -> `10013440` (78 callers) selects shader/state from
`render_flags` (`mesh+8` if bit 4 of `mesh+4`, else default `DAT_11b804a0`): `flags & 0xff000000` pass type (0, 0x1000000, 0x2000000, 0x5000000, 0x6000000, 0x8000000),
`& 0xf00` bone-palette class (-> shader index `*0x38`), `& 0x1c` light flags, `& 0x8000`, `& 0x4000`, then `1001a1e0 render_model_meshes` (mode by `mesh[0] & 0x300000`:
0x100000 per-range with material table, 0x200000 skinned with palette constants, 0x300000 skinned+group id, else rigid) or `1001bc70 process_render_packet`.
Bone palette is uploaded with `SetVertexShaderConstantF(start=0x2a, 4 regs)` per mesh (+ `0x26`, `0x2e`, `0xc3`, `5` constants for view/proj and misc) [D].

---------------------------------------------------------------------------------------------------

## 4. FSKL skeleton file  [V for layout, I for transform order]
Root `type=0xc0000000 (bit31 set) count=B+1 size=file`. Children:
- 1 x `type=0 count=1 size=0x10`: payload `u32 root_bone_id[count]` (value 0 in samples; "sets" for multiple roots) - `FUN_100022a0`.
- B x `type=0x40000001 count=1 size=0x10c`, **bone chunk**, payload 64 dwords (`FUN_100022a0`, `FUN_100021c0`):

| dword | field | conf |
|---|---|---|
| 0 | bone id (== index in file) | V |
| 1 | parent id (-1 root) - not read by the loader (it walks child/sibling) | V |
| 2 | first child id (-1) | V |
| 3 | next sibling id (-1) | V |
| 4..7 | float4 (1,1,1,1) - scale | I |
| 8..11 | float4 quaternion xyzw (0,0,0,1 = identity) | I |
| 12..15 | float4 translation xyz, w=1 (e.g. 14.04,-10.5,36.5) | V (plausible magnitudes) |
| 16 | i32 (-1 mostly) - IK/aux link or mirror bone | I |
| 17 | flag (1 on one bone in em003) | I |
| 18..63 | zero | |

Runtime: each bone becomes a 0x1c0-byte record in a pool of 20480 (`DAT_1ed528cc` stride 0x1c0, allocator `FUN_108f7f40`, bitmap `DAT_1dbf76b8`),
initialised by `FUN_10009640`/`FUN_10009dd0` (matrices at identity); tree traversal `FUN_100095d0`. Skinned meshes reference bones by id (weights) or through the 0x100000 palette.
Size seen: 26 bones (em003) ... see section 8 for max.

---------------------------------------------------------------------------------------------------

## 5. Textures

### 5.1 Storage and decoding  [V]
- PAC entries 1 and 4 are nested PACs of **PNG files** (every one of 2286 SD + 5301 HD images parsed: 100 % PNG, mostly 8-bit palette (colour type 3, some type 2/6), a few 1/2/4-bit palettes).
- Decoding is **`D3DXCreateTextureFromFileInMemoryEx`** (`FUN_10011a70`, queued to the render thread by `FUN_1158ffd0`):
  `Width=Height=` the PNG IHDR size (read by `FUN_100119f0`; DDS header used if magic is `DDS `), `MipLevels=1`, `Usage=0`, `Format=D3DFMT_UNKNOWN`, `Pool=MANAGED`,
  `Filter=MipFilter=D3DX_FILTER_NONE`, no colour key. => **no mip chain, no resize, any size the device accepts; PNG or DDS both work** (D3DX picks the format; palette PNG -> A8R8G8B8).
- After creation the code reads `GetLevelDesc(0)` and `GetSurfaceLevel(0)`, stores width/height and a 0x48-byte surface-desc copy in the global texture table.

### 5.2 Slot allocation  [D]
- Global texture table `DAT_11aa7d80`, stride 0xd8, **4096 entries** (`FUN_100113f0` scans to 0x11b7fd80), id 0 reserved. All game textures share it.
- Per-model texture-id table `DAT_1ecda320` (16-bit entries addressed `base + index`): monster slot `n` gets base `n*0x48 + 0x5ed` for entry 1 images (`FUN_108fba70` call at 0x108fbd48)
  and `n*0x48 + 0x631` for entry 4 images. **Capacity before spilling into the next monster slot: 0x44 = 68 images (entry 1) and 4 images (entry 4)**; `FUN_108df7d0` has no bound check.
  The pac entry-1 image count in official data: SD max 20, **HD max 60** (em142_e-hd, em099_e-hd).
- `material -> descriptor -> image_index -> texture id = table[base + image_index]` (`FUN_108f88e0` lines 71-89 patch +0x44/+0x4c/+0x50/+0x54).

### 5.3 SD vs HD texture contract (em001, representative of all)  [V]
| | SD `em001.pac` | HD `em001-hd.pac` |
|---|---|---|
| entry1 images | 4 x PNG 256x256 | 12 x PNG 512x512 (3 per SD image: diffuse, normal, gloss) |
| entry4 images | 3 x 128x128 | 3 x 128x128 (identical) |
| material type-9 | T=1, 0x110 B | T=3, 0x118 B |
| type-0xa descriptors | 22 (w/h 256) | 66 (w/h 512) |
| vertex data | 1477-vertex mesh0, no tangents | 3656-vertex mesh0, + 0x120000 tangents |
| model size | 326,256 B | 854,044 B |
| extra | - | entry 6 (2,297 B) material parameter table |
Across all 278 pairs: model size HD/SD = 0.63..6.03 (median 1.85); images per entry = exactly 3x; HD image sizes: 512 (4264), 1024 (342), 256 (166+), 2048x1024 (6),
non-square/odd like 512x510 / 512x511 exist (12+3) so **NPOT is tolerated**. Largest official image 2048x1024.
**HD meshes are re-exported (different vertex/material numbering), not just retextured** - SD mesh data cannot be mixed with HD textures or vice versa.

---------------------------------------------------------------------------------------------------

## 6. Runtime structures (what the loader builds)  -  needed to understand limits, NOT to be copied

### 6.1 Model descriptor (0x80 bytes, array `DAT_1ed528d0`, allocator `FUN_108f80a0`, bitmap `DAT_1dbfeeb8`, **max 0x500 = 1280**)  [D]
Built by `FUN_108f88e0`, skeleton part by `FUN_108f8660`.
| off | size | field |
|---|---|---|
| 0x00 | u16 | valid (=1) |
| 0x04 | ptr | fmod blob in memory (decompressed arena) |
| 0x08 | u16 | texture count of the loaded array |
| 0x0a | u16 | texture-id base (`param_6`, see 5.2) |
| 0x0c | u16 | material count N (type-9 count) |
| 0x0e | u16 | index of first material in material pool |
| 0x10 | ptr | material records (`pool[0x2800] x 0x8c`, base `DAT_1ed528c8`, indexed `*0x90`) |
| 0x20 | u16 | bone count |
| 0x22 | u16 | index of first bone in bone pool |
| 0x24 / 0x28 | ptr | bone instance array (0x1c0 each) / second copy (if mode 2) |
| 0x2c | u16 | **mesh count M** (type-2 count) |
| 0x2e | u16 | index of first mesh record in mesh pool |
| 0x30 | ptr | mesh records (`pool[0xf00] x 0x8c`, base `DAT_1ed528c4`) |
| 0x34 | u32 | number of skeleton root sets |
| 0x44.. / 0x54.. | ptr[] | per-set bone-instance array pointers (primary / alt copy) |
| 0x74 | u8 | flags (`param_3` of `FUN_108f8660`) |
So Codex's hints map to: `+0x2c` = mesh count (not generic "parts"), `+0x10` = **material** array, `+0x30` = **mesh** array, `+0x44/+0x48` = skeleton instance arrays.

### 6.2 Material record (0x8c bytes)
`+0x04 diffuse f4, +0x14 ambient f4, +0x24 specular f4, +0x34 emissive f4 (0), +0x44 tex0, +0x48 power(int), +0x4c tex1, +0x50 tex2, +0x54 tex3`
(tex = global texture id after patching, -1 none), `+0x58..+0x70` and `+0x7c..+0x88` extra shader parameters (defaults = 1.0 / 0, overridden by entry 6).
`+0x10` (diffuse alpha) is modulated at draw time for fades (`FUN_10b81e30`).  [D]

### 6.3 Mesh record (0x8c bytes)  [D]
`+0 mesh-object id (index into registry DAT_11aa3dd8, < 0xb40 = 2880 globally)`, `+4 material count n (<=32)`, `+8.. u32 material index[n]` (copy of 0x50000),
render-state words after. Palette table for skinning: `DAT_1ed532a0 + slot*0x2000`, **0x80 bytes per mesh = u16 count + up to 63 bone ids** (copied from the 0x100000 chunk by `FUN_108f8230`),
64 meshes per slot (official max meshes per model = 62, em113).
Mesh object (`FUN_10007b60`, malloc'ed): `+0 flags(format code) +4 param +8 render flags +0xc size +0x10 primitive type(1/4/5/6) +0x14 table offset
+0x18 range count +0x1c VB +0x20 IB +0x24 vertex-attr mask +0x28 vertex count +0x2c stride +0x30 index count + bounding sphere per range (`FUN_10007720`: centre f3, radius, dominant bone)` followed by range table, material copies.

### 6.4 HD material parameter table (pac entry 6)  [D]
`FUN_108fcd70`: optional 1-byte marker (value >= 0x20, e.g. 0x20) then 16-byte header (byte0 = mesh count M, rest 0xCC pad), then per mesh a 16-byte record
(byte0 = material count) followed by `count x 100-byte` blocks (old format: 0x60 B with a 3-dword shuffle). `FUN_108fba70` copies block dwords into the material record:
`block[0..3]->rec+0x04, [4..7]->+0x24, [8..11]->+0x58, [12]->+0x7c, [13..15]->+0x80.., [16..18]->+0x68..` (see decomp 108fba70 lines 285-307).
The loader aborts with a **MessageBox "Error"** if per-mesh material counts differ from the fmod (lines 247-256).  Semantics of individual floats open.

---------------------------------------------------------------------------------------------------

## 7. Memory arena and loader limits (everything the loader enforces)  [D]  <- read this for the HD-injection crash

All of this is a single `memset(0xbd16400)` static arena (`FUN_108e33a0`, VA 0x11e86340..0x1d19c740):

| symbol | VA | size | holds |
|---|---|---|---|
| `DAT_1ed528c4` | 0x11fc6340 | 0x83400 (3840 x 0x8c) | mesh records |
| `DAT_1ed528c8` | 0x12049740 | 0x168000 (10240 x 0x90) | material records |
| `DAT_1ed528cc` | 0x121b1740 | 0x8c0000 (20480 x 0x1c0) | bone instances |
| `DAT_1ed528d0` | 0x12a71740 | 0x28000 (1280 x 0x80) | model descriptors |
| **`DAT_1ed528d4`** | 0x12b04740 | **0x900000 (9 MiB)** | decompressed fmod for non-monster loaders: fmod at +0, fskl at +0x800000 |
| `DAT_1ed528b8` | 0x13404740 | 0x9000000 (144 MiB) | raw file read buffer #1 (big pacs) |
| **`DAT_1ed528bc`** | 0x1c404740 | **0xE00000 (14 MiB)** | monster path model arena: fmod decompressed at +0, **fskl at +0x800000** (`FUN_108fba70` 0x108fbc8f: `+0x800000`) |
| `DAT_1ed52984` | heap | 0xC000000 (192 MiB, `malloc`) | alternative raw pac buffer (used if non-null) |
The monster loader reads the whole pac into ECX buffer (= `DAT_1ed52984` if allocated else `DAT_1ed528b8`) and decompresses model/skeleton into `DAT_1ed528bc`.

Hard limits (violations are **not checked** unless stated - they corrupt neighbours):
1. **fmod decompressed size < 8 MiB (0x800000)**: the skeleton is decompressed to +0x800000 *after* the model and would overwrite its tail. Official HD maximum is 7,618,988 B (`em113_b-hd`) = 90.8 % of the budget; SD max 4,358,036.
2. fskl decompressed < 6 MiB (14 MiB arena minus the 8 MiB offset) on the monster path; official max 17,184 B (64 bones).
3. Raw pac file must fit the read buffer: 144 MiB static (192 MiB heap). Largest official HD pac 61.3 MB.
4. Images per entry-1 array <= 68, entry-4 array <= 4 per monster slot (texture id table spill). Official HD max 60.
5. Texture table: 4096 live textures globally; every image costs 1 slot (+ w*h*4 bytes of managed memory: a 1024x1024 palette PNG becomes 4 MiB).
6. Meshes per model <= 64 (palette table slot) - official max 62; <= 3840 mesh records globally; <= 2880 mesh objects globally (`FUN_10007aa0`).
7. Materials: pool 10240 global; per mesh <= 32 bound materials (`FUN_1000c390` slots 0x3a..0x59, official max 31); official max 138 per model.
8. Vertices per mesh < 65536 (INDEX16). Official max SD 10,117 / HD 16,544 per mesh. Bones per mesh palette <= 63 (official max 32, probably the shader constant budget); bone pool 20480; official skeleton max 64 bones.
9. Model descriptors: 1280 live (bitmap scan `FUN_108f80a0`).
10. Entry-6 material counts must equal the fmod's per-mesh counts (error MessageBox otherwise).
11. ECD files with key index >= 4 must keep their (upper-case) file name or the loader rejects them silently (returns failure from `FUN_108e27d0`); plain or key<4 files have no check.
12. `FUN_1158f240` does not check output buffer size at all: the JKR header's decompressed-size field is trusted.

Previous crash hypothesis ("HD textures packed into model files -> crash when the monster area loads"): the model arena (items 1-2) is the first thing to overflow if geometry
grew; the pac raw buffer (item 3) and texture-slot spill (item 4) are the next. Textures themselves are *not* in the 8 MiB arena (they are decoded from the pac buffer by D3DX), so
adding images only hits items 3-5. Re-test plan in section 10.

---------------------------------------------------------------------------------------------------

## 8. Official envelope (measured over every monster pac)  [V]
|  | SD (303 files) | HD (278 files) |
|---|---|---|
| max decompressed fmod | 4,358,036 (em113_b) | 7,618,988 (em113_b-hd) |
| max fskl | 17,184 (em085) | 17,184 |
| max meshes / model | 62 (em113) | 62 |
| max verts / mesh | 10,117 (em170) | 16,544 (em170-hd) |
| max materials / model | 138 (em123) | 138 |
| max materials / mesh (0x50000 count) | 31 (em105) - limit 32 | 31 (em105-hd) |
| max palette bones / mesh (0x100000 count) | 32 (em077) | 32 (em077-hd) |
| max bones / skeleton | 64 (em085) | 64 |
| max strips / mesh | 2955 (em170) | 4992 (em161-hd) |
| max descriptors | 138 | 414 (em123-hd) |
| max images in entry 1 | 20 | 60 |
| largest pac file | 14.5 MB (em093) | 61.3 MB (em149-hd) |
| pac entry count | 6 (276) / 5 (27) | 7 (273) / 6 (5) |
| encryption | ECD in ~85 % | ECD in 277/278 |
Chunk types present: SD 0x5,0x50000,0x60000,0x70000,0x80000,0xa0000,0xb0000 (all), 0xc0000 (302/303), 0xf0000 (200), 0x100000 (246), 0xe0000 (26); HD adds 0x120000 (268) and drops 0xe0000 (2).

---------------------------------------------------------------------------------------------------

## 9. Other things touched (pointers only)
1. Non-monster models (stages, weapons, armour, effects) use the same fmod/PNG scheme through `FUN_108f88e0` called from 54 sites (e.g. `103d4350`, `1035c710` with `DAT_1ed528d4` arena).
2. Fixed-function/`1001bc70` path (`DAT_1e73d3c0+0x204`) is an alternative renderer used for certain passes; not decoded.
3. `FUN_1000c390` implements the packed render-flag word editor (fields 0,1,2,0x12 and slots 0x1a.. light constants, 0x3a.. materials, 0x5a.. misc).
4. Animation bank (pac entry 2) header: `u32 {100, offset}` pairs (`64 00 00 00 38 00 00 00 64 00 00 00 c8 01 00 00 ...`), decoded by `FUN_108fd380`/`FUN_108fd1d0` (stride 0x960 per slot, `DAT_1eda2080`). Not covered.

---------------------------------------------------------------------------------------------------

## 10. Open questions / next experiments
1. Name the D3D states behind the 0xf0000 block and the group 0x30000-vs-0x40000 split (needs a render-state trace or reading `FUN_10018d30`/`FUN_10014700`).
2. Unknown chunks 0xe0000 (n x 0xffffffff list) and the 0x20000 header word.
3. Meaning of fskl dwords 4-7, 16, 17; transform composition order (scale/quat/pos). Read `FUN_10009dd0` / `FUN_100095d0`.
4. Whether `desc.width/height` in type 0xa are read anywhere else (grep for reads at desc+0x10/+0x14 of the 0x10c blocks).
5. Strip flag bit31 never observed set in samples; confirm with a census over all 581 files (cheap with `mhfmodel.parse_fmod`).
6. Which loader consumes pac entry 3/4 second model and whether it shares the 8 MiB arena (`FUN_108f8140` path in `FUN_108fba70` lines 203-221).
7. Runtime proof of the arena overflow: patch an HD pac with a >8 MiB raw (JKR mode 0) model and watch `DAT_1ed528bc+0x800000`, or build a 70-image entry 1 pac.
8. Rewrite hint: no mip chain is authored; a new engine should generate mips for the 3-texture HD sets, and read PNG tRNS for alpha.

## 11. Verification log
- `python -I tools\mhfmodel.py dat\emmodel\em003.pac`: 2 meshes (805/784 verts, 774/760 triangles), 9 materials, 9 descriptors, 26 bones, 2 PNGs; all strip indices < V; mesh material lists [0,1,2,5,7],[3,4,6,8] partition the 9 materials;
  weights sum to 100 for 805/805 vertices; normals unit for 805/805; uv in [0.0068, 0.9974]; 4 sample models confirm strip winding.
- ECD/JKR/PAC: 581/581 monster pacs decrypt + decompress; JKR output length equals header size every time.
- HD material PNG palettes inspected to type stages (section 2.4).
- Tools: `tools\mhfpac.py` (ecd_decrypt, jkr_decompress, pac_entries), `tools\mhfmodel.py` (parse_fmod, parse_fskl, triangles, OBJ/PNG export).

## 12. Evidence index
`1158f510 1158f460 1158f350` ECD | `1158f240 1158efe0 1158eec0 1158ef30 1158ef50` JKR | `108df4b0 108df7d0 108df600 108df890` pac helpers | `108fba70` monster loader |
`108fc420` alt loader | `108f88e0` fmod->runtime | `108f8660 108f85a0 100022a0 100021c0 10009640` skeleton | `10002680 10002740 100028f0 10002630 100026f0 10002960 100029a0 10002a10 10002af0` chunk access |
`10002bf0 10003190 10003790` mesh converters | `100027b0` material | `10002560 108f82b0 1000c390` render-state | `10007b60 10007b00 10007050 100070c0 10007120 100073b0 10007560 10007720 10007aa0 100082f0` mesh object |
`100121b0` vertex decls/shaders | `10011a70 10011af0 100113f0 100119f0` textures | `108f80a0 108f7e90 108f7ff0 108f85a0 108e33a0` pools | `108fcd70` entry 6 | `108f8230 100024f0` palette |
`10013440 1001a1e0 1001bc70 10b81e30 10bbe150` draw chain.
