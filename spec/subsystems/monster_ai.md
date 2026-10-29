# Monster AI and entities (subsystem spec) - first version, 2026-10-14

Confidence tags: [H] verified in code/data, [M] read from code, [L] inferred. All addresses are VAs in `mhfo-hd.dll` (base 0x10000000).
Tables below were dumped directly from the DLL (`work\ai\pev.py` helper reads any VA; `work\ai\findptr.py` finds data pointers to a function).
Companion data: `analysis\claude_names\s_monster_ai.jsonl` (+116 auto-derived per-species table entries), and other agents' per-species names (`em130_*`, `em003_069_*`, `ai_op_*`).

## 1. Big picture

Monster behaviour is **native C++ code per species + a bytecode "AI script" interpreter whose scripts are compiled into the DLL's .data**, not stored in the pac files.
The em*.pac files only carry model, textures, motions (entry 2), effects (entry 5) and materials (entry 6). Per-monster numbers (HP, hit zones, rank scaling) come from `dat\mhfemd.bin`.
A new monster therefore needs: (a) a model/motion pac, (b) rows in `mhfemd.bin`, (c) native code or - better for a rewrite - a data-driven re-expression of its species handlers (spawn / tick / request_state + AI script).

## 2. Actor (entity) storage [H]

* Array of **40 actors**, base pointer `DAT_1ed7ad2c`, **stride 0xef0**. Allocation `10bc39c0` (zero 0xef0 bytes, +0=1 active, +0x10=1, +0x13 and +0xc (u16 id) = index, +0xab3 = remote flag copied from session `+0x23f8`, spawn serial +0xd78). Reinit all: `1084cc20`. A second 20-record array (same stride) at `DAT_1dcd3718` is reinitialised in the same function (probably NPC/other actor class) [L].
* Players are NOT in this array: they use 4 records of stride 0x1050 at `DAT_1dc6b750` (NOTES.md). Aggro code indexes both.
* **Type byte `actor+3` == em id** (em001=1 ... em176=0xb0; values >0xb0 are forced to 0, `1086e490`). em130 Varusaburosu = 0x82; em121 Baruragaru = 0x79.
* Lifecycle byte `actor+4` [M, `108745c0`]: 0 = just spawned (run `1086f270` spawn init, class vtbl[2]); 1 = alive, locally simulated (`108728a0`); 2 = remote/proxy-controlled (`108742a0`); 3 = despawn (`108742d0`). `actor+0` active (2 = special spawn).
* Obfuscated HP: current HP is a u16 at `+0x624` stored as `ror/rol5( ~key[id] ^ hp ^ 0x11a422c4 ^ 0x5ec0 )` where `key[id] = *(u16*)(0x1edb768e - 2*id)` (anti-cheat). Decode: `hp = ~key ^ ((v>>5)|(v<<11)) ^ (u16)DAT_11a422c4 ^ 0x5ec0` (sign-extended 16-bit) [M, `108745c0`, `10db0ba0`]. Spawn encodes it in `10aaa420`. `actor+8` is a separate int (stagger/stun-like counter or base HP from stat rec; set by `10841710`/`108414e0`, capped 0x1e/0x3c/900/0x5a) [L].

