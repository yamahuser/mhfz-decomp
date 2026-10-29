# COMBAT subsystem (MHF-Z client, mhfo-hd.dll) - working spec

Status: first pass (hit detection + damage-application pipeline). Confidence tags: [H] read directly from decomp, [M] inferred from several sites, [L] guess.
All addresses are VAs in mhfo-hd.dll (ImageBase 0x10000000). Decomp files: decomp\<addr>.c.

## 0. Big picture
Combat is fully client-side simulated and frame-locked (30 Hz tick). Per tick (inside the gameplay update path):
1. `108af140` pre-clear: zero every actor's per-tick damage accumulators [H].
2. `108b6bf0` hit dispatcher: for every live **attack object** x every candidate **victim actor** that passes team/stage/immunity filters, call `108b7b60` -> `108c5910` (shape overlap test) -> `108c26b0` (apply hit) [H].
3. Later in the same tick, each actor's behaviour function (`10842a20` for non-player/monster-style actors) converts accumulated damage into HP loss, part damage, break counters and a **reaction state id** (return value) [H].
So the model is: *attack objects (hitbox lists) overlap actor hurtbox lists -> per-victim accumulators -> end-of-tick resolution.*

## 1. Actor containers [H/M]
Common "actor" record; players use a larger 0x1050 superset (same low offsets).
| container | base | stride | count | note |
|---|---|---|---|---|
| player character slots | `DAT_1dc6b750` | 0x1050 | up to 4 cleared per tick (session byte `+0x23fa` of `DAT_1e7fff3c` = party size; 100 slots exist per NOTES) | `+0x10`==0 means player-type actor |
| actor array A | `DAT_1dcd3060`..`1dce5b20` | 0xef0 | 20 | iterated by hit dispatcher group code 1 |
| actor array B | `*DAT_1ed7ad2c` | 0xef0 | 40 | group code 0 |
| special actors | pointer array `DAT_11beed00` | ptr | 4 | group code 2 |
| attack-object pool | linked list head `DAT_1ecb1660` (next ptr at obj+0x14) | 0x200 each (pool `DAT_1ed528c0`, slots reserved by `11353f70`) | - | `111d4e20` allocates |
Actor global session ptr `DAT_1e7fff3c`: `+0x14` local stage/room id (compared with actor `+0x7f8`), `+0x23f8` local player slot, `+0x23fa` party size, `+0x23ff` offline/solo flag.

