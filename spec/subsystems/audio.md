# Audio subsystem (mhfo-hd.dll, 32-bit)   -- WORK IN PROGRESS, updated incrementally

Confidence tags: [H] verified by code+data, [M] code read, [L] guess.

## 1. Architecture  [H unless noted]
* API: **DirectSound 8-style legacy (`dsound.dll!DirectSoundCreate`, single call site in 114db840)**. No XAudio/WinMM audio (WINMM only timeGetTime).
  Decoder: **libvorbis + libogg** (ogg.dll/vorbis.dll shipped; sync/stream/synthesis API, no vorbisfile) used in fns 114df720..114e1730.
* The engine is a **software mixer**: one DS primary buffer (set to 16-bit stereo, rate SOUND_FREQUENCY, default 44100 -> falls back to 0xAC44 if
  SetFormat mismatch) plus ONE streaming secondary buffer (flags 0x58180 = GETCURRENTPOSITION2|GLOBALFOCUS|CTRLVOLUME|CTRLPOSITIONNOTIFY|LOCDEFER..,
  size = 4 blocks * BUFFERNUM * 4 bytes, looping). `SetNotificationPositions` (IDirectSoundNotify) with one event per block; 6th event = quit.
  Mixer thread 114dac40 (priority +2) waits 15 ms on the events; each wake runs 114dad30 which, when the play cursor has advanced into the
  right quarter, calls the mix function 114db200 for the next block (BUFFERNUM frames) and copies it into the DS buffer (114dbbf0).
  So DirectSound only plays a ring of already-mixed PCM; all voice mixing, panning, envelopes, and Vorbis decoding are in game code.
* Master volume: 114dad30 re-applies `SetVolume(db100 = vol*-10000>>8)` every tick from one of 3 globals (DAT_119dd760 / DAT_1e866c8c / DAT_119dd75c)
  chosen by the focus/minimised flags (DAT_1e866c9c, DAT_1e866c98) = SOUND_VOLUME / _INACTIVITY / _MINIMIZE from mhf.ini. [M]
* mhf.ini [SOUND]: SOUND_NOTUSE (1 = skip DirectSound init: DAT_1e866c88), SOUND_VOLUME, SOUND_VOLUME_INACTIVITY, SOUND_VOLUME_MINIMIZE,
  SOUND_FREQUENCY (48000 in the sample ini; DAT_119dd754), SOUND_BUFFERNUM (2048 = frames per block; DAT_119dd758), SOUND_TYPE (1 = mono downmix flag at
  mixer+0x94: 0 stereo, 1 L+R averaged to both channels), SOUND_BGM / SOUND_SE (0..10 style user mix levels). [M for use, L for exact scale]
* Mixer state (struct at 0x1e815f10, "voice bank" array of **0x30 = 48 SE voices, stride 0x74, at +0x44b0**; **music/stream channels stride 0x630**
  at 0x1e817b7b..0x1e8187db (16 slots)). Output per block is clipped with a slow auto-limiter (gain DAT_11aa0844/48 per channel, 12-bit fixed point,
  reduced by 0x28 when |sample|>0x4fff, recovers +1 every 0x50 samples) and a feedback/decay stage (>>6 per frame, reverb-ish tail). [M]
* Voice mixing per frame: L = v*panL_table, R = v*panR_table where pan is looked up in a 1024-entry quarter sine table (VA 0x115fcd00, 256 x s16 mirrored
  4 ways) indexed by (pan byte + angle byte); volume = (a*b>>14)*c*d etc. [M]

## 2. Command layer (game logic -> sound)  [M]
* Game code never touches the mixer directly: it queues 32-byte "sound items" into a ring (114d92d0 acquire slot; 114dc0b0/114dc180/114dc210/114dc2a0/114dc920
  enqueue types) which the audio side drains on a counter (114dc830). Handler callbacks 114dc1f0/114dc280.
* `114dd030` spatial SE request: (see section 6) validates a 3-D position, rotates it into listener space, computes distance attenuation + pan, then
  starts a cue.  `114dd670` zone check returns 0/1/2 (inaudible / audible / outside listener area).
* Cue = (bank slot 0..15, program, key/note, velocity); resolved through the bank tables (section 4) by 114ddb30 and parameter-combined by 114ddc20.

## 3. Sound id -> file mapping
* Banks are loaded by name: `sprintf("sound\\%s", name)` (fmt @119a1360) with names from the pointer table at 0x11879468: `common00.snd`, `common01.snd`,
  `commonCH.snd`, `editpl.snd`, `system0.snd`, `npcairou_lob.snd`, ... (16 bank slots: DAT_1e3cbd68[slot] points to the loaded bank).
* Monster banks: fn 10b44950 builds `sound\\em%03d.snp`, `em%03dc.snp`(c = variants), `em%03dd.snp`, `em%03de.snp`, `em%03db.snp`, `em%03dce.snp`; special `em900.snp`, `em999.snd`.
  (.snp = MOMO bank for a monster; .snd = MOMO bank for everything else; 1794 of the 2130 .snd files are 0-byte placeholders.)
