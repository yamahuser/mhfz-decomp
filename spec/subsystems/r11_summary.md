# Region 0x11400000-0x1159FFFF: subsystem summary (agent r11)

Names live in `analysis\claude_names\r11.jsonl`. Everything below is engine-neutral behaviour description; confidence levels are in the jsonl.

## 1. Server request/response protocol layer ("snj_*" API)
* **Packet format (client -> server):** `[u16 BE opcode][u32 BE request-id][payload...]`. Strings are length-prefixed (u8/u16) and bounded (typically <=0x20 or <=0x100 bytes); ints are big-endian.
* One *builder* function per opcode (about 280 in 0x114ee700..0x11501xxx and 0x1153cxxx..): registers a pending request (`net_request_register`, 114ecfe0) and writes the packet at the session's write cursor (session+0x14). Builders are named `net_build_req_op_XXX` or, when a wrapper identifies them, `net_build_req_snj_*`.
* **Request table** (per session, 0x200 slots): handle = (slot<<16)|generation. Records (0x14 bytes): opcode, state (1=completed), result code (0x10 pending, 0x11 invalid handle, 0x12 overflow, 0x13 timeout), received size, buffer capacity, buffer/value. Helpers: alloc 114ed8e0, release 114ed9b0, poll 114ed300 (value) / 114ed4c0 (size), complete 114ed0b0/114ed160.
* **Client wrappers** `snj_db_*` (house/guild/pig/cloth/guacot), `snj_mail_*`, `snj_search_*`, `snj_semaphore_*`, `snj_stage_*` (lobby/stage create, enter, move, reserve, lock, enumerate, binary index, password): each is a per-frame polled two-phase state machine (send, then poll with a 600-frame timeout) that keeps its own name string for logging. The session objects live at DAT_1e9c8ca0 + index*0xeb640.
* Login/session bring-up is a ~6.8 KB state machine at 11514d00 (receives character lists, XOR-obfuscates data with a per-block LCG key).
* Debug call tracing: every net function brackets itself with `trace_enter_func` / `trace_exit_func` (1024-entry ring of 0x108-byte records).

## 2. Socket layer
Non-blocking Winsock TCP client/server object (state machines per frame): connect (with retries and timeout), listen/accept, send, receive (exact length or until close), graceful shutdown, `select()` readiness bits. Objects are chained in a socket manager that is updated once per frame. A helper thread keeps a 1 Hz tick and a bandwidth histogram.

## 3. Realtime peer sync (CSync_man-like) 114e1730..114e3bd0
Small session object (<=4 peers, 0x1f8-byte datagram budget) with per-peer states (0 none, 1 joining, 3 ready, 4 running, 5 left, 6 dropped), a reliable and an unreliable outgoing queue, control messages of types 1..6 (hello, ack-peer, toggle, start, clock, clock-echo) with 4-byte `[len,type,0xff,..]` headers, latency estimation and peer time-outs.

## 4. Archive/pack layer (matches spec\archive-format.md)
* `ecd_decrypt_payload` (1158f460): LCG-driven nibble-mixing stream cipher keyed by header key index and seed; `ecd_verify_and_decrypt` (1158f510) validates with a CRC-32 of the file name for key sets >3.
* JKR decompressor (1158f240 init, 1158f310 run, step/huffman helpers 1158eec0..1158efe0): types 0 raw, 2 LZ, 3/4 Huffman+LZ.
* Pack tables: 77 `.abn` bundles (name prefix table at 0x115f4798), per-pack id range tables, `pack_read_*` sync/overlapped file reads, resolve name -> pack/id.
* Async I/O: 0x400-entry ring of 0x4c-byte tasks (state, callback, args, name) pumped by 115904c0 on the main thread plus a worker thread.

## 5. Effect / entity-node system (1140xxxx-1146axxx)
Transient game objects ("nodes") come from a pool: node allocator 11405d70 (reserves contiguous 0x200-byte work slots from a 0xA00-slot bitmap), doubly linked active list, `effect_object_free` 11405e70. A node has a kind byte (+2 low) and subtype (+2 high), variant (+3), state (+4: 0 init, 1 run, 2 end, 3 free), position (+0x28..+0x30), parameters (+0x34), owner actor (+0x38) and an update callback (+0x24). About 45 kinds exist, each with a 3-state dispatcher (`fx_kind_NN_update_dispatch`); spawners (`fx_spawn_kNN_sSS`) fill nodes from actor data. Owner actors are checked via `actor+0x7f8 == quest_ctx+0x14` (stage/quest id) and `actor+0` alive flag.

## 6. Audio
* `play_positional_se_with_attenuation_pan` (114dd030): listener-relative 3D cue start with min/max distance, a 17-point volume curve table and pan from horizontal angle, random pan/pitch jitter; cue/curve tables hang off DAT_1e77dcc4.
* Sound instance banks (DAT_1e3cbd68[bank], 0x20-byte records).
* libvorbisfile statically linked (114df6e0..114e15f0): ov_open_callbacks, ov_read, ov_pcm_seek, ov_clear etc.

## 7. UI text renderer (114de870..114df4c0)
Context DAT_1e3cbd64: per-layer (7) command lists of 0x14-byte records + string heap, dynamic glyph atlas (double-byte SJIS codes, 32x32 cells), outline pass, 16-colour palette.

## 8. Misc
* RNG: global 32-bit LFSR (taps 0x80200003) at DAT_11a9a798 for logic (1158f6a0/1158f6c0); a separate 16-bit Lehmer LCG (x*0xb0 mod 0xff53) at DAT_1ed5f2a2 for effects/visual variation.
* Anti-tamper checksum helper 1158ccb0 (seed 0x6d68661a, sub/add modes).
* Chat UI keys (CHAT_SIZE, CSMODE...), graphics option names (90C_GRAPHIC_*) and the options file loader are in 11541xxx-1154exxx and 1158d450/1158e380 (not yet analysed in depth).
* Crypto++ (NameValuePairs, BufferedTransformation, AllocatorBase) and an HTTP client (GET/Content-Length/chunked) are statically linked in 11592xxx-11595xxx.
