# Region 0x11200000-0x113FFFFF: subsystem summary (agent r10)

Status: partial; ~620 functions named in `analysis/claude_names/r10.jsonl`. Engine-neutral notes; addresses are DLL VAs. Confidence is moderate unless stated.

## 1. FX / action-instance system (0x1120xxxx - 0x1131xxxx, ~60% of the region)
A pooled "FX instance" record (0x200-byte extra block per slot) drives visual and gameplay effects bound to an owner character.
- Alloc `111d4e20` (pool slot index from `11353f70`, free-slot ring `DAT_1e372630`, doubly linked active list `DAT_1ecb1660`, always under critical section `DAT_1e73ad88`); free `111d4ed0`.
- Record fields: +4 u16 family (0x02..0x8e, 0x3e = generic), +6 u16 effect id, +8 u8 state (0 start, 1/3 running, 2/4/5/7/9 ending, 6 free-pending), +0x28 update callback (a per-family state dispatcher), +0x1c extra block, +0x2c..0x34 yaw/pitch/roll (u16 turn fractions), +0x38..0x40 position, +0x44..0x4c previous position, +0x68/+0x6a life, +0x94/+0x98 timers, +0xac owner character, +0xe0 draw node, +0xec scale, +0xf0 yaw, +0xf2 area id, +0x158/+0x15c flag words, +0x174/+0x178 definition row (found by binary search `10afcfd0` in a 0x1c-byte-row table).
- ~270 "spawn" functions share one template (check owner active and in current area, alloc, copy owner pose, set family/callback). Named `fx_spawn_tXX[_idYY][_vN]`. Each family has a state dispatcher (`fx_tXX_state_dispatch`) calling start / update / end handlers (`fx_tXX_start|update|end`); the end handlers and `11322b70` release the draw node and set state 6.
- Generic family 0x3e (about 450 call sites via `1129c470`/`1129c810`): start handler `1129d3e0` (18 KB switch on effect id); running update `112b3d00` dispatches by a per-effect class table (`DAT_11657840`) into four giant handlers `112b2f90`, `112afc00`, `112ae010`, `112ad9e0`. Class 3 uses a 70-entry jump table to per-effect scripts `112a26e0..112ad2a0` (named `fx_t3e_c3_script_caseNN`).
- Draw nodes are inserted depth-sorted into 512 buckets (`10b8f6f0`), buckets `DAT_1ecb1ec0`, `DAT_1ed06880`, `DAT_1ed6d6a0`.
- Owner "character record" (stride 0x1050 at `DAT_1dc6b750`, also NPC/monster array stride 0xef0 at `DAT_1ed7ad2c`): +3 class byte, +0xc index, +0x10 npc flag, +0x12 local flag, +0x14/+0x15 action id/substate, +0x16/+0x17 previous, +0x32c motion id, +0x448 roll seed, +0x678 model resource (+0x24 joint table stride 0x1c0, <=0x75 joints), +0x7f8 area id, +0xa0..a8 rotation, +0xac..0xb4 position, +0xb20 time scale, +0xbcc active skill ids u16[28], +0x708 ground height.

## 2. Particle / effect-player system (0x113cc - 0x113d7)
Effect templates (resource) live in 0x44-byte slots at `DAT_1e8d31a8`; `play_effect_by_id_*` (`113d6250`, `113d6500`, `113d62d0`, `113d6490`, ~3000 call sites total) instantiate an effect player (`113d34f0`), whose timeline update `113d3fc0` spawns particle emitters (`113cd4b0`, `113cd960`, `113cd9c0`) between section start/end frames. Curves: Vec3 key curve (24-byte keys, `113ccd90`), RGBA curve (16-byte keys, `113ccaf0`), looping flag in bit 0. Effects use a private LCG (seed `DAT_1ed5f2a2`, x*0xb0 mod 0xff53) so they never disturb gameplay RNG. Sound: positional sound request `114dd030` (outside region).

## 3. UI layout engine (0x113e - 0x113f)
Layout resources are cached by name (`113ecae0`, slots 0x114 bytes). A layout holds groups (u16 count + 16-byte element records, type byte at +0, handler table `DAT_119a622c`), part rects (0x1c-byte records), and node trees with keyframed transforms (`113f0650`, track evaluator `113f0fa0`). Draw path: `113eeb70` group -> `113ed9c0` -> `113ed380` part -> `113ecc60` emits a textured quad (rotation, flips, tint multiply `113ecbd0`, 2D batcher `1000f1d0`). Notice message ring: 20 x 0x214-byte records (`11355710`, `11355510`).

## 4. Character action layer (0x1131 - 0x1136)
`113331d0`/`11328db0` begin a character action (id + substate, previous kept); ground snapping `11327530`; line probes `11321460`, `11321340`; many 1-caller giant state machines (`1132a5f0`, `1132c790`, `1132e1e0`, `1132fd40`, `11331730`: 6 KB each, per-class action update) not yet analysed.

## 5. Items / containers / camera (0x1139 - 0x113c)
Item pools `DAT_1e80db38..` (0x1c00-byte arrays of 0x38-byte slots, four 0xe-byte records each; `1139f1a0` search) and storage categories `DAT_1e80db48` (`113b0400` find-by-mask). Camera target logic at `113c16f0`, `113c2250`, `113bdbe0`. Area block lookup (0x550-byte blocks, 1000-unit cells) `113aa800`.

## 6. Not found in this region
No socket/crypto/packet-handler code was seen (no send/recv, no cipher loops). Network structure lives above 0x114xxxxx. `11349810` builds a party/lobby menu flag word from `DAT_1e505xxx` session globals.

## Open questions
- Meaning of FX family numbers (0x11..0x8e): likely per-character-class or per-skill-group modules; unconfirmed.
- Per-effect-id semantics inside the class 0/1/2 giant handlers.
- Giant 1-caller state machines in 0x1132a000-0x11331fff and 0x1134f980 (menu flow).
