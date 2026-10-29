# Region 0x10A00000-0x10BFFFFF summary (agent r6)

Engine-neutral notes. Names/records: analysis/claude_names/r6.jsonl.

## Global data model
- **Save data** (PTR_DAT_11a3ee2c, 0x24cd4 bytes): progress-flag bitmap +0x1fdb4 (0x600 bits, dirty copy 0x1ed7a4e0); unlock bitmaps +0x64 / +0x23cdc; item pouch +0x23e28 (30 slots x 8 bytes {u16 id,u16 count,u32 extra}; slots 0-19 ordinary, 20-29 for flagged ammo-type items); item box +0x11a14 (pages x 100 slots, pages from unlock flags); storage +0x2051c (400 slots); hunter experience +0x1fdac -> rank 0..999 via cumulative table 0x11858888.
- **Master data** (DAT_1e77dcc4): item table +0xfc (0x24-byte records, +3 max stack, 0xff unlimited, +1 flags); equipment tables +0x50..+0x60 (0x48-byte), +0x7c (0x34-byte), +0x80 (0x3c-byte); pointer arrays +0x64..+0x88; "itemref" = {+1 category 0..7, +2 u16 id}; model->effect-id lists +0x294 and 0xb4-byte effect definitions +0x298. Localized strings: DAT_1e77dccc.
- **Session** DAT_1e7fff3c (+0x14 area/map id, +0x20 game clock, +0x23f8 local slot, +0x23ff offline flag); quest session record DAT_1e8001ec (+0x64 quest info with monster ids, +0x80 current quest, +0x2e quest id).
- **Actor record**: hunters in 100 slots at 0x1dc6b750 (stride 0x1050); other characters 0x28 objects at DAT_1ed7ad2c (stride 0xef0); per-player blocks 0x1e2a32f0 (stride 0x9d0). Shared field layout: +0 active, +3 type (hunters: weapon class 0..13), +0xc slot id, +0x10 non-local flag, +0x14/+0x15 action id/category (+0x16/+0x17 previous), +0xac/b0/b4 world position, +0x45c.. accel, +0x468.. velocity, +0x7f8 owner session id, +0x7fc current health (+0xfa4 12-bit fraction), +0xb2a max health (75..450), +0x678 model resource, +0x680 model descriptor, +0xd0 attachment matrix table, +0xd28 effect runtime buffer. Per-tick integrator: apply_velocity_to_actor_position (10a93110). NOTE: hunter slots DO hold world position at slot+0xac (e.g. 0x1dc6b7fc) - candidate interpolation source.
- RNG: actor LCG x*0xb0 mod 0xff53 (DAT_1ed5f2a2). Global frame counter DAT_1ed78564, UV/effect tick DAT_1ed5f2c8.

## Subsystems
- **Sound**: play_sound_cue_if_enabled (4431 callers), play_actor_sound_effect*, delayed sound queue (32 x 0x20 bytes, logic-rate), monster sound packs `sound\em%03d{,c,d,e,ce}.snp` chosen by build_monster_sound_pack_path, loaded by a state-machine sequencer; area ambient SE schedulers keyed by area id and tick modulo.
- **Render (world frame)** render_world_frame_pipeline (10b7acd0): pre-passes to render targets, scene objects with effect table (10b56430), markers, character draw callbacks, passes 6,0,1,2,4,3,5, depth-sorted draw list (enqueue/flush by view depth, 512 buckets), lights from presets (3 directional), time-of-day colour (8 keyframes, 16 steps).
- **Scene-object effects** (10b56430 + helpers 10b51xxx-10b54xxx): descriptor {part,alpha,type,flags,params}; types = UV scroll variants, flip-book, stepped rotation, axis spin, wave; all driven by global tick counter (30 Hz) -> need fractional-tick evaluation for 60 fps.
- **Character material effects** (10bba7a0.. 10bbc890): 0xb4-byte definitions, 0x94-byte instances in banks inside the character effect buffer; colour/alpha ramps, UV scroll, kinematic tracks (see spec/animation-format.md section 5).
- **Attached model trees** (10b7c1b0..10b7c9f0): recursive node walk, node dwords: world matrix [0..15], local [0x10..], mesh offset [0x20..], sibling [0x33], child [0x34]; attach index from per-class tables (0x1185d590).
- **Text/UI**: tagged text ({I..}{K..}{U..} game-text tags; `~Cnn` debug colour tags), measure/draw/wrap routines, overlay record DAT_1e3cbd64 (+0xc x,+0xe y,+0x10 depth,+0x64 layer,+0x207d0 colour), message window buffer DAT_1e7ff410 (18 lines x 0x60 x 10 pages).

## Open questions
- Action-id meanings (actor +0x14/+0x15), the huge 1-caller handlers at 10bc4aa0/10bc7910/10bdf480/10be7c50/10bff090 (likely per-weapon action state tables), 10b60230 (22 KB field/weather effects), meaning of pre-pass renders 10b7a460/10b7a940.
