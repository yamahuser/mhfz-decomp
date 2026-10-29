# Particle / mesh effects (spec, 2026-10-15)

Derived from reading the client (functions named below) and checking every claim against em130 data. Engine code is
written from this file, never from the decompile. Offsets are bytes, little endian. "Time" is the effect clock, which
advances by 2 per 30 Hz game tick (so it counts 1/60 s).

## Where the data lives
- Monster pack (`emmodel[-hd]/emNNN[-hd].pac`), em130 example:
  - entry 3 = effect model pack {JKR fmod, JKR skeleton}: 77 meshes (rings, shockwaves up to r 2200, pillars, slashes,
    shards), unskinned, 8 materials.
  - entry 4 = PNG pack: the effect model's textures (4 for em130).
  - entry 5 (JKR) = effect container (below).
- `dat/effect.bin` = global effects, same idea: pack of 20 entries; entry 0 = model pack {fmod, skeleton}, entry 1 = PNG
  pack, further pairs/containers not surveyed yet.

## Effect container (monster entry 5)
- u32 n, then n x {u32 offset, u32 size} (offsets from the container start).
- Section 0 = directory: u16 version (1), u16 count, then count x {u16 type, u16 id} describing sections 1..count.
  em130: (1,0x474) (1,0x475) (1,0x476) (2,0x474).
- Type 1 section = one effect file (below), registered under `id` (the client's registry: 128 slots of 0x44 bytes,
  spawn calls look up by id then pick a timeline by sub-id: `spawn_effect_by_id` 113d61f0, `play_effect_by_id_at_pos`
  113d6250, `play_effect_by_id_attached_to_object` 113d62d0).
- Type 2 section = trigger table: u16 0, u16 1, u32 count, u16 idA, u16 idB, 4 zero bytes, then count x 0x20 records
  {12 zero bytes, u16 key (= idA, 0x47b), u16 frame, u16 a, u16 b, u16 effect id, u16 timeline sub-id, 8 zero bytes}.
  em130: 7 records at frames 194..324, a/b = 35/26 (bone ids?), effect 0x476 sub 2. Consumer not identified yet.

## Effect file (parser 113d4a70)
Header 0x1c bytes = 14 x u16: h0 version (must be >= 4), h1..h6 table counts, h7, h8, h9 flags/counts, rest 0.
Tables follow back to back in this order (absent when the count is 0):

| table | count | stride | content |
|---|---|---|---|
| T1 | h1 | 0x70 | spawn timeline records |
| T2 | h2 | 0x18 | vec3 keys |
| T3 | h3 | 0x10 | colour keys |
| T4 | h4 | 0x10 | integer keys (mesh index / child timeline lists) |
| T5 | h5 | 0x38 | particle emitter defs |
| T6 | h6 | 0x8c | model-emitter defs (alternate kind) |
| T7 | h7 | 4 + 4*h7 | u32 header then h7 dwords |
| T8 | h8 | 0x20 | ? |
| T9 | h9 != 0 | rest | ? |

em130 files: (h1..h6) = (106,76,93,30,36,52), (137,111,75,31,31,36), (60,119,59,31,33,28); each sums to its exact size.

### T1 spawn timeline record (0x70) - read by `effect_player_update_timeline` 113d3fc0
- +0x00 vec3 position, +0x0c vec3 position jitter
- +0x18 vec3 rotation (radians), +0x24 vec3 rotation jitter (2*pi = fully random), wrapped to [-pi, pi]
- +0x30 vec3 scale, +0x3c vec3 scale jitter (flag bit 1: one shared random factor for all three axes)
- +0x48 f32 yaw angle applied to the position track (em130 has pi/4)
- +0x4c s16 emitter def id (matches T5 +0x04, or T6 +0x04 when flag bit 0). EVERY def with that id spawns (em130
  emitter 0 = 6 defs = 3 ring meshes x 2 draw variants)
- +0x4e u16 trigger time; fires when it lies in (t-2, t]
- +0x50 u16 timeline sub-id: a player plays only the records whose sub-id equals the sub-id it was spawned with
- +0x52 u16 particle repeat count (min 1): the particle restarts its clock this many times
- +0x54 u32 flags: bit0 use T6 instead of T5; bit1 uniform scale jitter; bit2 random X mirror (-1); bit3 random Y mirror
- +0x58 s16 particles per trigger
- +0x5c f32 time scale for lifetime and tracks (applied when >= a small threshold; 0 = 1x; em130 uses 1.4)
A player ends after the largest trigger time of its sub-id (+2); a record with trigger time 0xffff marks a looping one.
Random numbers: 16-bit LCG x = (x*0xb0) mod 0xff53 (x=0 -> 1); jitter = ((x & 0x3ff) - 0x200)/512 * range.

### T2 vec3 key (0x18) - `sample_vec3_keyframe_curve` 113ccd90
- +0x00 f32 x, y, z; +0x0c s32 time; +0x10 u8 flags (bit0 loop: time wraps at the last key); +0x12 u8 track id.
- A track = all keys with the same track id, in file order; linear interpolation; one key = constant.

### T3 colour key (0x10) - `sample_color_keyframe_curve` 113ccaf0
- +0x00 s32 time; +0x04 u8 flags (bit0 loop); +0x06 u8 track id; +0x08 u8 R, G, B, A. Linear per channel.

