# Hunter (player) core: MH2 to MHF-Z map

Source of the map: `tools/mh2match.py` matches functions of the named MH2 (Dos, PS2) decompile
(`thirdparty/mh2-decomp`) to MHF-Z's `mhfo-hd.dll` by numeric features, call graph and code layout (results in
`analysis/mh2_matches.csv`). This file records only facts (addresses, offsets, behaviour in prose). No code is copied from
either game.

## Health

| MH2 name | MHF-Z address | How it was found | Behaviour |
|---|---|---|---|
| Player_Heal | 10a983f0 | pouch.c layout + identical skill-adjusted quarter rule | heal amount +25% / -25% depending on two skills (MHF skill ids 0xa5 / 0xa6, MH2 used 0xA3 / 0xA4), then calls AddHp |
| Player_AddHp | 10a98010 (callee of Player_Heal) | call position | adds a signed delta to current HP, clamped to 0..max; also raises the "recoverable" (red) amount |
| Player_AddMaxHp | 10a984f0 | pouch.c layout + clamp 1..150 (0x96) | changes max HP (clamped 1..150), then caps current HP to it |
| Player_GetSkillAmmoMask | 10a99290 | constants | |
| Player_AddStamina | 10a99620 | pouch.c layout | |
| Player_AddMaxStamina | 10a99d10 | constants + layout | |

### Storage (anti-cheat scrambling)
The hunter is an actor object. HP values are not stored in plain form:

* `index` = u16 at player+0x0c
* `key` = NOT(u16 at 0x1edb7626 - 2*index) XOR (u16 at 0x11a422c4) XOR 0x5ec0, all 16-bit
* current HP = rotate-right-16(u16 at player+0x624, 3) XOR key
* max HP = rotate-right-16(u16 at player+0x6bc, 5) XOR key, and the game clamps it to 1..150

Monsters and other actors use the same +0x624 slot with a different table (0x1edb768e) and a 5-bit rotation (getter
10aa0d70, setter 10aa0db0). That is why reading the hunter with the monster formula gave nonsense (24500 / 9999).

The party array at 0x1e2a3844 + i*0x9d0 (function 101c2c20) and its +8 short are NOT the live HP (read 0 while alive).

### God mode
`mhfz-engine/tools/tracer/php.py god <player>` holds HP at max HP. The player pointer still has to be confirmed in a live
session: candidates are the actor objects seen at camp (0x0fae60f0, 0x0fae6fe0; they move between sessions). The
argument of Player_Heal / Player_AddMaxHp (ECX / ESI) is the player pointer, so a breakpoint on 10a984f0 or 10a983f0
during a heal gives it directly.

## Status
Not yet verified in game (the client was closed before the test). Everything above is from static reading of the MHF
pseudo-C guided by the MH2 layout.
