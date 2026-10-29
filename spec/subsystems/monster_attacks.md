# mhfsdt.bin - per-monster shape/hit tables (partially decoded)

Loader: `10afcd10` (load_mhfsdt_bin), lookup `10afcfd0` (binary search over 0x1c-byte rows by u16 at +2).
File `dat/mhfsdt.bin`: ECD -> JKR -> 779,328-byte relocatable image (offsets are image-relative).

## Layout
- 104 rows of 0x1c bytes, keyed by monster id (row 130 = Varusaburosu, em130).
- Row 130: count 121, u6 = 19 (number of groups), p8 = 0x95ae0 (0x28-byte records), p10 = 0x96de0 (group table).
- Group table at p10: `u6` groups of 0x20 bytes = 8 u32 pointers. For em130 all 8 pointers of a group are identical
  (8 slots - probably per-variant/level; others may differ).
- Each pointer -> list of 0x28-byte records, terminated by a record whose first i16 == -1.
- Record: `u16 id` (0x2,0x3,0xc,0x13,0x14,0x16,0x18,0x19,0x1c,0x22,0x29,0x2c,0x79,0x7d,0x7f), `u16 kind` (0/1),
  `u16 flag` (1 only on 0x7d), then three floats at +0xc, +0x18, +0x24 (e.g. 150,0,30 / 285,140,-135 / 2000,0,0),
  other bytes zero. Looks like per-body-part hit-volume or attack-reach definitions (distance/offset in game units).
  A 3-record pattern 0x29/0x7d/0x2c (150,0,0 / marker / 150,0,0) repeats in groups 4, 8, 11: probably a
  start/marker/end triple of one attack.
- Group 10 holds a 2000-unit reach (projectile/breath), group 17 a 500-unit one with id 0x79.

## Open
- Meaning of `id` (shape vs bone vs effect id) and mapping group index -> `FUN_1121d390(owner, 4, N)` calls in
  `em130_motion_event_script` (10da8e00). Needs a live trace (tools/tracer) to confirm.
- Fields p8/pc/p14 of the row: flat 0x28-byte arrays, not decoded.
