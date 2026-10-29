# MHF-Z animation / motion data: engine-neutral spec

Status: first pass. Written from the decompile (`decomp\*.c`) and from decoding real files in the install
(`dat\motion\*.mot`, `dat\emmodel\em003.pac`, `dat\emmodel\em005.pac`). Everything is described in
reimplementation terms. Confidence tags: **[H]** high (read directly from code or verified by parsing real
files with assertions), **[M]** medium (strong inference), **[L]** low (guess, needs a probe).

Helper tools written for this pass (they read the user's own game files, no game data is stored in the repo):
- `tools\jkr.py` : JKR/JPK decompressor, types 0, 3, 4. Verified on `.mot`, `.pac`.
- `tools\pacwalk.py` : recursive walker for `.pac` / `.mot` containers and JKR wrappers.

---------------------------------------------------------------------------------------------------

## 0. Headline findings (read this first)

1. **`10bbe150` is NOT a skeletal-pose evaluator.** It is a per-material-slot / per-part *effect* animator:
   UV scroll, tint colour fade, alpha fade, and a per-part scale/offset kinematic track. It writes
   a 0x8c-byte "slot record" (colour, alpha, UV matrix) into the renderer's per-pass constant table. Section 5.
   The earlier NOTES.md hypothesis ("skeletal/part transform evaluator") should be corrected.
2. **Real skeletal animation data is fully understood on the file side** (container, skeleton, tracks, key
   format, channel layout): sections 1-4. What is NOT yet located is the *runtime sampler* that turns keys +
   frame into bone matrices (scales/units and blend rules are therefore partly inferred, section 4.4/6).
3. **Anim time is advanced at DRAW time for the effect layer** (counter incremented inside the draw callback,
   section 5.4). Skeleton time advance not yet confirmed, but the entity draw callback is invoked from the
   render passes, so the 60 fps plan must make these counters tick-driven. Section 7.
4. **HD asset replacement is feasible without touching animation**: motions are independent files keyed by
   *bone index*; they only require the replacement skeleton to keep the same bone count/order/hierarchy.
   Textures inside `.pac` are plain PNG. Section 8.

---------------------------------------------------------------------------------------------------

## 1. Containers

### 1.1 JKR compression wrapper [H]
Magic `4A 4B 52 1A` ("JKR\x1a"). Header (little endian):

| off | size | field |
|---|---|---|
| 0 | 4 | magic |
| 4 | u16 | version (0x108 seen) |
| 6 | u16 | type: 0 = stored, 3 = LZ, 4 = Huffman+LZ (2 = other/unused here) |
| 8 | u32 | data offset (0x10 seen) |
| 12 | u32 | decompressed size |

Evidence: reader init `1158f240` (type switch, huffman setup), LZ loop `1158efe0`, huffman byte reader `1158eec0`,
copy helper `1158ef50`. Wrapper is recognised at load time in `108fd1d0` and `1158f310`.

LZ bit protocol (identical for type 3 and 4; only the "get byte" source differs):
- Flag bits are consumed MSB first from a flag byte fetched via `getbyte()` when the bit counter runs out.
- `bit=0`: literal = `getbyte()`.
- `bit=1`, next bit `=0`: short match. `len = (2 bits) + 3`, `dist = getbyte() + 1`.
- `bit=1`, next bit `=1`: long match. `hi = getbyte(); lo = getbyte(); dist = ((hi & 0x1f) << 8 | lo) + 1`.
  - if `hi >> 5 != 0`: `len = (hi >> 5) + 2`.
  - else read a bit: `0` -> `len = (4 bits) + 10`; `1` -> `b = getbyte()`: if `b == 0xff` then a RAW block of
    `(dist - 1) + 0x1b` literal bytes follows (each via `getbyte()`); else `len = b + 0x1a`.
- Type 3: `getbyte()` reads the next source byte. Type 4: flag/literal/length/distance bytes ALL come from the
  Huffman decoder, which shares the same source pointer with the flag stream.

Type 4 Huffman: at `data_offset` a u16 `tableLen` (root node id, 0x1fe seen). Nodes `0x100..tableLen`, children stored
as u16 pairs at `data_offset+2 + (node-0x100)*4`; value `< 0x100` is a leaf byte. Bits MSB first. The bit buffer
starts as the byte immediately before the LZ source pointer; the LZ source starts at
`data_offset + tableLen*4 - 0x3f9`. When 8 bits are used the next byte is pulled from the shared source pointer.
Confidence: [H] (decoder reproduced the game's output for all tested blobs and sizes match the header).

HD model packs (`dat\emmodel-hd\*.pac`) start with `65 63 64 1A` ("ecd\x1a"): an encrypted wrapper, NOT decoded here
(see open questions).

### 1.2 Generic "offset/size archive" [H]
`u32 count; { u32 offset; u32 size } * count` then payloads (offset from archive start). `size==0` = empty slot.
Entries may themselves be JKR wrapped or nested archives. (ReFrontier's "simple archive".)

### 1.3 Monster pack `emmodel\emNNN.pac` (verified on em003, em005) [H for layout, M for entry meaning]
```
pac            archive(5)
 [0]           archive(2)                      "model set"
    [0]        JKR(type4) -> model/mesh file   (em003: 122,076 bytes decoded; format NOT yet reversed)
    [1]        JKR(type3) -> SKELETON          (em003: 6,996 bytes)  section 3
 [1]           archive(1..N)  each entry = raw PNG   (textures)
 [2]           JKR(type4) -> MOTION ARCHIVE    (em003: 241,112 bytes, 62 clips)  section 2
 [3],[4]       empty (size 0)
```
Variants `emNNN_b.pac`, `_c`, `_e` are alternate model/texture sets of the same monster (same layout) [M].

### 1.4 Motion files `dat\motion\*.mot` [H]
A `.mot` is a JKR type-3 wrapper around the same MOTION ARCHIVE as pac entry [2]. `evcamNNNN.bin` (cutscene
camera) is a different format and is not covered. `npc*.mot`, `lbcom_on.mot`, `ac_com.mot` use the same archive
header; `ac_com.mot` has 11 groups of small (5-dword) tables, i.e. a different payload, not skeletal.
Loaders: `108fd1d0` (generic), `10881730` (builds `motion\evmot%04d.mot`), `10829ee0` (builds `motion\evcam%04d.bin`),
`1032aab0` (weapon-class motion names `motion\w12w_typeA..E.mot`).

---------------------------------------------------------------------------------------------------

## 2. Motion archive and clip records [H]

### 2.1 Archive header
```
G = (offset of first table) / 8              number of groups
for g in 0..G-1:  { u32 count_g; u32 table_offset_g }          at file offset g*8
table_g = u32[count_g]  (count_g is normally 100)  absolute offset of a clip record, 0xFFFFFFFF = absent
motion_id = g*100 + index
```
Evidence: `108fd1d0` loop (`local_3c / 100`, `% 100`, `-1` => null). em003: G=5 (groups 0..3 populated,
group 4 empty), 62 clips; npc33: G=3. Groups are logical banks (action sets); ids are what gameplay scripts
reference. Each present record is converted by `100018b0` into a runtime clip object.

### 2.2 Clip record
```
+0x00 u32 tag = 0x80000002           (chunk tag, bit31 set)
+0x04 u32 trackCount                  (em003: 23, npc33: 9). Track i drives bone i.
+0x08 u32 byteSize                    of the whole record, tracks included
+0x0c u32 loopFlag                    nonzero = loops (runtime sets flag bit 0x8000)
+0x10 f32 loopFrame                   frame to restart at when looping
+0x14 tracks[trackCount], each `trackSize` bytes
```
Runtime clip object built by `100018b0` (offsets from the allocated block):
`+0 u16 flags(bit15=loop)`, `+2 u16 trackCount`, `+4 f32 minFrame`, `+8 f32 maxFrame (clip length)`,
`+0xc f32 loopFrame`, `+0x10 ptr trackTable`. Length = max over channels of the last key's frame number [H, code
`100018b0`/`100017f0`]. Observed lengths em003: 26..362 frames; loops have loopFrame 0..64.

### 2.3 Track (per bone) and channel chunks
```
track:   u32 tag = 0x80000000 | channelMask      (0x1f8 = 6 channels, 0x38 = 3 channels, 0 = static bone)
         u32 channelCount
         u32 byteSize                            (advance by this to the next track)
         channels[channelCount]
channel: u32 tag = 0x80000000 | (keyType << 16) | channelBit
         u32 keyCount
         u32 byteSize                            (12-byte header + keys)
         keys[keyCount]
```
Both walkers assert `sum(sizes) == parent size` on all 62 em003 clips [H].

Channel bit -> slot index (code `10001ee0`): `0x01->0, 0x02->1, 0x04->2, 0x08->3, 0x10->4, 0x20->5, 0x40->6,
0x80->7, 0x100->8`. So there are 9 channel slots per bone:

| slot | mask | meaning | evidence |
|---|---|---|---|
| 0,1,2 | 0x01,0x02,0x04 | not seen in any shipped clip we parsed | [L] scale XYZ (guess) |
| 3,4,5 | 0x08,0x10,0x20 | **rotation** X,Y,Z (Euler, s16 angle) | present on every animated bone [M] |
| 6,7,8 | 0x40,0x80,0x100 | **translation** X,Y,Z | only on one root-like bone (em003: bone 2) [M] |

Track layout seen: em003 tracks 0 and 1 are empty (static), track 2 has all 6 channels (root: rotation +
translation), tracks 3..22 have rotation only. Bones 23..25 have no track (static in every clip) [H].
Key type constant `0x80120008` etc: `0x8012` = flag+type 0x12.

### 2.4 Key formats (type = bits 16..23 of channel tag) [H for sizes/offsets, M for semantics]

| type | bytes/key | layout (little endian) | notes |
|---|---|---|---|
| 0x11 | 4 | `s16 value; u16 frame` | no tangents (converter `10001d20`) |
| 0x12 | 8 | `s16 value; u16 frame; s16 tanIn; s16 tanOut` | **the only type present in the shipped clips we scanned (2,222/2,222 channels)**; converter `10001da0` |
| 0x13 | 12 | 3 dwords, frame at +6 (`100017f0` reads `+6`) | rare/unused here |
| 0x21 | 8 | float variant, value float at +4, frame at +0..3 | converter `10001b80` |
| 0x22 | 16 | float variant | `10001bf0` |
| 0x23 | 20 | float variant | `10001c80` |

Frame numbers are integers (u16) in clip frame units, strictly ascending, first key usually frame 0, last key = clip
length. Tangent values are small (0..~250) and usually 0 -> interpolation is effectively **Hermite with optional
tangents, tangents mostly zero i.e. smooth/ease or linear** [L: exact formula and tangent scaling unverified].
Hermite vs linear must be settled by a probe or by locating the sampler (open question Q1).

### 2.5 Value units [L, needs probe]
- Rotation channels are 16-bit signed angles. Observed range on em003: about -16,765 .. 7,845 (rotation) so units
  cannot be degrees (would exceed human range for tail bones). Best hypothesis: `angle_rad = value * 2*pi / 65536`
  (full signed range = +-180 degrees), applied as Euler XYZ in some order (order unknown, Q2).
- Translation (root bone 2): Y channel ~1,411 at rest. Skeleton rest offsets are tens of units (hip-to-leg ~44),
  so hypothesis `translation = value / 32` (=44.1) [L].
- Time: integer frames; gameplay logic is 30 Hz so 1 frame = 1/30 s is the working assumption [M, see section 7].

---------------------------------------------------------------------------------------------------

## 3. Skeleton (pac entry [0]/[1], JKR type 3) [H layout, M semantics]

```
+0x00 u32 tag = 0xC0000000
+0x04 u32 chunkCount (27 for em003; = bones + 1)
+0x08 u32 totalSize  (6996)
+0x0c u32 0
+0x10 u32 1
+0x14 u32 0x10
+0x18 u32 0
then bones, stride 0x10c (268), first bone at +0x1c, count = chunkCount-1 (26)
```
Bone record (offsets from record start):

| off | type | field | confidence |
|---|---|---|---|
| 0x00 | u32 | tag 0x40000001 | H |
| 0x04 | u32 | version = 1 | H |
| 0x08 | u32 | size = 0x10c | H |
| 0x0c | s32 | own index (0..N-1) | H |
| 0x10 | s32 | parent index (-1 root) | H |
| 0x14 | s32 | first child index (-1 none) | H |
| 0x18 | s32 | next sibling index (-1 none) | H |
| 0x1c | f32[4] | scale xyz + 1.0 (always 1,1,1,1 in em003) | M |
| 0x2c | f32[4] | bind rotation as quaternion (x,y,z,w); identity (0,0,0,1) in em003 | M |
| 0x3c | f32[3] | bind local translation (bone length offset, e.g. 14.06,-10.56,37.02) | H |
| 0x48 | f32 | 1.0 | L |
| 0x4c | s32 | -1 (attachment/mesh link?) | L |
| 0x50.. | zero (bones 23-25 carry a nonzero word) | reserved/extra (IK limits? attach data) | L |

The hierarchy is a first-child/next-sibling tree AND has explicit parent; parents always precede children
(verified em003: 0->1->2->3..., 3 has children 4,8,12; 2 has 14,18,22). Bind pose is all-identity rotation with
translation offsets, i.e. a T/rest pose where the *animation supplies the rotation*. No inverse-bind matrices are
stored (they are derivable by accumulating translations) [M]. Bone names are not stored.

Pose rule (standard, consistent with the data) [M]: `local(i) = T(bindTranslation_i [+ anim translation if
channel]) * R(anim euler_i) ; world(i) = world(parent) * local(i)`. Rotation replaces the identity bind rotation.

---------------------------------------------------------------------------------------------------

## 4. Pose evaluation (what is known)

### 4.1 Where the evaluator is NOT
- `10bbe150` and callees (`10bbc890`, `10bbbf80`, `10bba160`, `10bbe0a0`, `10bba090`, `10bbcbd0`, `10bbbe40`,
  `10bbc1f0`, `10bbc330`) contain no key interpolation, no quaternion/Euler pose code, no bone traversal. See section 5.
- The decomp contains zero `D3DXQuaternion*`, `D3DXMatrixRotationQuaternion`, `D3DXMatrixDecompose`, `D3DXVec3Lerp`
  calls; the engine builds rotations with `D3DXMatrixRotationX/Y/Z` (63/50/9 call-site files) and multiplies with
  `D3DXMatrixMultiply` (336 files). So blending is almost certainly *per-channel scalar* (Euler s16 interpolation),
  not quaternion slerp [M].

### 4.2 Runtime clip object and loading
`100018b0` copies each track's channels into runtime arrays (converters `10001d20/da0/e40/b80/bf0/c80`), builds a
per-track slot table (8-byte entries: `u8 keyType; u8 slot; u16 count; u32 relOffset`, slot from section 2.3) and
computes min/max frame. Callers that load clip banks: `108fd1d0`, `107fe6c0`, `105f7bd0`, `105e6100`, `105f7ee0`,
`105f8220`, `1060e160`, `107163c0`, `113da8c0`. The sampler consuming `trackTable` is still to be found (Q1).

### 4.3 Entity draw path (context for where the pose is consumed) [H]
Each entity has a draw callback pointer at `*(entity+0x6b8)+0x14` set by state code
(`10b7b860` player, `10b7ba30`/`10b7bbf0` monster/NPC; assignments in `101ca8e0`, `108103b0`, `1065bec0`, `106a7900` ...).
Callbacks call `10b86ce0` / `10b88470`, which call `10b81e30` (render_character_model_parts).
`10b81e30` loops the model's `partCount` (`model+0x2c`), selects per-part matrices (copies 64-byte matrix from
`entity+0xf4 or +0xf8 -> +0x40`, applies `D3DXVec3TransformNormal`, scale `D3DXMatrixScaling` via `1000cf90`, multiply via
`10008970`) and per part calls `10bbe150` for the material animation, then `10013440` (mesh draw).

### 4.4 Blending
No two-clip crossfade code has been located yet. In `10bbe150` the only blend is a scalar weight `param_7` that
gates/scales effects (section 5). Skeletal clip blending/transition rules: **unknown (Q3)**.

---------------------------------------------------------------------------------------------------

## 5. `10bbe150` update_group_animation_and_transforms = material / part effect animator

Signature (fastcall + stack, decompiler argument order corrected from the call site in `10b81e30`):
`(groupTable = model+0x30, modelDesc = model, slotRecords = model+0x10, groupIndex, entity, modelClass(short),
weight(float), entityByte(+0x401), passKind(char 0/1/2/3), int* outFlag)`.

### 5.1 Data structures [H unless noted]
- `modelDesc` (= `entity+0x680`): `+0x10` array of effect "slot records" (0x8c bytes each), `+0x2c` part count (s16),
  `+0x30` array of group records (0x8c bytes), `+0x44`/`+0x48` primary/alt part resource arrays (stride 0x1c0, a
  part's `+0x70..0x78` holds its xyz offset/scale).
- Group record (0x8c): `+0` s32 id (-1 = unused), `+4` s32 childCount, `+8..` s32 child slot indices (`0x23` dwords per group).
- Slot record (0x8c = 0x23 dwords) is exactly the per-pass render constant block uploaded by `1000c390(0x3a+child, rec, 0)`
  into the table at `0x11aa6af8` (`+0x4..0xc` RGB tint 0..1, `+0x10` alpha, rest includes a 4x4 UV transform).
- Effect instance (stride 0x94) fetched by `10bbe0a0(entity)`: pool chosen by `passKind`/index; base `entity->(+0xd28)`
  plus `0x9c00 / 0xa0a0 / 0xa540 / 0xa9e0 / 0xae80 / 0xb320 + i*0x94`; 8 instances per child. Fields used: `+0` ptr to
  effect definition, `+4` s16 frame counter, `+6` u16 start-delay counter, `+0x8a` active, `+0x8b` mode (0 init,1 run,2 end,3 ended),
  `+0x8c` aux, `+0x8d` state, `+0x15*4..` per-track runtime state (4 floats: value, velocity, accel, count).
- Effect definition (selected fields, `d` = float*): bytes `+0xd` group index, `+0xe` child index, `+0xf` part resource
  index, `+0x10` u16 delay frames, `d[0..2]` base xyz offset, three kinematic tracks (position xyz) at
  `d[0xf..0x13]`, `d[0x14..0x18]`, `d[0x19..0x1d]`, scale tracks `d[6..0xd]`, UV scroll params `+0x96 u16, +0x98 s16, +0x9a u16`,
  colour fade params at `+0x7c..+0x86`, alpha fade params `+0x88..+0x90`, a render-mode byte `+0xa0 (=4: per-frame random tint)`.

### 5.2 Algorithm per (group, child) [H structure, M details]
1. Early-out if no pool (`entity+0xd28==0`), weight == 0, or group id == -1.
2. Init slot record: UV matrix = translation(0), identity others (`D3DXMatrixTranslation(&m,c,c,c)`).
3. For each of up to 8 active effect instances whose def matches this group/child:
   - `10bbcbd0` (4 KB) = activation predicate by `def+0xc` mode (cases 1..0x32 test entity state: weapon/skill ids, `10b742a0`,
     `108ff7a0` timers) and drives the state byte `+0x8b/+0x8d` transitions.
   - Count/delay: if draw-enabled (`10029ab0(1)`) and first-pass (`passKind==0`) then increment start-delay (`+6`) until it reaches
     `def+0x10`, then increment frame counter (`+4`) by 1 **per call** (see 5.4).
   - Kinematic tracks (`10bbbe40`, `10bbbf80`, `10bbc1f0`): an integer-stepped value with velocity easing: velocity moves toward target by
     `target * DAT_118e45b0` per call, value += velocity, clamped between min/max, bounce (`10bbbf80` flips direction) or wrap/reset,
     counters decremented every `period` frames (`frame % period == period-1`). Output xyz offset applied to the part resource
     (`+0x70..0x78`) and a scale via `D3DXMatrixScaling(1000cf90)`.
   - UV scroll (`10bbc330`, `10bbc500`): `u = (frame % periodU)/periodU`, `v = (frame % periodV)/periodV`, written as
     `D3DXMatrixTranslation(uvMatrix, u, v, 0)`. `10bbc330` also advances its own counter (frame++, optional step, loop count -1 at wrap).
   - Colour fade (`10bbc620`): per-channel linear ramp between two bytes over `len` frames (`frame % (len+1)`), or ping-pong
     (`frame % (2*len)` folded). Result `byte/255` -> record `+4/+8/+0xc`.
   - Alpha fade (`10bbc890`): same ramp/ping-pong on a u8 alpha, then `alpha/255 * weight` -> record `+0x10`.
   - Random tint mode (`10bbde80`, def mode 4): angle from `108e4b90` (atan/random) sums -> UV offset.
   - `10bba160` gate: evaluates entity condition masks (`param & 1,2,4,8`) vs player action tables and a global timer
     `DAT_1ee24964` thresholds (0xa8c0 = 43,200) -> forces alpha 0 (effect hidden).
4. After the effect loop: pass-specific alpha rules by `entity+3` (entity subtype: 0 player, 1,5,7,9,10 monsters/NPC...) set `record+0x10`
   to the incoming weight or 0, then `1000c390(0x3a+child, rec)` uploads the record, `10b705e0/10b70760/10b811a0` are render-state helpers.
5. Final: draws the part with `10013440(0, entityHeaderU16, 3 or 1, 0, 0, ...)` if the part mesh table `DAT_11aa3dd8[id]` (0xb40 entries) exists and
   marks `mesh+4 |= 0x80`.

### 5.3 D3DX / math primitives used (engine-neutral list)
`D3DXMatrixTranslation` (UV transform, init), `D3DXMatrixScaling` (via `1000cf90`), `D3DXMatrixMultiply` (`10008970`, world * per-part),
`D3DXVec3TransformNormal` (rotating a local offset into world space, `10b81e30`), `fsin` (sinusoid pulse in the case-0 monster glow: `value =
amp * weight * sin(counter * k1 * k2) + base`), `fpatan`/trig helpers (`10004c20` builds a rotation from three angles, `10004f80` scale from
three floats). There is NO quaternion math.

### 5.4 Tick vs draw (the 30 Hz / render split) [H code, M conclusion]
- All counters (`+4` frame, `+6` delay, `+0xc` loops) are mutated INSIDE `10bbe150`, which is reached only from the entity draw callbacks
  (section 4.3) in the render block of `1080fe60` and from `10b7b5c0` passes. There is no separate tick-time animation update for this layer.
- Increment condition `10029ab0(1)==true || state==1 || *outFlag` AND `passKind==0`: i.e. once per entity draw (first pass only), skipped when
  the renderer is in the special offscreen mode (`DAT_1e73d3c0+0x10`) with the capture flag.
- Because the game's own frame-skip clears the render gate (NOTES: `119dd74c`), skipped frames do not advance these counters: effect time
  = number of *drawn* frames, locked to 30 fps in the original.
- **Recommendation for the rewrite:** make the effect counter a pure function of tick count (`frame = ticks_since_activation`, 30/s), evaluate
  the closed forms (ramps, `frame % period`, ping-pong) from the counter, and for 60 fps render interpolate by evaluating at fractional frame
  (`frame + alpha`). Only the velocity-eased kinematic tracks (5.2) are order-dependent integrators; step them on ticks and lerp between the last two states.
- Skeletal clips: sampler not found. If, as for these effects, the clip frame is advanced in the draw callback (likely, since entity draw
  callback is the only per-entity code in the render block) the same rule applies. Confirm with Q1.

---------------------------------------------------------------------------------------------------

## 6. Reimplementation plan (suggested)

1. Parse pack: `jkr_decode`, archive walker, extract skeleton + motion archive + PNGs (tools exist).
2. Pose = for each bone with a track: sample each of 6 (or 3) channels at fractional frame with Hermite using the stored tangents
   (fallback: linear if tangents are 0), convert units (2.5), build local TR, accumulate parent-first. Start with the hypothesis units,
   verify visually against a known idle clip (feet on ground, no spikes).
3. Clip playback: speed multiplier * 30 frames/s, loop at `loopFrame` if `loopFlag`, else clamp at last frame. Cross-fade: unknown, start with
   a fixed 4-6 frame linear weight blend per channel.
4. Effect layer: implement 5.2 as stateless functions of an integer counter.

---------------------------------------------------------------------------------------------------

## 7. Evidence index

| claim | address / file |
|---|---|
| JKR types and decoder | `1158f240`, `1158efe0`, `1158eec0`, `1158ef50`, `1158ef30`, `1158f310`, `108fd1d0` |
| Motion archive indexing (group*100+idx) | `108fd1d0` |
| Clip parse/convert | `100018b0`, `10001ee0`, `10001790`, `10001700`, `100017f0`, `10001d20`, `10001da0`, `10001e40`, `10001b80`, `10001bf0`, `10001c80` |
| Motion file name builders | `10829ee0` (evcam), `10881730` (evmot), `1032aab0` (w12w_type) |
| Slot/pass constant table upload | `1000c390` (0x3a..0x59 -> 0x8c-byte records at `0x11aa6af8`) |
| Effect animator | `10bbe150` + `10bbcbd0 10bbbe40 10bbbf80 10bbc1f0 10bbc330 10bbc500 10bbc620 10bbc890 10bbde80 10bba160 10bba090 10bbe0a0` |
| Entity draw chain | `10b81e30`, `10b86ce0`, `10b88470`, `10b7b860`, `10b7ba30`, `10b7bbf0`, `10013440` |
| Real files parsed | `dat\emmodel\em003.pac`, `em005.pac`, `dat\motion\npc33.mot` |

## 8. Guidance for HD model/texture replacement

- Textures in `emNNN.pac` entry [1] are PNG: swapping resolution is a pack-level change (pac entry size is just stored in the
  archive header; repack offsets). UV scroll/colour effects (section 5) are computed in UV space so they are resolution-independent.
- Animations bind to the skeleton by **bone index only** (track i -> bone i; no names, no hashes). A replacement mesh must be skinned to a
  skeleton with the same bone count, order and parent/child structure and the same bind translations (rotations in clips are absolute
  replacements of an identity bind rotation). Extra bones can be appended AFTER the original indices (they simply get no track).
- `emmodel-hd\*.pac` are the game's own HD set: ECD-wrapped. If the same skeleton chunk is present inside, the HD set proves the
  skeleton is shared across SD/HD (not yet verified).
- The mesh/model file (entry [0]/[0]) is not yet decoded, so skin weights/bone-index maps for replacement meshes are the missing piece.

## 9. Open questions (ranked)

- **Q1** Locate the sampler: code that walks `trackTable` slots (keyType u8 + slot u8 at the 8-byte entries) per bone with a float frame. Search
  for functions reading 8-byte entries with `keyType 0x12`, or break on reads of the runtime clip `+0x10`. Gives: interpolation formula, units,
  Euler order, translation scale, time advance site (tick vs draw), and cross-fade.
- **Q2** Euler rotation order / handedness and angle unit (hypothesis 65536 per turn).
- **Q3** Clip blending/transition and per-entity playback state (current clip id, frame, speed): find fields on the monster/player entity.
- **Q4** Mesh/model file format (`em003.pac` [0]/[0], chunk tree `0x80000xxx`-style tags like the skeleton): skin weights, bone map, LODs.
- **Q5** Meaning of skeleton bone fields `+0x1c` (scale vs other), `+0x48`, `+0x4c`, and tails of bones 23-25.
- **Q6** ECD (`emmodel-hd`) decryption and whether HD packs reuse the SD skeleton/motions.
- **Q7** `evcam*.bin` cutscene camera format and `ac_com.mot` payload.
- **Q8** Frame rate of clips (30 assumed).