* Weapon / misc loose: `sound\\w%c%03d`, `sound\\wd%03d` (fn 108e05e0; id 50000+ => wd). Also bundled in `dat\wd000snd.abn` (see archive-format.md section 6).
* Music/ambience/jingle streams: `dat\sound\mus\*.mus` (762): Ogg Vorbis, either plain or EXF-wrapped (section 5).

## 4. MOMO sound bank (.snd/.snp)  [H for container, M for tables]
```
0x00 'MOMO'   u32 version (2 = .snp samples, 3 = common/other)   u32 header_size=0x40
0x0c u32 head_jkr_size   0x10 u32 head_jkr_padded  (section A at 0x40, padded to 0x80?? observed 2816 for 2738)
0x14 u32 wave_size_field (419506; section B at 0x40+head_padded; size field exceeds the padded span by <=64, treat as "up to section C")
0x18 u32 section_C_offset  0x1c u32 section_C_size  (JKR-wrapped)  ; rest of 0x40 header zero
```
* Section A (JKR type 3 -> "Head" block, 6356 B in common00). Decoded layout:
```
Head: 'Head' u32 0x20 u32 ver=2 u32 total_size u32 pcm_total(0x79ac74=7.97MB decoded PCM bytes) u32 prog_off u32 smpl_off u32 vagi_off
Prog: 'Prog' u32 size u32 max_prog  u32 prog_off[max_prog+1] (-1 = absent)  -> each program: tone records of 0x0e bytes
      tone: +2 keylo +3 keyhi (cue is valid when keylo<=note<=keyhi), +0xc u16 sample index (114ddb30)
Smpl: 'Smpl' u32 size u32 count  u32 -1 ; records 0x0c bytes at +0x10: ... +10 u16 vagi index  (114ddb30)
Vagi: 'Vagi' u32 size u32 count u32 -1 ; records 0x14 bytes at +0x10: u32 pcm_offset, u32 pcm_size(bytes?), u32 0, u32 0, u16 0, u16 sample_rate (0xBB80=48000)
```
  Names (Head/Prog/Smpl/Vagi/DROPED @119aa260) are PS2 SPU-ish (VAG), but data are Vorbis; offsets index a *decoded PCM* address space.
* Section B: Ogg-Vorbis stream(s) with rewritten/stripped page headers (first bytes: 8x00, `5f 30 00 00`, `01 00 00 00`, then garbled Ogg page header, then
  `03 'vorbis'` comment header with "Xiph.Org libVorbis I ... 20051117"; real `OggS` pages occur later (first at +0x254 of section)). [M] Exact framing unresolved.
* Section C (JKR type 3, 6160 B decoded): begins `'dbsT' u32 0x10 u32 0x1800 u32 0xc0 u32 2 ...` then 0x20-byte-ish records (`00 00 00 69 00 05 3e 0a 03 05 05 50 40 ...`):
  per-cue parameter table (key, pan, volume, priority, ADSR bytes) consumed by 114ddc20/114dc9e0. [L]
* Cue parameter assembly 114ddc20 (output 0x14 B record): vol = vol_cue*prog_vol/0x7f*tone_vol/0x7f ; pan = clamp(base+prog+tone offsets, +-0x40)+0x40 ;
  pitch(cents-ish *100 + fine) = sum of (key-offset terms) ; plus sample index and pcm offset/size. [M]

## 5. EXF (`exf\x1a`) .mus  [H -- SOLVED, round-trip verified on all 538 files: every decrypted file is a CRC-valid Ogg page chain to EOF]
```
0 'exf\x1a'  4 u16 version(0..4)  6 u16 name check (only version>=4: ~hash(lowercase basename)>>7, not needed to decrypt)  8 u32 0  12 u32 seed
16.. payload (same length as Ogg)
key(16 bytes): s=seed; repeat 4: s = mul*s + inc (u32);  word = s ^ seed     (mul,inc table @0x115fccb8: v0=(0x4a4b522e,1) v1..3=(0x10dcd,1) v4=(0x2e90edd,3))
for payload byte i (0-based), c = cipher:  x=(c^i)&0xff; hi=x>>4; lo=x&15
   plain = ((K[i&15]^hi)&15)<<4 | (((K[hi]>>4)^lo)&15)       (decrypt callback = fn 114d9e30; i = file_pos-0x10)
```
Counts: 453 version 4, 58 version 0, 27 version 1. Decrypted data is standard Ogg Vorbis (48 kHz stereo, start of file after exf header = `OggS`).
Tool: `tools\mhf_exf.py exf in.mus out.ogg`. The game streams through a 0x2800-byte block cache (114d96a0/114d97b0) and exposes ov-style read/seek callbacks
(114d9b00/114d9b50 for in-memory, 114d9e30/114da0a0 for EXF files).  Plaintext .mus (223) skip the cipher (magic test in 114d9c70).

## 6. Spatial SE request 114dd030  [M]  (see jsonl notes)

## 7. Open questions
* Q-A: MOMO section B exact framing/stripped Ogg header; Vagi pcm_offset units (decoded PCM vs stream).  * Q-B: Section C semantics.
* Q-C: SOUND_BGM / SOUND_SE scale; SE id numbering (common00 cue ids); .gab (320 files, outside dat\sound, not audio per se?).