### Field map seen so far (offsets from actor)
| off | meaning | conf |
|---|---|---|
| +0 | active (1 live, 2 special) | H |
| +3 | type = em id | H |
| +4 | lifecycle 0 spawn/1 active/2 remote/3 despawn | M |
| +5 | step inside current action (also +9 in some helpers) | M |
| +8 | int counter/base value | L |
| +0xc | actor index (u16) | H |
| +0x10 | valid flag | M |
| +0x14 | **sub-state / action id** | H |
| +0x15 | **major state** (0 idle/patrol, 1..3 combat variants, 4 reaction/hurt, 5-8 special: 5/6 skip the AI script, 8 dead?) | M |
| +0x16/+0x17 | previous sub/major | M |
| +0x1b | variant (quest sub id) | M |
| +0x60 | 4x4 world matrix (64 B) built by `1084b610` | M |
| +0xa4 | yaw (16-bit angle units, 0x10000 = 360 deg) | M |
| +0xac/+0xb0/+0xb4 | position xyz | H |
| +0xb8/+0xbc/+0xc0 | scale | H |
| +0x1d4 + layer*0x50 | animation layer: +0 playing, +8 time scale..., +0x1dc frame, +0x210 motion ptr | M |
| +0x32c[layer] | current motion id of layer (u16) | H |
| +0x340/+0x342 | default blend / layer count | M |
| +0x344.. | 9 body-part slots x 8 B; +0x34a+8i = part damage state, +0x34b flags | M |
| +0x410 | mode (0 normal,1,2,4 ...) | L |
| +0x412 | flags: bit1 remote proxy, bit4, bit7 (0x80) scaled, 0x100, 0x800 | M |
| +0x474 | species class table (6 fn slots) | H |
| +0x510 | stat sub-record (+4 phase/rage stage, +8 timer, +0x40..+0x4c cooldown counters) | M |
| +0x624 | obfuscated HP | H |
| +0x678 / +0x680 | model/resource ptr, model descriptor | M (NOTES) |
| +0x6f8.. | home position | M |
| +0x722 | current target player slot | M |
| +0x7f8 | stage/area id the actor is in | M |
| +0x828 | AI-script sub-state byte | M |
| +0x898/+0x89c | damage multipliers (init `10851990`) | M |
| +0x8cc | species ops table | H |
| +0x9f0 | AI script set pointer | H |
| +0xa10/+0xa14/+0xa5c | main script idx / call depth / instruction pointer | H |
| +0xa34 | remembered target slot (0xff none) | M |
| +0xa7c/+0xa7f/+0xb04 | masks: players in aggro range / aggro / aware | M |
| +0xa80[i]*2, +0xb08[i]*4 | per-player aggro timer / aggro counter (max 30000) | M |
| +0xaa0/+0xaa2 | enrage timer base / current | M |
| +0xaa6 | enraged flag; +0xaa8 enrage pending | M |
| +0xab3 | remote-controlled flag | M |
| +0xb07 | pending AI-script event bits (see 5) | M |
| +0xc8c | variant index into per-type tables | M |
| +0xcc4.. | species-specific scratch | L |
| +0xd7c | link to owning/proxy object | L |

## 3. Per-species dispatch tables (all indexed by `actor+3`, 0..0xb0) [H]

| table | VA | content |
|---|---|---|
| class table ptr | `PTR_PTR_11a4e420` | -> 6-slot vtable stored in actor+0x474: [0] init (`1086e490`), [1] reinit, [2] per-frame post/dispose, [3] ?, [4] ?, [5] `can_be_interrupted(actor)` predicate. Families share one table (Rathian family 0x118563ec, default 0x118c2788 -> stubs). |
| ops table ptr | `DAT_11a4e6e8` | -> actor+0x8cc. Slots +0x18 value override (used by `10841710`), +0x2c per-frame hook (`1084b610`), +0x40 post-tick hook (`108ffa90`), **+0x44..+0x68 = per-major-state tick handlers `PTR_FUN[major]` (10 entries)**, then u16 pair tables (action/motion maps). Species dispatchers e.g. `10d3fea0` (em121 action switch on +0x14) sit at larger offsets (+0x8b0). 0 for many simple species. |
| **spawn** | `PTR_caseD_9_118c3350` | `on_spawn(actor)` called by `1086e490`. Typically resets actor, sets up params, enters first state. |
| **tick** | `PTR_FUN_118c3628` | `ai_update(actor)` per frame (called by `1086e8a0`). |
| **request_state** | `PTR_FUN_118c38f0` | `request_state(actor, major, sub, mode)` (default `10850d10`). Called by tick code, AI script op 0x05 retarget (`1086e950`) and net packets. |
| type descriptor | `PTR_DAT_118c3bb8` + type*0x28 | 10 dwords: +0x14 -> motion table (12 B records), +0x18/+0x1c alternates, +0x20 u16, +0x22 u16, **+0x27 flag byte** (bit0 -> `10851990` init damage multipliers every tick). `108471c0` returns it, with variant overrides for types 1,9,0x15,0x2e,0x33,0x41,0x44,0x57,0x58,0x60,0x67,0x76,0x85. |
| group id | `PTR_DAT_11a4e9c0` | maps type -> species group (used for part-break triggers and AI op 0x2c). |