### Actor fields used by combat (offset: meaning) [H unless noted]
- `+0x00` active, `+0x03` **type id (species / NPC class)** indexes per-type tables, `+0x0c` slot index, `+0x10` 0=player-character, nonzero=monster/NPC, `+0x14/+0x15` mode bytes (0x15==5 dead/ignored, 4/6 special), `+0xac/+0xb0/+0xb4` world position (x,y,z float), `+0xb8` model scale, `+0xa4` yaw (u16, 65536=360deg).
- `+0x7f8` stage/room id (hit only if equal to attack object's `+0xf2`).
- `+0x4e4` team/side nibble (attack `+0xf5`; same-team filtered via `((a^b)&1)==0`).
- `+0x624` current HP (u16, **anti-tamper obfuscated**: stored = rotl((v ^ keyTable[id] ^ DAT_11a422c4 ^ 0x5ec0),5); getter `10aa0d70`, setter `10aa0db0`), `+0x6bc` max HP (obfuscated differently, getter `10aa0ce0`, rotr 3 / xor ~key[id] ^ DAT_11a422c4). Clean-room: treat as plain u16.
- `+0x82c[8]` bytes: per-part "hit flags this tick" (OR'd with attack `+0x77` damage-type bits).
- `+0x854[8]` s16: **per-part damage accumulated this tick** (index 0..7 = body part / hurt group; `+0x416` byte = index of most-damaged part). Players use only [0]. `[8]` (offset 0x864) is a special 9th slot used by tail-cut/special logic.
- `+0x86e,+0x876,+0x87c,+0x884,+0x88c,+0x8bc,+0xd4c,+0xd5a`: s16 **status-gauge input accumulators** for this tick (see s5).
- `+0x898` float: this actor's *outgoing* damage multiplier; `+0x89c` float: *incoming* damage multiplier (applied to every part's accumulated damage).
- `+0x344 + 8*i` part record (i=0..8): `+0` enabled, `+4` s16 **part HP** (0x348), `+6` byte break counter (0x34a, saturates 99), `+7` ?. Part HP reaching <=0 => part broken event.
- `+0x415` hit-this-tick flag (set to 2 by `108c26b0` on being hit), `+0x410` stance/state, `+0x828` state byte (2=down?), `+0x49e/+0x49c` last hit reaction id and hit-id, `+0x496` OR of attack `+0x72` flags.
- `+0x8c8` pointer to the attack object that last hit this actor; `+0xd10` last attacker actor; `+0x44c` same.
- `+0xd80` pointer to the **monster stat record** (defense table): s16 `[+0x4e + 2*part]` per-part defense/bonus; falls back to global default `DAT_1e800188` when null.
- `+0x4a2[0x20]` ring buffer (index byte `+0x4e8`, wrap &0x1f) of recent attack-instance ids (`obj+0xdc`) - duplicate-hit suppression: an attack instance already in the victim's ring cannot hit it again.
- `+0x900/+0x8e0 [16]`: second ring for explicit hit immunity timers (value 0x1e = 30 ticks) used by attack class 10.
- `+0xc10,+0xc14,+0xc18,+0xc1c,+0xc20` floats: **status resistances** (0..1 fraction) for 5 buff/debuff classes (see s5).
- `+0xcf4/+0xcf5` u8,u8: knock-back/stagger request (kind mask, strength 0x10..0x80) set by hit.
- `+0xd6c..+0xd78`: accumulated "blow" vector/strength (sound/guard push) for attack ids 0x41,0x42,0x44,0x45,0x48,0x5c.

## 2. Attack objects [H/M]
Created by `101de750` (class 0x6f, "monster/NPC attack", sub-id 1..22) and `101e6210` (class 0x71, **player attack**, sub-id 1..0x55) and ~40 `spawn_action_object_t*` wrappers. Allocated from the 0x200-byte pool.
| off | meaning |
|---|---|
| +0x00 u16 | active |
| +0x04/+0x06 u16 | class / sub-id (e.g. 0x71 player, 0x6f monster; 0x79 special-hit class: sub 1,2 treated separately) |
| +0x0c u8 | owner slot (0xff = no owner/environment) |
| +0x0e u8 | owner slot copy, +0x0f u8 phase (2 = armed) |
| +0x14 ptr | next in active list (linked) |
| +0x28 ptr | per-tick callback (e.g. `101e61a0` switch on +0x08 phase) |
| +0x2c/+0x30/+0x34 | origin position (copy of owner pos / owner +0xa0..a8 axes) |
| +0x38/+0x3c/+0x40 | current hit-effect position; +0x44.. previous |
| +0x68..: | the "hit definition" copied/filled each hit: see below |
| +0x6c u16 | **base damage ("power") of this hit** |
| +0x6e u16 | **hit-reaction id** (large switch in `108c26b0`; 8=heal/negative-damage, 0x38,0xa5-0xa7 special etc.) |
| +0x72 u16 | reaction flag bits ORed into victim `+0x496` |
| +0x76 u8 | hit-type / attack-type id copied to victim `+0x49c` |
| +0x77 u8 | **damage-type / status bits** (0x04,0x10,0x40,0x20,0x80 -> status class 0..4, see s5) |
| +0x7a s16 | rumble/sound code (1 = vibrate, 0xd..., 0xff none) |
| +0x7c u32 | gauge bits: 1,2,4,8,0x100 -> victim accumulators `+0x86e,+0x88c,+0x884,+0x87c,+0x8bc`; 0x2000000,0x18000000,0x20000000,0x40000000,0x1000000 -> other counters |
| +0x80 u32 | gauge amount, +0x8c u16 alt amount |
| +0x85,+0x86,+0x87 | misc: +0x87 low nibble = remaining multi-hit count, high nibble = reload |
| +0x89 u8 | status-buildup value (see s5) |
| +0x90 u16 | flags (0x20 = set owner `+0x4e6`, 0x800 = flag, 0x400, 0x10/0x01 = guardable-type) |
| +0x92 u8 | owner is monster (copy of owner `+0x10`) |
| +0x9a u8 | bit1/2/4 special handling (4 = "set damage to raw +0x6c ignoring modifiers"). |
| +0xa0 ptr | **hitbox list** (array of 0x28-byte records, terminated by s16 -1) |
| +0xac ptr | owner actor |
| +0xdc u16 | unique attack instance id (counter `108c72d0`, nonzero) |
| +0xf2 u16 | stage id; +0xf5 team; +0xf6 u8 extra damage multiplier (x/ DAT_119b5ef0) |
| +0x158/+0x15c u32 | flags (0x400 = no-HP-damage?, 0x8000 etc.) |
| +0x174 ptr | attack-table pointer: (`ptr+0xc`)+ (id*0x10) 16-byte entry copied to `*(obj+0x1c)+0x3c` |
Attack definition source for players: `FUN_10afd0c0` returns 40-byte (10-dword) record copied to `*(obj+0x1c)+0x14`; 16-byte tail record from table at `obj+0x174`. (Motion/attack data files - see s7.)

## 3. Hit shapes and detection [H]
**Hitbox / hurtbox record = 0x28 bytes (20 s16)**, same format for attacks (list at attack `+0xa0`) and for victims (per-type list from `10846ca0`, plus `idx*0x28`):
```
+0x00 s16 part/bone id  (<0x76: bone/part index into actor part table; 0x77..0x7f special generators; -1 = end of list)
+0x02 s16 shape: 0 = sphere, 1 = capsule (two endpoints)
+0x08 u8  flags A (bit1,bit4,bit8 = require guard/stance state; bit4 = only when victim state in {6,9,0x86}...)
+0x09 u8  flags B (bit4 = disabled)
+0x0a u8  flags C (bit2,bit0x10,bit8 selection flags), +0x0b bit1 = disabled
+0x0c f32 radius (scaled at runtime by actor scale +0xb8 and an extra factor)
+0x10 f32[3] local offset (point A), +0x1c f32[3] local offset point B (capsule only)
```
`10a93dd0` (resolve volume): looks up the part record transform (`10a93d70(actor,boneId)`, matrix whose translation is at +0x30), transforms the offsets with `D3DXVec3TransformNormal`, adds the part translation, radius = rec.radius * actor.scale * factor. Outputs sphere (center xyz, radius at [3]) or capsule (A xyz, B xyz, radius at [6]).
Special ids: 0x77/0x7a/0x7b/0x7e (`10a94360`), 0x78 (`10a94650`), 0x79 (`10a94410`), 0x7c/0x7f (`10a94290`), 0x7d = list-skip marker conditional on actor bitfield (`+0xb5c`) (switchable hitbox sets).
Overlap primitives (named by call pattern): sphere-sphere `108a9b90` (dist <= r1+r2, writes contact point = lerp), capsule/sphere variants `108abc20`, `108aa220`, `108ac610`; segment/plane `108cb720`, ray vs collision grid `108cf9a0` (terrain/walls; grid `DAT_1e77dc2c`).
For **player victims** (`+0x10==0`) there is no list: a single capsule built from the player (`10a82260`, `108a9ad0` builds center/axis/length from two points).
Per-type victim lists: `10846ca0` selects by actor type id (+3), with ~35 species-specific overrides (`DAT_117c5a20`, `DAT_11750aa8` ...). Records live in .rdata (hurtboxes are code-side tables, NOT in em*.pac) [M].
Best-hit selection: for monster victims the dispatcher scans ALL victim volumes, keeps the closest to the attack (min distance via `10006900` sqrt/length), then applies the hit once (`local_a4 = 101e8460()` "multi-volume pick" mode) [M]. Otherwise first overlap wins.

### Hit filters (in `108b6bf0`/`108c5910`) [H]
- attack/victim stage ids equal; attack active & not flagged 0x400000; phase `+0xf` == 2 armed.
- owner exclusion: attacks with owner != 0xff don't hit their owner unless attack flag `+0x90 & 4`... (`local_1c != victim || (flags&4)`).
- team: `(a.team ^ v.team)&1 ==0` suppresses friendly fire unless special.
- duplicate suppression via victim ring `+0x4a2` (32 entries of attack instance id) - this IS the multi-hit interval mechanism: ring holds ids of attack instances already landed; a multi-hit attack gets new ids per pulse (`108c72d0` called when `+0x87` low nibble counts down).
- victim must be alive: `10aa0d70()>0` for player-type reaction ids 6,9,0x13.
- victim `+0x415==0` (not already hit this tick) for most attack classes.
- Invulnerability states: victim `+0x410==2` or `+0x410==4`, `+0xca6`, `+0xaab` (>0) block specific reaction ids (guard `0x1b` state via `10844bc0(0x1b)`).

## 4. Hit resolution `108c26b0(hitPos, atkObj, attackerActor, victim, outFlag)` [H]
1. Writes `atkObj+0x17c..0x18c` last hit position; `victim+0x8c8 = atkObj`.
2. Early-outs (return with `*out=1`): in certain scenarios (`DAT_1e76b89b` & session mode 0x35/0x36) for non-listed reaction ids; allies' healing id 8 allowed.
3. Records `atkObj+0xdc` into victim ring `+0x4a2`.
4. Multi-hit bookkeeping on atkObj `+0x87`.
5. `victim.+0x82c |= atk.+0x77` (damage type bits).
6. **Damage computation** (non-heal, reaction id != 8):
   ```
   base   = atk.+0x6c                     (u16)
   mult   = attackerActor.+0x898 (float; DAT_1199cb64 = 1.0 when no attacker)
   dmg    = (float)base * mult
   if atk.+0xf6: dmg *= atk.+0xf6 * DAT_119b5ef0   (DAT_119b5ef0 likely 0.01)
   ... species exceptions (attack class 0x42 sub-ids 0x38,0x55,0x56,0x7a-0x7f skip the following reduction)
   defense step (when not exempted, and not a recognised scripted case):
        dmg -= dmg * victim.+0x89c / (victim.+0x89c + DAT_119981f0)       <-- hyperbolic mitigation
        i.e. dmg = dmg * DAT_119981f0 / (victim.+0x89c + DAT_119981f0) = dmg / (1 + m/K)  with m=incoming mult, K=DAT_119981f0 (constant, unread yet)
   then per-status-class resistance factors (s5) multiply the *status* value, not HP damage
   dmg16 = (int)(factor * dmg) & 0xffff
   + FUN_108b7d60(dmg16): sword-shield-type chain bonus (table DAT_116bccf8, 2 bytes/sub-id: [kind, pct]) - adds pct/10 % when attacker has skill 0xdc/0x168
   halved if victim is player-type AND mode `10aa17c0`==1 (offline mode?) ; status value halved too
   skill 0x211 / equip effects may call `101c6b70`.
   if atk.+0x9a & 4: victim.+0x854[0]=0; dmg = atk.+0x6c (true damage)
   special: reaction id 0x38 w/ skill 0x15d, ids 0xa5-0xa7 w/ `10a62f20` -> dmg 0
   guard/boost: x DAT_116038a8 (0.5) if `108a5b90` and victim skill 0x6a.
   victim.+0x854[0] += dmg16      (players: single accumulator)
   victim.+0x876 += statusValue (atk.+0x89, modified by `10a8db70`)
   ```
   For heal reaction id 8: `victim.+0x854 -= atk.+0x6c` (negative damage = heal).
   [M] For **monster victims** the part index to credit is chosen earlier (via `108b0e00`, `108ae9b0`, `108c4830/108ba3d0` which pick the hurtbox volume and thus the part) so that `+0x854[part]` is incremented; the `[0]` form seen above is the per-hit path for player victims and the part-0 case.
7. Sets `victim.+0x415=2`, `+0x44c/+0xd10 = attacker`, `+0x4fc..` hit position, `+0x496 |= atk.+0x72`, `+0x49e=reaction id`, `+0x49c=hit type`.
8. Reaction id switch (large): sets knock-back (`+0xcf4/+0xcf5`), blow vectors, or position pushes (ids 0x88,0x89,0x8c,0x9d: lerp victim position toward/away from the hit position by a table factor from `109a2c30`; ids 0x41/0x42/0x44/0x45/0x48/0x5c "blow" accumulators; 0x39/0x7c/0x81 = grab/bind to attacker `+0xd2c`).
9. Rumble: `114dd030(1,0,1,0)` when local player is hit (`atk.+0x7a`), `10b43180(0x21,0xc)` etc.

## 5. Monster-side resolution `10842a20` (damage -> HP/part/reaction) [H structure, M semantics]
Called once per actor per tick (105 callers; it is the behaviour "evaluate" step). Steps:
1. `10841db0` (apply_damage_to_actor_and_dependents): for i in 0..7 compute `d_i = accumulated[i] * victim.+0x89c + bonus_i` where `bonus_i = FUN_1004b1d0` = `(short)stat[0x4e + 2*i] * rate` (rate = float from master record `DAT_1e77dcc4+0x72c -> +0x13e0` when game version field `*(+0x10)+0x292 >= 0x9f`, else default `DAT_11880f08`; stat = `victim.+0xd80` record or default). If damage>0 but rounds to 0, becomes 1. Sum into total damage `*param_3`; negative (heal) sums to `*param_1`. Species 0x7c ('|') special-cases negatives. Trailing HP-adjusting hooks via callback `victim.+0x8cc -> +0x20` (owner "damage filter" function) and per-species handlers.
   Also halves status gauges when victim is in certain states (`1086dc40`, `1086de10`).
2. HP update: `10851240(victim, totalDamage)` (62 callers; HP-bar/quest damage logging) and `10aa0db0` sets HP; kill when `10aa0d70()<=0`.
3. Per-part damage: loop over parts i: `d_i` recomputed; if part enabled (`+0x344+8i`) and no sigil-type protection, `10842630(actor, part, -d_i)` reduces part HP (`+0x348+8i`); when part HP < 1 -> `+0x34a+8i` break counter++ (cap 99), `1084e560` event dispatch, `108480d0` recompute part stat. Three modes selected by `actor.+0xb6c` (1,2,3 = alternative part-damage schemes: all-parts parallel / single-part / 9-part with specials, e.g. part 8 = tail with `+0x864`).
4. Output is the **next behaviour/reaction state** id (u8): 1 = dead, 2 = (HP<=0 early), 3/4 = specific recoveries for reaction ids 9/6, 5,6,7,8 = knockdown flavours, 0xb/0xc/0xd/0xe/0xf/0x10 = flinch/stagger/hit-reaction variants, 0x14,0x15,0x16... = species-specific, 0x1b/0x1c = tail/part-specific, 0x1d,0x1e = misc. Callers act on it via per-species state machines.

## 6. Status effects [M]
Player-side buffs/debuffs: `apply_status_buildup_type_a..d` (`10857380`,`108572c0`,`10857460`,`108575b0`), dispatcher `10857520` on pending-status byte `+0x892`; gauges at `+0x86a/+0x880/..` capped at 30000, with per-type hit counter limits. Victim resistances `+0xc10..+0xc20` (floats; formula `status_value = atk_status * (DAT_1162b234 - resist) * DAT_119b5ef0`), classes by `atk.+0x77` bit: 0x04->class0 (res +0xc10), 0x10->1 (+0xc14), 0x40->2 (+0xc18), 0x20->3 (+0xc1c), 0x80->4 (+0xc20). Applied via `1086b9d0(victim, class, atk)`. Class meaning (poison/para/sleep/stun/...) still to be pinned down - see open questions.
Monster-side gauges: victim `+0x86e,+0x87c,+0x884,+0x88c,+0x8bc` etc. receive `atk.+0x80 * ...` from `108b0e00` (bits 1,2,4,8,0x100 of atk `+0x7c`) - these are the per-status accumulators (poison/sleep/para/blast/... order TBD) compared against thresholds in `108413c0`, `1004aef0`, `101bc710` (threshold at `+0xd48/+0xd4a` etc.; on reaching threshold set bit in `+0x893`).
Timed buffs on players: `102dc140` apply_actor_timed_buff_value (array of s16 at block `+0x2ac`, per-player 0x9d0 block).

## 7. Weapons / motions [M]
- Weapon classes have separate code modules `wmA..wmU` (each with `*_set_state` + 0..5 kind handlers; e.g. wmR `10e1f4b0`, wmT `10e61660`, wmS `10e91480`, wmU `10e15610`, wmA `10ec2a40`, wmQ `10ed6d00`, wmB `10eea7b0`, wmK `10ef2cb0`, wmC `10f0e990`, wmM `10f10090`, wmD `10f303a0`, wmE `10f4e970`, wmL `10f5ce40`, wmN `10f649a0`, wmF `10f75ea0`, wmI `10fe2630`, wmP `10fec720`, wmO `10ff4680`, wmJ `10ec0a20`) and per-band `wpn_band_*_dispatch_enter_action` entries. These are the player/NPC action state machines.
- Actions play motion ids (`1084fe60 actor_play_motion`, group*100+index); damage windows come from motion-time windows `108ff5c0/108ff650` (0x50-byte windows per actor) which trigger attack-object spawns/effects/sounds (`1091e410`, `1091e5d0`, `1085cce0`).
- Weapon data: master record `DAT_1e77dcc4` pointer tables: `+0x74` (kind0), `+0x64`(2), `+0x68`(3), `+0x6c`(4), `+0x70`(5) armor/other 0x48-byte records, `+0x88`(6), `+0x84`(7), **`+0x7c` weapon table, stride 0x34** (u16 at +0x2e = weapon subtype used for w12 motion variant). Selected by `10a9c920(kind, id)`. Master record loader: `10af5140` (19 KB; builds the table pointers from mhfdat.bin-like blob; magic `DAT_1a66686d`).
- Weapon models `weapon\w%c%03d.bin` (`10601710`).
- Equip skill effects: per-character-slot per-tick `1081e6a0/1081e030/1081e250/1081eab0`, effect table `DAT_118dea08` stride 0x14, callbacks `PTR_FUN_118df2dc` (see NOTES).

## 8. Tick structure [H]
`108af140` (clear accumulators) -> `108b6bf0` (attack-vs-victim loop; first the pool list `DAT_1ecb1660`, then a second pass for victim group 3 = player slots) -> per-actor behaviour update calls `10842a20`. Everything is integer/float per-tick with no dt. For a 60 fps rewrite keep this at 30 Hz.

## 9. Open questions / TODO
- Value of constants DAT_119981f0 (defense hyperbola K), DAT_119b5ef0, DAT_1162b234, DAT_1199cb60/64, DAT_116038a8, DAT_118e8214 (read from .rdata/.data of the DLL).
- Where player attack power (`atk.+0x6c`) is computed from weapon raw/sharpness/motion value/affinity/skills: expected in attack-spawn code of the weapon modules (`FUN_10afd0c0` table + `101e6210` callers).
- Monster hitzone table: only per-part defense s16 `stat[0x4e+2*part]` located; element/hitzone split not found (elements possibly are separate `+0x854` indexes: 8 slots = ?).
- Status class identities and threshold tables.
- Master data blob layout (`10af5140`).
- The `0x2c4`-stride tables near `DAT_1dbbb441`: `108f5150` memset's `DAT_1dbbb440` (0x3c270 B) and `108f58d0` fills pad-input records there; this appears to be INPUT/UI event storage, not combat [M].

## 10. Addendum (constants resolved from the DLL image, multiplier sources)
Constants read from mhfo-hd.dll: DAT_119981f0 = 80.0 (defense hyperbola K), DAT_119b5ef0 = 0.01, DAT_1162b234 = 100.0, DAT_1199cb64 = 1.0, DAT_116038a8 = 0.5, DAT_118e8214 = 1.5, DAT_118e8200 = 0.9, DAT_117c9ec0 = 0.8, DAT_1182f584 = 0.7.
=> **Core hit formula [H]:**  `dmg = base(atk+0x6c) * attacker.outMult(+0x898) [* atk.+0xf6 * 0.01]`; `dmg = dmg * 80 / (80 + victim.inMult(+0x89c))`; `dmg16 = trunc(dmg) & 0xffff` plus optional skill bonus; added to `victim.+0x854[..]`.
  For player victims `+0x89c` behaves as a DEFENSE value (80/(80+def)); for monster victims `+0x89c` is a per-quest/rank float multiplier, applied later in `10841db0` as `accum*inMult` (not hyperbolic there; the hyperbola branch is skipped when victim is a monster in most paths -- see condition tree in 108c26b0 around the DAT_119981f0 use; verify when rewriting).
  Status value from a hit: `atk.+0x89 * (100 - resist_class*100?)...` precisely `statusIn = (DAT_1162b234 - victim.+0xc10..+0xc20) * 0.01 * ...` i.e. resist stored as percent (0..100) float; scaled attack multiplier `local_20` is replaced by `(100-resist)*0.01` for the status path.
**Monster multipliers [M]:** `108599c0` (-> atk mult `+0x898`) and `1085a500` (-> def mult `+0x89c`) return values in XMM0 (lost by the decompiler). They are modified in `10851990`/`100514a0`/`10178a50`/per-species inits by the per-type, per-quest-rank record `DAT_1e77dce0[3]` -> `+0x48 + (type*0x30 + rank)*4` -> {+8 float attack mult, +0xc float defense mult}; rank = `10aa1520()` = byte at `*(DAT_1e8001ec+0x50)+0x5c` (quest difficulty tier; 9 for special event ranges 0x40-0x43,0x4f-0x52). Additional species table `DAT_1e77dce0[0x16]` (0x1c-byte rows: u16 id, +0xc atk float, +0x10 def float) applied when `DAT_1e76b896` (event/duplicate-quest flag) set. Many species multiply by constants (1.5, 0.9, ...) depending on solo/party (`1087cd60`, `1087cde0`), i.e. HP/attack scaling with party size.
**Attack definition data [M]:** sorted array `DAT_1e77dcd4` (count `DAT_1e7ff40c`, 0x1c bytes, u16 class id at +2; lookup `10afcfd0` binary search) -> per class: +4 u16 count, +6 u16 version filter, +8 ptr to 0x28-byte attack defs (indexed by node sub-id), +0xc ptr to 0x10-byte hit-effect rows (obj+0x178), +0x10 ptr table (0x20-byte rows). `10afd0c0` fetches a def. Spawned nodes (`101e6210`) copy the 0x28-byte def to `*(obj+0x1c)+0x14`. These rows are file-loaded data (loaded together with the master blob by `10af5140`, magic `DAT_1a66686d`), NOT code constants. Per-attack damage `+0x6c` is then set/tuned by per-class callbacks (e.g. `112ce4e0`, `111fe130`, `10bc7910`, `105fd420`...) and player weapon modules (r8/r9 summaries) using weapon table `DAT_1e77dcc4+0x7c` (0x34 stride).
**Action nodes = attack objects:** per r9 summary, nodes (type 4 field = 0x6f/0x71 for attack classes) come from `111d4e20`; substate +8 (0 init,1 run,3 finish,6 dead) drives callbacks `101e61a0`/`101dc420`; they live ~`+0x94/+0x98` countdown ticks (decremented by `11322980` each tick) which define hit-window duration.
**Not found:** an explicit elemental/hitzone-percent table, sharpness, affinity/critical, per-weapon raw formula. In this client those appear to be folded into precomputed `atk.+0x6c` by the owner's module and into the per-part `stat[0x4e+2*part]` on the server-provided monster record (`victim.+0xd80`, filled from em*.pac config / mhfdat). Next steps: decode `+0xd80` record loader; locate `101e6210` callers that set `+0x6c` from weapon table; decode status class mapping.