### T4 integer key (0x10) - 113cc8a0 / 113cca10 / 113cc8e0 / 113cc970
- +0x00 s32 time, +0x04 u8 flags (bit0 loop), +0x06 u16 list id, +0x08 s32 value.
- As a mesh list (emitter +0x0a): value = effect-model mesh index, step function over time; if more than one key has
  time 0 the spawn picks one of them at random.
- As a child list (emitter +0x24): at the exact key time a child effect player starts with timeline sub-id = value.

### T5 particle emitter def (0x38) - `particle_emitter_create` 113cd4b0, draw 113ce4d0
- +0x00 u32 flags: 0x1 / 0x2 / 0x200 = billboard modes (camera-facing variants), 0x4 / 0xc00 render-list choice
  (blend order), 0x20, 0x40 tint from area light, 0x80 snap to ground, 0x400 distance cull, 0x10 screen-space
- +0x04 s16 id
- +0x06 s16 mesh source: 1 = the owner's effect model (monster entry 3), otherwise global effect.bin
- +0x08 u16 default mesh index
- +0x0a s16 mesh list id (T4), +0x0c u16 lifetime (effect time units)
- +0x0e u8 position track (T2): offset path, rotated by the spawn rotation and yaw, added to the spawn position
- +0x10 u8 spin track (T2): angles added over time
- +0x12 u8 scale track (T2): multiplies the spawn scale
- +0x15 u8 draw variant
- +0x20 u8 colour track (T3): ARGB tint
- +0x22 u8 aux vec3 track (T2)
- +0x24 s16 child list id (T4)
- +0x26 u8 rotation track (T2): added to the spawn rotation
- +0x28 f32: when equal to the default constant the mesh is drawn normally, else an alternate draw path
Track id 0 is valid; an emitter whose track field matches no key simply has no such track.

### T6 physics particle def (0x8c) - create 113d0b60, setup 113d11c0, motion 113d2190, spin 113d2700
- +0x00 u32 flags (0x80 snap to ground, 0x100 keep bouncing), +0x04 s16 id, +0x08 default mesh, +0x0a mesh list (T4)
- +0x0e u8 velocity-multiplier track (T2, per tick drag), +0x10 / +0x12 u8 further tracks (spin multiplier?)
- +0x14 vec3 velocity, +0x20 vec3 velocity jitter; velocity x/z rotated by the particle yaw; pos += v per tick
- +0x2c vec3 rotation, +0x38 vec3 rotation jitter
- +0x44 vec3 angular velocity, +0x50 vec3 angular velocity jitter (rotation += angular velocity per tick)
- +0x5c f32 gravity (subtracted from v.y per tick)
- +0x60 f32 ground interaction: bounce factor (v.y = -factor * v.y on ground contact), +0x64 f32 horizontal damping
  on bounce, +0x78 s16 child timeline started on bounce (-1 none), +0x7c s16 max bounces (0 = unlimited)
- +0x70 u16 period of a mesh flip-book (frames)
- +0x74 u8 scale track (T2), +0x7e s16 child list (T4)
Lifetime presumably at +0x0c like T5 (not yet confirmed).

## Material effects (separate system) - EQUIPMENT, not monsters
`get_effect_bank_instance_ptr` 10bbe0a0 / `init_material_effect_instance` 10bba7a0: 0x94-byte runtime instances built
from 0xb4-byte definitions (UV scroll, flip-book, colour and alpha ramps). Definitions live in mhfdat.bin: header
+0x294 -> per-model lists (0x18-byte rows, u16 definition ids from +8, up to 8), +0x298 -> definitions (0xb4 each;
mhfdat 2026-10 build: lists at 0x15b0600, defs at 0x15b8500). Only character code uses them
(setup_character_material_effects_for_model 10bbac20 on character +0xd28, render_character_model_parts 10b81e30):
armour/weapon glow. Monster glow is NOT driven by this.

## Alternate draw path (emitter +0x28 != default)
113ce4d0 draws the particle mesh via 10007fd0(0,0,0,4,0,value,3): disables the post-process render-target owner
(10029cb0, 0x210 bytes) and the effect render helper (10025810, 0x550 bytes) for the draw, then draw_mesh_object
10013440 with pass kind 4 and the value as its last argument (passed on to render_mesh_batches 10018d30 / 1001b210 in
a float register the decompile drops). em130's heat-flame shells use 0.05. Probably a distortion / soft-blend strength;
confirm live (bp 10013440 when a flame shell draws, read the pass state).

## em130 heat flames (placement from the client)
Handlers 11216cc0 / 11216db0 / 112190d0 / 112192a0 read a bone's world position (10848420(owner, bone): bone record
stride 0x1c0, translation at +0x30) and play effect 0x476 attached (113d62d0, sub | 0x8000): subs 10,11 / 14,15 /
28,29 / 32,33 at bone 34 (head, horn flames), 12/16/30/34 at bone 3 (back plates), 13/17/31/35 at bone 44 (tail club).
Shell meshes 35-38, 39-42, 66-69, 70-73 are nested layers (colour alpha 255/255/176/96).

## Global effects (dat/effect.bin)
Entry 18 (JKR) = a pack table whose entry 0 is the same directory as above (u16 version 1, u16 count 61, count x {type 1, id}) and entries 1..61 the effect files. Ids (the first directory word 0x003d0001 is the header: version 1, count 61): 0xbb8-0xbcc, 0xfa0-0xfc6, 0x1004-0x100a, 0x13ee, 0x13ef. Their meshes (src 0 and the file's own) are effect.bin entry 0. 0xbb8 = hit effects: timeline 0 orange impact sparks, 1 red splash, 4-8 coloured slash streaks.