`work\ai\gen_tables.jsonl` / s_monster_ai.jsonl lists every distinct spawn/tick/request_state function with the em ids that share it (116 new entries). Families: e.g. Fatalis `10bea970` for em002/036/071, Rathian family tick `10bde780` for em001/011/037/041/042/049..., Varusaburosu: spawn `10da1e70`, tick `10da8400`, request_state `10db0ba0` (+ `em130_enter_major_0..4`).

### 3.1 Species tick pattern (em130 `10da8400` is representative) [H]
```
tick(actor):
  clear +0xc82; idle-look helpers (10858420/108584c0/10858c80)
  update quest-dependent params (+0xb5e/+0xb60 via 1085c170)
  species per-frame helper (10da1830)
  code = actor_poll_events(actor)              ; 10842a20  -> reaction code
  switch(code): 1,2 small hurt | 5 flinch | 6 stagger | 8 knockdown | 0xa special | 0xb | 0xc part break
                | 0xd/0xf/0x10 phase triggers | 0x11 | 0x1d,0x1e ...
      -> request_state(actor, 4 /*reaction major*/, subIdx, 3)   ; sub depends on mode +0x410 and hit zone +0x416
  species timers decrement (+0x40..+0x4c counters)
  ai_script_run_if_pending(actor)              ; 1085c5e0 -> 108696d0 interpreter
  prev = (+0x16,+0x17) := (+0x14,+0x15)
  ops->tickMajor[+0x15](actor)                 ; ops table +0x44.. : per-major state handler
```
`request_state` (`10db0ba0`): sets +0x50e=1, resets time scale, picks target from mask if local (`10869350`), loads attack profile (`10853780`), `switch(major)` -> `enter_major_N(sub,mode)` which starts the motion (`1084fe60`) and primes timers; then applies HP/time-based phase interrupts (compares encoded HP against 0xe10 / 0x1518 / half-life thresholds, rank-dependent `+0xccc`) and triggers the rage/phase change (effects 0x17/0x22/0x2b..., sound 0x44). Mode arg 3/4 are ignored when the actor is remote-controlled (+0xab3).

### 3.2 Reaction / hit events
* `10842a20` (5.6 KB) computes the reaction code from damage/status/HP and part break state (+0x344 part slots, thresholds from the per-type status record `1085b530`, 0x50 bytes per type x rank).
* **Part-break trigger table `DAT_1188edf0`** (0x1c-byte records, scanned by `1084e560`, terminated by u16 0xffff): `{u16 type_or_group; u8 part_idx; u8 required_state; i16 ?; i16 flag; u16 reaction_action_id @+8; f32 1.0 @+0xc; 3 x f32 params}`. Matching part state -> `108601c0(actor, action, param)` plays the reaction and marks the part flag. Example rows: type 1 part 6 state 2 -> action 0x21.
* Enrage: `10851c60` / `10851d70` / `10852120` set +0xaa6, recompute multipliers, timer `(+0xaa0)`; AI op 0x35 tests it.

