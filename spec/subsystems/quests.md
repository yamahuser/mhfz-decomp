# Quest files (2026-10-16)

Source: Erupe's `bin/quests/*.bin` (server-side, JKR-compressed; 54,977 files, `<id><d|n><0-2>.bin` = day/night x 3
variants). Field positions from the open-source Erupe quest JSON converter; engine parser `core/src/quest.cpp`.

- Header 0x00-0x43: u32 absolute pointers - 0x00 main properties, 0x04 loaded stages, 0x08 supply box, 0x0c rewards,
  0x14 quest area, 0x18 large monsters, 0x1c area transitions, 0x20 area mapping, 0x24 map info, 0x28 gathering points,
  0x2c facilities, 0x30 strings, 0x38 gathering tables.
- 0x44 u16 monster size multiplier (%), 0x46 u16 size range, 0x48 u32 stat table 1, 0x61 u8 stat table 2.
- Main properties: +0x08 u16 rank band, +0x0c u32 fee, +0x10 u32 main reward, +0x20 u32 time limit (frames @30 Hz),
  +0x24 u32 map, +0x2e u16 quest id, +0x30 three 8-byte objectives.
- Large monsters: block {u8 version 1, 7 pad, u32 ids ptr, u32 spawns ptr}; up to 5 spawns of 0x3c bytes
  {u8 monster id, u32 +0x04 amount, u32 +0x08 stage, u32 +0x1c orientation, f32 +0x20/+0x24/+0x28 x/y/z}; 0xffff ends.
- Monster id == emNNN model file number (Erupe's mhfmon enum: 11 Rathalos, 130 Varusaburosu). Spawn stage == stNNN.
- Varusaburosu: 78 spawns in 13 quests (21871, 23419, 23488, 50719, 50735, 50737, 51117, 54568, 54679, 54880, ...),
  all st396 (volcanic arena) at (6307, 0, 5820), orientation 12080, size 100%, stat table 31 or 53, map 69, 50 min.
- Open: orientation unit (assumed 65536 = 360 deg), hunter start point (area transitions / map info), what the stat
  tables index (monster HP/attack tiers - not in the quest file).
- Zone transitions: header 0x1c -> u32 pointer per zone (zone count u8 0x7c) -> 52-byte records until s16 -1: s16 target stage, s16 variant, f32 current xyz, f32[5] trigger box, f32 +0x24 arrival xyz in the target stage, s16[2] +0x30 rotation. Varusaburosu quests: zone 0 -> st396, arrival (9530, 0, 10127), rotation 16384 = the hunter's entry into the arena.