## 4. Motions [H/M]
* Motion tables: per type a table of **12-byte records** at `type_desc+0x14` indexed by "motion index"; record byte0 = motion id (low), byte1 layer mask (0xff all layers, 0x10..0x12 layer exclusions), +4 i16 start frame/speed, +6 i8 blend, +7 default next blend, +8 alt id, +9 link. `1084fe60(actor, idx, blend, start)` plays it.
* Stored motion id per layer (u16 at actor+0x32c): `id = motionIdx + (layer+5)*200` (layer 0 -> 1000+idx). `108fd780` decodes `id`: **space = id/1000** (0 shared pool, **1 per-monster pool**, 2/3/4 other shared pools), **group = (id/100)%10, index = id%100**; per monster slot 0x3ac dwords and 8 group offsets. Layer count = stat rec byte +5 (x2 groups). This matches the pac entry 2 "100-entry tables" (motion id = group*100+index).
* `108fd910` binds the data to the layer (+0x1d4+layer*0x50), `108fd380` allocates the per-slot pool when the pac has entry 2.

## 5. The AI script VM [H structure, M semantics]
* Interpreter `108696d0` (called only from `1085c5e0`): `ip = actor+0xa5c`; loops up to 1000 ops; `switch(*ip)`. Not run when major state (+0x15) is 5 or 6. Debug strings in the binary name ops: `MAIN_JUMP`, `CALL_CONTENTS`, `CALL_SUB_CONTENTS`, `ANGLE_CK`, `NEAR_POS_CK`, `T_KIND_AREA`.
* Script set (`actor+0x9f0`): array of pointers, set by per-species spawn code (e.g. `1019f910` for em017 -> `PTR_PTR_11a17888`, `10050f60`). [0] main scripts table (indexed by +0xa10), [0x10],[0x20],[0x28],[0x2c],[0xc],[0x34],[0x38] = event scripts, [0x18] timed sequence table, [0x24] subscripts, [0x3c] contents group, [1] contents. Some script constants are patched at spawn from the difficulty parameter block `DAT_1e77dce0+0x24` (e.g. +0x728..+0x740).
* Events: bits in `actor+0xb07` (0x40,0x80,0x20,0x10,8,4,2) pick the event script (`10860500`) -> sets ip (+0xa5c). Bit 2 is raised every tick by `108728a0` for some species when the actor is idle/mode 0 and aware of players.
* Format: 1-byte opcode, operands inline. Block opcodes use a sub-byte: 0 = begin, 1 = case/else, 2 = end (`ai_script_skip_instruction 10860730` holds the **operand length table**; `ai_script_find_matching_sub_op 10860a10`). End marker `0xff` handled by `108675a0`.
* Opcodes (~130; all handlers named in analysis `ai_op_*`): 01-03,0x12,0x13,0x4d,0x52,0x53 awareness/aggro/target selection; 05 retarget+move; 06 set target descriptor; 07 jump main script; 0a set sub-state (+0x828); 0b/0c/0d state/flags; 0f/10/80 random/weighted choice; 14/20/22/36/42/69/78 angle & distance conditions to target; 15/1c/1d/27/2c/33/3e switch blocks (stage id, HP percent, reaction id, entity group); 16/81/82 call subscripts; 17/18 timed sequences; 24 counted loops; 2e set motion variant; 35 not-enraged; 3f move to other stage; 40 set actor state idle/active (`108693e0`); 41 apply HP loss percent; 90 teleport to spawn point; 91 face target.
* Sample bytecode (em017 main script 0): `39 00 07 05 ff 00 39 02 0b 00 00 29 00 81 00 ff 00 29 02 ...` (cond 0x39 block with CALL_CONTENTS 0x81 ...). A decompiler/exporter should be built from the length table; data: 117a7abc for em017 (`11a17888` set).

## 6. Targeting and aggro [M]
* Aggro counters `+0xb08[slot]` (int, saturates at 30000; >=27000 forces re-targeting), timers `+0xa80[slot]`, masks +0xa7c (in range), +0xa7f (aggro), +0xb04 (aware). `10852a80` adds damage-based aggro; `10854d80` updates awareness by distance with per-type radii; `10854bf0` marks players in range; `10852c10` per-tick aggro cleanup/target pick (also special player buff 0x1d7).
* AI ops 0x52/0x53/0x5f choose the target (highest aggro with team parity, same stage, random tie-break); the target is kept in +0xa34 / +0x722; target position resolved by `108538b0`; yaw toward target `10167fc0` / op 0x91; look-at aim `1084f7c0`.
* Network ownership: `10856750` switches an actor between local and remote control (+0xab3) based on slot/party; remote actors run `108742a0` and proxy vtbl (+0xa30/+0xa38).

## 7. Spawning a monster [H]
`10aaa420(spawnRecord, extra, slotInfo)`: allocate (`10bc39c0`), copy rec fields, species fix-ups (types 0x68/0x70, 0x77/0x78/0x7b), then `108745c0` (state 0: `1086f270` -> `1086e490` -> species on_spawn), scale = `+0x70c * size * const`, world matrix, HP encode. Spawn record (0x3a B): +0 type, +2 variant, +6, +8 stage u16, +0xc/+0x10/+0x14 ints (hp/params), +0x1c yaw, +0x20 xyz, +0x2c, +0x30 size u16, +0x32 hp i16 (-1 default), +0x34/+0x38 out id, +0x35 main-target flag, +0x36/+0x37 variant. Who builds these records (quest/stage loader) is open.
Model loading is separate: pac loader `108fba70` (see archive-format.md): entry 0 mesh, 1/4 textures, 2 motions (-> `108fd380`), 5 effects (`113d5a90`; types 1/2 = effect definitions registered per slot, NOT AI), 6 materials.

## 8. Data file `dat\mhfemd.bin` [M]
ECD+JKR-wrapped (2,571,008 B unwrapped, `tools\mhf_archive.py unwrap`), loaded by `10afa180` into `DAT_1e77dce0` and relocated from offsets to pointers (header is a table of ~24 section offsets; u32 count 0xb1 types at hdr+4). Sections used: [2] stat table (**0x34 B per type**; byte+0 flag, byte+5 layer count, u16 +0x2e base value), [3] per-type 0xc0 B records (`+0xc` base; stride 0xc0 with pointers at +8, +0xb0, +0xb8), [4] 12-entry pointer array (per-difficulty arrays; `[difficulty][type*0x50]` status/threshold records, flags at +0x4c), [0x24-offset] script/difficulty parameter block. Exact record layouts: **open** (naive parse of the unwrapped bytes does not align - check the extra transform in `1158f310` after JKR).

## 9. Adding a new monster (e.g. an MHGU monster) - checklist
1. Pick a free em id (type byte < 0xb1 limit: arrays are 177 long; ids above 0xb0 are clamped to 0 - extending needs every table above enlarged).
2. Provide `emNNN.pac` (+`-hd`): mesh, textures, motion pack (entry 2: groups x 100 indexes; layer count must equal the stat record byte +5), effects (entry 5), materials (entry 6).
3. Add the mhfemd.bin rows (stat record, 0xc0 record, per-rank status records).
4. Provide the species code: spawn, tick, request_state functions, class vtable, ops table (per-major tick handlers), motion table (12-byte records), type descriptor, part-break rows, AI scripts. In a rewrite express these as data (state-machine table + script bytecode) - em130's `enter_major_N`/tick pair is the template.
5. Register in quest/stage spawn data.

## 10. Open questions
* Exact meaning of major states 0..9 and the sub-state numbering per species (only partially labelled by the `em*_goto_state_M_S` helpers).
* Operand lengths of every AI opcode (extract from `10860730`) and a script exporter; locate all script sets (found via `+0x9f0` assignments).
* mhfemd.bin record layouts; where spawn records are produced from stage/quest files.
* Class vtable slots [3],[4]; ops table u16 tables; reaction codes returned by `10842a20`.
* Phases/rage thresholds per monster (HP breakpoints are hard-coded in each `request_state`, e.g. em130 uses 0xe10 / 0x1518 / rank-scaled values).
