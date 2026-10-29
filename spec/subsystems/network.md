# Network subsystem (MHF-Z client, mhfo-hd.dll)

Status: first version, 2026-10-14. Sources: decomp\*.c, DLL .data strings, Erupe (github.com/Mezeporta/Erupe network/ package; docs/network_protocol.md does not exist in the repo, the protocol is documented in code: `network/crypt_conn.go`, `crypt_packet.go`, `crypto/crypto.go`, `packetid.go`).
Confidence tags: [H] verified in decomp/binary, [M] inferred, [L] guess.

## 0. Key discovery: the DLL carries its own function names
Almost every network function begins with `mov esi, <char* name>; call 114ea090` (**trace_func_enter**; `114ea000` = trace_func_exit, 936 / 1266 callers). The ESI string is the ORIGINAL function name (e.g. `CSync_man::putReceive_gacha_item`). 600 of 603 callers resolve (script: read 80 bytes before the call; the string lives in .data 0x1199xxxx-0x119bxxxx). These tracers are a ring buffer (`DAT_1e3d7410`, 0x108-byte entries, 1024 entries) of enter/exit events with a call-depth counter `DAT_1e8182e8`. Because the same trick likely exists in other subsystems (936 callers total), other agents can reuse it: for any function calling `114ea090`, the name is the C string pointed to by the nearest preceding `BE imm32` (mov esi). Names are written to analysis\claude_names\s_network.jsonl for all 600. [H]

Classes recovered (all prefixed C): CAsock_man/CAsock_sys (sockets), CServer_log, CEntrance_terminal, CLobby_terminal, CMessage_man (framing+crypto), CCast_man, CAcknowledge_man, CSync_man (message builders put*/handlers exe*), CPobj_man/CPobj_sys (player objects), CUser_info_man, CUser_man. Also `write_message_code` (x8), `encode_binary8`/`decode_binary8`/`calc_binary_sum32`/`calc_binary_sum16`, `Build_server_info`.

## 1. Architecture (layers, bottom to top)
1. **Winsock use** (ws2_32 imported by ordinal; decomp shows EXTERNAL:0000xxxx). `WSAStartup(2.0)` in `1153b2f0 network_init` (called from `1158f870`<-`114d6600`); `WSACleanup` in `1153b490`. [H]
2. **CAsock_man** (`114e3d10`..`114e4e10`): non-blocking TCP "async socket" object, 0xC0 bytes, vtable `PTR_FUN_119aa564`. Created by `114e3dd0`; `114e3f10 InitTcp` makes `socket(AF_INET,SOCK_STREAM)` + `ioctlsocket(FIONBIO)`. Driven by `114e4350 Execute` which polls once per frame via `select()` (`114e41e0 Update_event`) then steps up to five independent sub-state machines: connect (+0x1c), recv (+0x20), send (+0x24), close (+0x28), listen (+0x2c). Each machine: 0 idle, 1 requested, 2 in progress, 3 done (fire callback), 4 error (-> `114e3d70` reset). Callbacks stored at +0x68 (connect done), +0x6c (recv done), +0x70 (send done), +0x74 (close), +0x78 (error). Socket fd at +0x30, sockaddr_in at +0x34, ready-flags at +0x5c (bit0 readable/conn, bit1 read, bit2 write), error code +0x62 (1 select-error, 2 send, 3 recv, 4 recv-eof, 5 overflow) with WSA errno at +0x64. Connect retries: +0xa8 = 3 tries, 0xb0 = 4 (ticks) between, timer `DAT_1e8e6440` (frame counter). API: `Connect(114e4420: ip, port, cb)`, `Send(114e48c0: buf,len,cb,ctx)`, `Recv(114e4a90: buf, minLen/0, maxLen, cb, ctx)`, `Close(114e4bb0)`. Bytes sent are accumulated in a per-second table `DAT_1e8e6494[...]` under a critical section (bandwidth stats). [H]
3. **CMessage_man** (`114eb1b0`..`114ec5c0`): packet framing, 2 send buffers (0x40000 bytes... double buffered, `+0x330/+0x334`) and 2 recv buffers (`+0x340/+0x344`, 0x31000 max body `+0xe2354`). Detail in section 2. [H]
4. **CEntrance_terminal** (`114e5c00` init, `114e5ee0` execute, `114e5fa0` send_message, `114e6650` recv_binary): talks to the Entrance server (login/server list). **CLobby_terminal** (`114eabe0` init, `114eaf50` execute): the Sign/Channel (game) server link; owns a CMessage_man and CSync_man. Object instances are indexed by `DAT_1e8182f0` (slot) with strides 0x3ad90 (lobby terminal at `DAT_1e8e68b0`) and 0xeb640 (sync/ack block at `DAT_1e9c8cac`). [M]
5. **CSync_man** (`114ecd10` init, `114ece30 Analize_execute`): message-level layer. `put*` builders write requests into the CMessage_man send buffer (cursor at param_2+0x14); `exe*` handlers consume server pushes via the dispatch table. **CAcknowledge_man** allocates request handles and stores results so game code can poll.
6. Game code calls the 36 "wrapper" functions (`10xxxxxx`/`113xxxxx`) or the `put*` methods directly, later polls ack results with `CAcknowledge_man::Get_result` (`114ed240/114ed300`) / `Get_result_size` and consumes them in ~175 `Return_handle` result parsers (`1150e770`...`1158xxxx`, one per request type).

Separate from the game protocol, two **HTTP clients** exist (web API; not Erupe's game protocol): (a) `11593950`/`11594510` GET `/v1/%s%s%s%s` HTTP/1.1 non-blocking client with chunked-transfer decode (callers `104a04b0`,`104a2ab0`,`11594a80`,`11594bd0`); status code 0x123 (291) sets a global flag `*(DAT_1e879dfc+0x14)=1` (maintenance/stop). (b) `10341a00`/`10341ab0`/`10342230` blocking multipart/form-data POST client (caller `10342aa0`) with `std::string`s. A third WSAStartup(1.2) at `115877b0` belongs to a further module (`11587740`, `11587780`). [M]

## 2. Wire format (game protocol) [H unless noted]
### 2.1 Connection preamble
`CEntrance_terminal::Execute` (`114e5ee0`) state machine: 0 connect(host, port) -> 1 when connected send **8 zero bytes** (init "ping", matches Erupe) -> 2 wait send done -> 3 `Execute_send_message` -> 4 `Execute_recv_binary`. Host string `DAT_1e552650` ("host[:port]", parsed by `1150ba40` + `114ea140`).
Entrance request body is the text command: `"LOG\0"` + `"ALL+\0"` etc. (`DAT_119aa6f0` = "LOG\0ALL+\0\0\0\0\0Build_se..."; `ALL+` = list all servers; the client also appends a user-info block, `Build_user_info`, with up to N 4-byte ids: u16 count BE followed by u32 BE ids at `+0xe2c0c` stride 8). Entrance replies: a binary with magic `'USR'` ... `"SV2"`/`"SVR"` tags (strcmp at `119aa604/608`) containing a server list, plus `"end of log"` terminated log lines (`CServer_log`, up to 0x200 entries of 0xa10 bytes). Reply parsing `114e6160` (decode_binary8 + checksum32 + 'SV2'/'SVR' + per-server entries via `114e5880`/`114e54f0`) and `114e6400` ('USR' + counts). The entrance replies use `encode_binary8/decode_binary8` + `calc_binary_sum32/16` (see 2.4). [M]

### 2.2 Packet header (14 bytes, big-endian) - identical to Erupe `CryptPacketHeader`
```
+0  u8  Pf0        low nibble = mode (3 when encrypted game packets; 'bVar9' 0 = terminate); high nibble = bits 16-19 of body length
+1  u8  KeyRotDelta  non-zero => new key = (key+1)*delta (updates keyrot, also resets prev-check when mode<2)
+2  u16 PacketNum   running counter (CMessage_man+0x10 on send; compared against +0xc on receive)
+4  u16 DataSize    low 16 bits of body length; full length = ((Pf0&0xF0)<<12) | DataSize
+6  u16 PrevPacketCombinedCheck  = Check0 of the previous packet in the same direction (stored at obj+0x1e send / +0x1c recv)
+8  u16 Check0   (= "combined" check = low16(acc1 + (acc0>>1)... see 2.3)
+10 u16 Check1
+12 u16 Check2
```
Send path: `114ebb80 CMessage_man::Send` fills this (Pf0 = `((len>>12)&0xf3)|3`, KeyRotDelta = 0 normally; every 13th send (`+0x28 % 13 == 0`) a pseudo-random delta `((counter>>3) % 251)+1` is chosen and send key `+0x24 = (key+1)*delta`), then double-buffers and `114ebdc0 kick_send_data` posts it to CAsock_man::Send. Receive: `114ec0f0 kick_recv_head` posts a 14-byte Recv; `114ec1f0 kick_recv_data` parses the header, then posts a Recv for the body; `114ec440 kick_recv_next` decrypts (`114eb410`), verifies Check0/1/2 against header (mismatch => abort connection: sets flag +0xa, callback +0xe23a4), advances double buffer and calls handler `+0xe239c`. Initial keyrot (both directions) = `0xF2F2D` = **995117** (`114eb1b0`, offsets +0x20 recv, +0x24 send). Max body 0x31000.

### 2.3 Cipher and checks (matches Erupe crypto.Crypto) [H structure]
Encrypt `114eb340` (per packet body, registers: keyrot byte, table object, buffer, length, out[4] checks):
```
derived = ((keyrot & 0xFF) + 1) * len          ; u32, wraps
prev = 1; acc0=acc1=acc2=0
for i in 0..len-1:
    p   = buf[i]
    idx = (p ^ (derived >> 10)) & 0xFF
    derived = (derived + 1) * 0x4FD            ; == 1277*derived + 1277
    k   = ENC[idx]                             ; table at obj+0x2C   (256 B)
    acc2 += prev * p ; acc1 += idx ; acc0 += k << (i & 7)
    buf[i] = SHARED[prev] ^ k                  ; table at obj+0x22C  (256 B)
    prev = p
check[0] = low16( (acc2>>2) + (acc0>>1) + acc1 )      ; header Check0 (also stored as "previous combined check")
check[1] = hi16(acc0)^lo16(acc0); check[2] = hi16(acc1)^lo16(acc1); check[3] = hi16(acc2)^lo16(acc2)
```
(header Check0/1/2 = check[0..2] in the order stored at header +8/+10/+12; exact lane order should be re-verified against `114ebb80`: it stores local_118[1],[2],[3] after local_118[0] goes to the next packet's PrevPacketCombinedCheck, i.e. header +6 = previous check[0], +8 = check[1], +10 = check[2], +12 = check[3].) Decrypt `114eb410` is the inverse (table DEC from the same init). The key rotation per packet: when KeyRotDelta != 0 `keyrot = (keyrot + 1) * delta` (recv `+0x20`, send `+0x24`), both start at 0xF2F2D (995117). Server-side Erupe derives the byte as `((rotKey>>1) % 999983) & 0xFF`, consistent with `(keyrot&0xFF)` here after the client's own rotation scheme; verify when implementing.
The three 256-byte tables are generated by `114eb4e0` (1463 B) from the string `"I want 2 fly high"` at `0x119aac58` (swap shuffle indexed with %0xFB, %0x13 constants) - they equal Erupe's `_encryptKey/_decryptKey/_sharedCryptKey`. Mode field Pf0 low nibble: 3 = encrypted, <2 resets the key chain (`+0x32c`, `+0x32d` flags).
### 2.4 Entrance/legacy binary blobs
`encode_binary8 (114ea220)`: LCG `x = x*0xd433+1`, `b ^= (x>>13) ^ DAT_115f9530[i&7]`. `decode_binary8 (114ea2b0)` inverse. Checksums `calc_binary_sum32 (114ea340)` (4 lanes, tables `DAT_115f9538[%7]`, `DAT_115f9540[%9]`, result htonl) and `calc_binary_sum16 (114ea430)` (2 lanes). Used on Entrance replies. [H]

### 2.5 Message layer (inside the decrypted body)
Body = back-to-back messages, ending with opcode 0x10 (MSG_SYS_END) or 0x00. Each message starts with a **u16 BE opcode** (same numbering as Erupe `packetid.go`). `Analize_execute (114ece30)` reads byte0 (always 0 for opcodes < 0x100), byte1 = code; if code == 0x0F (MSG_SYS_EXTEND_THRESHOLD) the real opcode is the u16 BE at +2 and the payload starts at +4; otherwise payload at +2. Examples observed in builders: opcode 0x9F -> `00 9F`; opcode 0x137 -> `00 0F 01 37`. Dispatch is `table[code](payload)`; a handler returns the pointer to the next message (null ends the body).
Request messages (client->server) carry a **u32 BE AckHandle** right after the opcode (from `CAcknowledge_man::Issue_handle 114ecfe0(opcode, argA, argB)`, which fills a 0x14-byte slot `{opcode, u16 flag 0x1000, argB, argA}` in a 512-entry table), then big-endian payload fields; the builder writes bytes individually. The reply is **MSG_SYS_ACK (0x12)**: `[u32 handle][u8 isBuffer][u8 errorCode][u16 size, 0xFFFF => u32 size][data]`, handled by `exeAck 11501860` -> `Set_result 114ed0b0` (scalar) or `114ed160` (buffer); game code later polls `Get_result 114ed240/114ed300`, `Get_result_size 114ed400/114ed4c0` and `Return_handle` (~175 per-request result parsers at `1150e770`-`1158xxxx`). [H]
## 3. Dispatch table (server -> client) [H]
Base `0x119de090`, 432 dword entries indexed directly by opcode (0x000-0x1AF); default entry `115011c0 CSync_man::noImplement` (407 entries). A second table immediately after (at `0x119de750`) holds name strings `"MSG_..."` (528 pointers, 0..0x20F; note this client's list shows reserveXXX names after 0x1A1 but the put builders use Erupe's 0x1A2/0x1A3/0x1A5 opcodes, so the name table is just stale; Erupe names are correct for the builders). Only 25 opcodes have real handlers:
- 0x10 END `11501350`, 0x11 NOP `11501450`, 0x12 ACK `11501860`, 0x16 SET_STATUS `11501bd0`, 0x17 PING `11502410`, 0x1A TIME `11501580`, 0x1B CASTED_BINARY `115021a0`, 0x1F ECHO `11502270`, 0x21 STAGE_DESTRUCT `11504370`, 0x3F NOTIFY_REGISTER `115063b0`
- objects: 0x41 DELETE_OBJECT `11502d20`, 0x42 POSITION_OBJECT `11502f50`, 0x43 ROTATE `11503040`, 0x44 DUPLICATE `115030f0`, 0x45 SET_OBJECT_BINARY `11503930`, 0x46 GET_OBJECT_BINARY `115039d0`, 0x47 GET_OBJECT_OWNER `11503ac0`, 0x48 UPDATE_OBJECT_BINARY `11503b70`, 0x49 CLEANUP_OBJECT `11503240`
- users: 0x50 INSERT_USER `11504920`, 0x51 DELETE_USER `115049e0`, 0x54 NOTIFY_USER_BINARY `11504cc0`, 0x58 UPDATE_RIGHT `115059f0`, 0x59 AUTH_QUERY `114f1450` (unnamed), 0x5B AUTH_TERMINAL `11506060`.
All MHF_* opcodes (0x60+) are request/ACK only: the server answers with MSG_SYS_ACK, never a distinct opcode. SYS_LOGIN (0x14), CAST_BINARY, ENTER_STAGE etc. are request builders only. [H]

## 4. Request builders (client -> server)
Each `CSync_man::putXxx` has signature `void __thiscall put(int* outHandle, SendCursorHolder* c /*+0x14 = write ptr*/, ...args)`; it zeroes `*outHandle`, calls `Issue_handle`, writes opcode+handle+args at the cursor, advances the cursor, and returns the handle in `*outHandle`. 301 distinct call sites of `114ecfe0` (265 `put*` methods in `114f1xxx`-`11505xxx`, the rest are game-side wrappers). Table (opcode, name, builder address, dispatch entry) is generated below.


### Opcode -> builder / handler table

| Opcode | MSG name (Erupe/client) | Request builder (client->server) | Recv dispatch entry (server->client) |
|---|---|---|---|
| 0x010 | SYS_END |  | `11501350` CSync_man::exeEnd |
| 0x011 | SYS_NOP |  | `11501450` CSync_man::exeNop |
| 0x012 | SYS_ACK |  | `11501860` CSync_man::exeAck |
| 0x013 | SYS_TERMINAL_LOG | `11505b50` |  |
| 0x014 | SYS_LOGIN | `11501970` |  |
| 0x016 | SYS_SET_STATUS |  | `11501bd0` CSync_man::exeSet_status |
| 0x017 | SYS_PING | `11502310` | `11502410` CSync_man::exePing |
| 0x01A | SYS_TIME |  | `11501580` CSync_man::exeTime |
| 0x01B | SYS_CASTED_BINARY |  | `115021a0` CSync_man::exeCasted_binary |
| 0x01C | SYS_GET_FILE | `11501c30`, `11501db0` |  |
| 0x01D | SYS_ISSUE_LOGKEY | `11505dd0` |  |
| 0x01E | SYS_RECORD_LOG | `11505ef0` |  |
| 0x01F | SYS_ECHO |  | `11502270` CSync_man::exeEcho |
| 0x020 | SYS_CREATE_STAGE | `115032a0` |  |
| 0x021 | SYS_STAGE_DESTRUCT |  | `11504370` CSync_man::exeStage_destruct |
| 0x022 | SYS_ENTER_STAGE | `11503420` |  |
| 0x023 | SYS_BACK_STAGE | `115035b0` |  |
| 0x024 | SYS_MOVE_STAGE | `115036b0` |  |
| 0x026 | SYS_LOCK_STAGE | `11503f50` |  |
| 0x028 | SYS_RESERVE_STAGE | `11504160` |  |
| 0x02B | SYS_WAIT_STAGE_BINARY | `115046a0` |  |
| 0x02D | SYS_GET_STAGE_BINARY | `11504520` |  |
| 0x02E | SYS_ENUMERATE_CLIENT | `11503c50` |  |
| 0x02F | SYS_ENUMERATE_STAGE | `11503dd0` |  |
| 0x035 | SYS_CREATE_SEMAPHORE | `11502550` |  |
| 0x036 | SYS_CREATE_ACQUIRE_SEMAPHORE | `115026d0` |  |
| 0x038 | SYS_ACQUIRE_SEMAPHORE | `11502920` |  |
| 0x03A | SYS_LOCK_GLOBAL_SEMA | `114f0b60` |  |
| 0x03B | SYS_UNLOCK_GLOBAL_SEMA | `114f0d10` |  |
| 0x03C | SYS_CHECK_SEMAPHORE | `11506430` |  |
| 0x03D | SYS_OPERATE_REGISTER | `11506110` |  |
| 0x03E | SYS_LOAD_REGISTER | `11506270` |  |
| 0x03F | SYS_NOTIFY_REGISTER |  | `115063b0` CSync_man::exeNotify_register |
| 0x040 | SYS_CREATE_OBJECT | `11502b60` |  |
| 0x041 | SYS_DELETE_OBJECT |  | `11502d20` CSync_man::exeDelete_object |
| 0x042 | SYS_POSITION_OBJECT |  | `11502f50` CSync_man::exePosition_object |
| 0x043 | SYS_ROTATE_OBJECT |  | `11503040` CSync_man::exeRotate_object |
| 0x044 | SYS_DUPLICATE_OBJECT |  | `115030f0` CSync_man::exeDuplicate_object |
| 0x045 | SYS_SET_OBJECT_BINARY |  | `11503930` CSync_man::exeSet_object_binary |
| 0x046 | SYS_GET_OBJECT_BINARY |  | `115039d0` CSync_man::exeGet_object_binary |
| 0x047 | SYS_GET_OBJECT_OWNER |  | `11503ac0` CSync_man::exeGet_object_owner |
| 0x048 | SYS_UPDATE_OBJECT_BINARY |  | `11503b70` CSync_man::exeUpdate_object_binary |
| 0x049 | SYS_CLEANUP_OBJECT |  | `11503240` CSync_man::exeCleanup_object |
| 0x050 | SYS_INSERT_USER |  | `11504920` CSync_man::exeInsert_user |
| 0x051 | SYS_DELETE_USER |  | `115049e0` CSync_man::exeDelete_user |
| 0x053 | SYS_GET_USER_BINARY | `11504b90` |  |
| 0x054 | SYS_NOTIFY_USER_BINARY |  | `11504cc0` CSync_man::exeNotify_user_binary |
| 0x058 | SYS_UPDATE_RIGHT |  | `115059f0` CSync_man::exeUpdate_right |
| 0x059 | SYS_AUTH_QUERY |  | `114f1450`  |
| 0x05B | SYS_AUTH_TERMINAL |  | `11506060` CSync_man::exeAuth_terminal |
| 0x05D | SYS_RIGHTS_RELOAD | `114f4a90` |  |
| 0x060 | MHF_SAVEDATA | `11504d40` |  |
| 0x061 | MHF_LOADDATA | `11505080` |  |
| 0x062 | MHF_LIST_MEMBER | `115056b0` |  |
| 0x064 | MHF_ENUMERATE_DIST_ITEM | `114f6650` |  |
| 0x065 | MHF_APPLY_DIST_ITEM | `114f6780` |  |
| 0x066 | MHF_ACQUIRE_DIST_ITEM | `114f6900` |  |
| 0x067 | MHF_GET_DIST_DESCRIPTION | `114f6a30` |  |
| 0x068 | MHF_SEND_MAIL | `11505510` |  |
| 0x069 | MHF_READ_MAIL | `115052b0` |  |
| 0x06A | MHF_LIST_MAIL | `11505190` |  |
| 0x06B | MHF_OPRT_MAIL | `115053d0` |  |
| 0x06C | MHF_LOAD_FAVORITE_QUEST | `114f6b60` |  |
| 0x06D | MHF_SAVE_FAVORITE_QUEST | `114f6c70` |  |
| 0x06E | MHF_REGISTER_EVENT | `114f4810` |  |
| 0x06F | MHF_RELEASE_EVENT | `114f4960` |  |
| 0x070 | MHF_TRANSIT_MESSAGE | `115057c0` |  |
| 0x07F | MHF_PRESENT_BOX | `1034af00`, `105ca800` |  |
| 0x082 | MHF_ANNOUNCE | `114fbfa0` |  |
| 0x08D | MHF_CARAVAN_MY_SCORE | `1034ad30`, `1034ada0` |  |
| 0x08E | MHF_CARAVAN_RANKING | `1034ae90` |  |
| 0x08F | MHF_CARAVAN_MY_RANK | `1034ae10` |  |
| 0x090 | MHF_CREATE_GUILD | `114ee700` |  |
| 0x091 | MHF_OPERATE_GUILD | `114eeca0` |  |
| 0x092 | MHF_OPERATE_GUILD_MEMBER | `114eee60` |  |
| 0x093 | MHF_INFO_GUILD | `114eeb70` |  |
| 0x094 | MHF_ENUMERATE_GUILD | `114ee870` |  |
| 0x096 | MHF_ARRANGE_GUILD_MEMBER | `114eefc0` |  |
| 0x097 | MHF_ENUMERATE_GUILD_MEMBER | `114eea20` |  |
| 0x098 | MHF_ENUMERATE_CAMPAIGN | `114ef250` |  |
| 0x099 | MHF_STATE_CAMPAIGN | `114ef8b0` |  |
| 0x09A | MHF_APPLY_CAMPAIGN | `114ef740` |  |
| 0x09B | MHF_ENUMERATE_ITEM | `114ef370` |  |
| 0x09C | MHF_ACQUIRE_ITEM | `114ef4b0` |  |
| 0x09D | MHF_TRANSFER_ITEM | `114ef600` |  |
| 0x09E | MHF_MERCENARY_HUNTDATA | `114f3e00`, `114f3f10` |  |
| 0x09F | MHF_ENTRY_ROOKIE_GUILD | `114f2390`, `114f24b0` |  |
| 0x0A0 | MHF_ENUMERATE_QUEST | `114ef9e0` |  |
| 0x0A1 | MHF_ENUMERATE_EVENT | `114ef130` |  |
| 0x0A2 | MHF_ENUMERATE_PRICE | `114f10c0` |  |
| 0x0A3 | MHF_ENUMERATE_RANKING | `114f11e0` |  |
| 0x0A4 | MHF_ENUMERATE_ORDER | `114f1300` |  |
| 0x0A5 | MHF_ENUMERATE_SHOP | `114f6390` |  |
| 0x0A7 | MHF_UPDATE_INTERIOR | `114efe60` |  |
| 0x0A8 | MHF_ENUMERATE_HOUSE | `114efb30` |  |
| 0x0A9 | MHF_UPDATE_HOUSE | `114efcd0` |  |
| 0x0AA | MHF_LOAD_HOUSE | `114f0000` |  |
| 0x0AB | MHF_OPERATE_WAREHOUSE | `114f32d0` |  |
| 0x0AC | MHF_ENUMERATE_WAREHOUSE | `114f2df0` |  |
| 0x0AD | MHF_UPDATE_WAREHOUSE | `114f2f10` |  |
| 0x0AE | MHF_ACQUIRE_TITLE | `114f2b60` |  |
| 0x0AF | MHF_ENUMERATE_TITLE | `114f2cc0` |  |
| 0x0B0 | MHF_ENUMERATE_GUILD_ITEM | `114f05f0` |  |
| 0x0B1 | MHF_UPDATE_GUILD_ITEM | `114f0720` |  |
| 0x0B2 | MHF_ENUMERATE_UNION_ITEM | `114f0e10` |  |
| 0x0B3 | MHF_UPDATE_UNION_ITEM | `114f0f20` |  |
| 0x0B4 | MHF_CREATE_JOINT | `114f1f60` |  |
| 0x0B5 | MHF_OPERATE_JOINT | `114f20e0` |  |
| 0x0B6 | MHF_INFO_JOINT | `114f2250` |  |
| 0x0B7 | MHF_UPDATE_GUILD_ICON | `114f25e0` |  |
| 0x0B8 | MHF_INFO_FESTA | `114f14c0` |  |
| 0x0B9 | MHF_ENTRY_FESTA | `114f15e0` |  |
| 0x0BA | MHF_CHARGE_FESTA | `114f1730` |  |
| 0x0BB | MHF_ACQUIRE_FESTA | `114f18b0` |  |
| 0x0BC | MHF_STATE_FESTA_U | `114f1a00` |  |
| 0x0BD | MHF_STATE_FESTA_G | `114f1b50` |  |
| 0x0BE | MHF_ENUMERATE_FESTA_MEMBER | `114f1ca0` |  |
| 0x0BF | MHF_VOTE_FESTA | `114f1df0` |  |
| 0x0C0 | MHF_ACQUIRE_CAFE_ITEM | `114f27b0` |  |
| 0x0C1 | MHF_UPDATE_CAFEPOINT | `114f2a40` |  |
| 0x0C2 | MHF_CHECK_DAILY_CAFEPOINT | `114f2910` |  |
| 0x0C4 | MHF_CHECK_MONTHLY_ITEM | `114f35b0` |  |
| 0x0C5 | MHF_ACQUIRE_MONTHLY_ITEM | `114f3460` |  |
| 0x0C6 | MHF_CHECK_WEEKLY_STAMP | `114f46e0` |  |
| 0x0C7 | MHF_EXCHANGE_WEEKLY_STAMP | `114f45c0` |  |
| 0x0C8 | MHF_CREATE_MERCENARY | `114f36d0` |  |
| 0x0C9 | MHF_SAVE_MERCENARY | `114f37e0` |  |
| 0x0CA | MHF_READ_MERCENARY_W | `114f3930` |  |
| 0x0CB | MHF_READ_MERCENARY_M | `114f3a50` |  |
| 0x0CC | MHF_CONTRACT_MERCENARY | `114f3ba0` |  |
| 0x0CD | MHF_ENUMERATE_MERCENARY_LOG | `114f3cf0` |  |
| 0x0CE | MHF_ENUMERATE_GUACOT | `114f01a0` |  |
| 0x0CF | MHF_UPDATE_GUACOT | `114f02c0` |  |
| 0x0D0 | MHF_INFO_TOURNAMENT | `114f4020` |  |
| 0x0D1 | MHF_ENTRY_TOURNAMENT | `114f4150` |  |
| 0x0D2 | MHF_ENTER_TOURNAMENT_QUEST | `114f4280` |  |
| 0x0D3 | MHF_ACQUIRE_TOURNAMENT | `114f4490` |  |
| 0x0D4 | MHF_GET_ACHIEVEMENT | `114f4e00` |  |
| 0x0D9 | MHF_INFO_SCENARIO_COUNTER | `114f5b30` |  |
| 0x0DA | MHF_SAVE_SCENARIO_DATA | `114f4cb0` |  |
| 0x0DB | MHF_LOAD_SCENARIO_DATA | `114f4ba0` |  |
| 0x0DC | MHF_GET_BBS_SNS_STATUS | `10341260` |  |
| 0x0DD | MHF_APPLY_BBS_ARTICLE | `103412d0` |  |
| 0x0DE | MHF_GET_ETC_POINTS | `114f50c0` |  |
| 0x0DF | MHF_UPDATE_ETC_POINT | `114f51d0` |  |
| 0x0E0 | MHF_GET_MYHOUSE_INFO | `114f52f0` |  |
| 0x0E1 | MHF_UPDATE_MYHOUSE_INFO | `114f5480` |  |
| 0x0E2 | MHF_GET_WEEKLY_SCHEDULE | `114f5830` |  |
| 0x0E3 | MHF_ENUMERATE_INV_GUILD | `114f08e0` |  |
| 0x0E4 | MHF_OPERATION_INV_GUILD | `114f0a30` |  |
| 0x0E5 | MHF_STAMPCARD_STAMP | `114f5930` |  |
| 0x0E7 | MHF_UNRESERVE_SRG | `11505910` |  |
| 0x0E8 | MHF_LOAD_PLATE_DATA | `114f5c40` |  |
| 0x0E9 | MHF_SAVE_PLATE_DATA | `114f5d50` |  |
| 0x0EA | MHF_LOAD_PLATE_BOX | `114f5ec0` |  |
| 0x0EB | MHF_SAVE_PLATE_BOX | `114f5fd0` |  |
| 0x0EC | MHF_READ_GUILDCARD | `114f6140` |  |
| 0x0ED | MHF_UPDATE_GUILDCARD | `114f6250` |  |
| 0x0EE | MHF_READ_BEAT_LEVEL | `1153d680` |  |
| 0x0EF | MHF_UPDATE_BEAT_LEVEL | `1153d9b0` |  |
| 0x0F2 | MHF_READ_LAST_WEEK_BEAT_RANKING | `1153d7a0` |  |
| 0x0F3 | MHF_ACCEPT_READ_REWARD | `1153d8b0` |  |
| 0x0F4 | MHF_GET_ADDITIONAL_BEAT_REWARD | `1153d460` |  |
| 0x0F5 | MHF_GET_FIXED_SEIBATU_RANKING_TABLE | `107ca4d0` |  |
| 0x0F6 | MHF_GET_BBS_USER_STATUS | `103411f0` |  |
| 0x0F8 | MHF_GET_BREAK_SEIBATU_LEVEL_REWARD | `1153d560` |  |
| 0x0F9 | MHF_GET_WEEKLY_SEIBATU_RANKING_REWARD | `1034acc0` |  |
| 0x0FA | MHF_GET_EARTH_STATUS | `1153c580` |  |
| 0x0FB | MHF_LOAD_PARTNER | `114f6da0` |  |
| 0x0FC | MHF_SAVE_PARTNER | `114f6eb0` |  |
| 0x0FD | MHF_GET_GUILD_MISSION_LIST | `114f6ff0` |  |
| 0x0FE | MHF_GET_GUILD_MISSION_RECORD | `114f7100` |  |
| 0x0FF | MHF_ADD_GUILD_MISSION_COUNT | `114f7210` |  |
| 0x100 | MHF_SET_GUILD_MISSION_TARGET | `114f7360` |  |
| 0x101 | MHF_CANCEL_GUILD_MISSION_TARGET | `114f7490` |  |
| 0x102 | MHF_LOAD_OTOMO_AIROU | `114f80a0` |  |
| 0x103 | MHF_SAVE_OTOMO_AIROU | `114f81b0` |  |
| 0x104 | MHF_ENUMERATE_GUILD_TRESURE | `114f82f0` |  |
| 0x105 | MHF_ENUMERATE_AIROULIST | `114f8430` |  |
| 0x106 | MHF_REGIST_GUILD_TRESURE | `114f8560` |  |
| 0x107 | MHF_ACQUIRE_GUILD_TRESURE | `114f86c0` |  |
| 0x108 | MHF_OPERATE_GUILD_TRESURE_REPORT | `114f92a0` |  |
| 0x109 | MHF_GET_GUILD_TRESURE_SOUVENIR | `114f93e0` |  |
| 0x10A | MHF_ACQUIRE_GUILD_TRESURE_SOUVENIR | `114f94f0` |  |
| 0x10B | MHF_ENUMERATE_FESTA_INTERMEDIATE_PRIZE | `114f9920` |  |
| 0x10C | MHF_ACQUIRE_FESTA_INTERMEDIATE_PRIZE | `114f9a30` |  |
| 0x10D | MHF_LOAD_DECO_MYSET | `114fa0f0` |  |
| 0x10E | MHF_SAVE_DECO_MYSET | `114fa200` |  |
| 0x110 | MHF_LOAD_GUILD_COOKING | `114f75c0` |  |
| 0x111 | MHF_REGIST_GUILD_COOKING | `114f76f0` |  |
| 0x112 | MHF_LOAD_GUILD_ADVENTURE | `114f7840` |  |
| 0x113 | MHF_REGIST_GUILD_ADVENTURE | `114f7950` |  |
| 0x114 | MHF_ACQUIRE_GUILD_ADVENTURE | `114f7aa0` |  |
| 0x115 | MHF_CHARGE_GUILD_ADVENTURE | `114f7bd0` |  |
| 0x116 | MHF_LOAD_LEGEND_DISPATCH | `114f7e90` |  |
| 0x117 | MHF_LOAD_HUNTER_NAVI | `114fa5d0` |  |
| 0x118 | MHF_SAVE_HUNTER_NAVI | `114fa6e0` |  |
| 0x119 | MHF_REGIST_SPABI_TIME | `114f7fa0` |  |
| 0x11A | MHF_GET_GUILD_WEEKLY_BONUS_MASTER | `114f9600` |  |
| 0x11B | MHF_GET_GUILD_WEEKLY_BONUS_ACTIVE_COUNT | `114f9710` |  |
| 0x11C | MHF_ADD_GUILD_WEEKLY_BONUS_EXCEPTIONAL_USER | `114f9820` |  |
| 0x11D | MHF_GET_TOWER_INFO | `11381010` |  |
| 0x11E | MHF_POST_TOWER_INFO | `10b77ee0` |  |
| 0x121 | MHF_GET_EARTH_VALUE | `11381080` |  |
| 0x123 | MHF_GET_PAPER_DATA | `107ad640` |  |
| 0x127 | MHF_POST_BOOST_TIME | `114f9da0` |  |
| 0x128 | MHF_GET_BOOST_TIME_LIMIT | `114f9ec0` |  |
| 0x12A | MHF_ENUMERATE_FESTA_PERSONAL_PRIZE | `114f9b60` |  |
| 0x12B | MHF_ACQUIRE_FESTA_PERSONAL_PRIZE | `114f9c70` |  |
| 0x12C | MHF_GET_RAND_FROM_TABLE | `114f9fd0` |  |
| 0x12D | MHF_GET_CAFE_DURATION | `114fa830` |  |
| 0x12E | MHF_GET_CAFE_DURATION_BONUS_INFO | `114fa940` |  |
| 0x12F | MHF_RECEIVE_CAFE_DURATION_BONUS | `114faa50` |  |
| 0x130 | MHF_POST_CAFE_DURATION_BONUS_RECEIVED | `114fab60` |  |
| 0x131 | MHF_GET_GACHA_POINT | `114face0` |  |
| 0x132 | MHF_USE_GACHA_POINT | `114fadf0` |  |
| 0x133 | MHF_EXCHANGE_FPOINT_2_ITEM | `114faf20` |  |
| 0x134 | MHF_EXCHANGE_ITEM_2_FPOINT | `114fb070` |  |
| 0x135 | MHF_GET_FPOINT_EXCHANGE_LIST | `114fb1c0` |  |
| 0x136 | MHF_PLAY_STEPUP_GACHA | `114fb2d0` |  |
| 0x137 | MHF_RECEIVE_GACHA_ITEM | `114fb410` |  |
| 0x138 | MHF_GET_STEPUP_STATUS | `114fb530` |  |
| 0x139 | MHF_PLAY_FREE_GACHA | `114fb670` |  |
| 0x13A | MHF_GET_TINY_BIN | `1153d5e0` |  |
| 0x13B | MHF_POST_TINY_BIN | `1153d4d0` |  |
| 0x13D | MHF_GET_GUILD_TARGET_MEMBER_NUM | `114fb790` |  |
| 0x13E | MHF_GET_BOOST_RIGHT | `114fb8d0` |  |
| 0x13F | MHF_START_BOOST_TIME | `114fb9e0` |  |
| 0x140 | MHF_POST_BOOST_TIME_QUEST_RETURN | `114fbb10` |  |
| 0x141 | MHF_GET_BOX_GACHA_INFO | `114fbc10` |  |
| 0x142 | MHF_PLAY_BOX_GACHA | `114fbd40` |  |
| 0x143 | MHF_RESET_BOX_GACHA_INFO | `114fbe80` |  |
| 0x144 | MHF_GET_SEIBATTLE | `1004a100` |  |
| 0x145 | MHF_POST_SEIBATTLE | `1004a170` |  |
| 0x146 | MHF_GET_RYOUDAMA | `10692630` |  |
| 0x147 | MHF_POST_RYOUDAMA | `106926a0` |  |
| 0x148 | MHF_GET_TENROUIRAI | `105bca10` |  |
| 0x149 | MHF_POST_TENROUIRAI | `105bca80` |  |
| 0x14A | MHF_POST_GUILD_SCOUT | `114fc110` |  |
| 0x14B | MHF_CANCEL_GUILD_SCOUT | `114fc240` |  |
| 0x14C | MHF_ANSWER_GUILD_SCOUT | `114fc370` |  |
| 0x14D | MHF_GET_GUILD_SCOUT_LIST | `114fc4b0` |  |
| 0x14E | MHF_GET_GUILD_MANAGE_RIGHT | `114fc5c0` |  |
| 0x14F | MHF_SET_GUILD_MANAGE_RIGHT | `114fc6d0` |  |
| 0x150 | MHF_PLAY_NORMAL_GACHA | `114fc810` |  |
| 0x154 | MHF_GET_GACHA_PLAY_HISTORY | `114fc950` |  |
| 0x155 | MHF_GET_REJECT_GUILD_SCOUT | `114fca80` |  |
| 0x156 | MHF_SET_REJECT_GUILD_SCOUT | `114fcb90` |  |
| 0x158 | MHF_SET_CA_ACHIEVEMENT_HIST | `114fccb0` |  |
| 0x159 | MHF_GET_KEEP_LOGIN_BOOST_STATUS | `114fce10` |  |
| 0x15A | MHF_USE_KEEP_LOGIN_BOOST | `114fcf20` |  |
| 0x15B | MHF_GET_UD_SCHEDULE | `114fd040` |  |
| 0x15C | MHF_GET_UD_INFO | `114fd150` |  |
| 0x15D | MHF_GET_KIJU_INFO | `114fd260` |  |
| 0x15E | MHF_SET_KIJU | `114fd370` |  |
| 0x15F | MHF_ADD_UD_POINT | `114fd490` |  |
| 0x160 | MHF_GET_UD_MY_POINT | `114fd5e0` |  |
| 0x161 | MHF_GET_UD_TOTAL_POINT_INFO | `114fd6f0` |  |
| 0x162 | MHF_GET_UD_BONUS_QUEST_INFO | `114fd800` |  |
| 0x163 | MHF_GET_UD_SELECTED_COLOR_INFO | `114fd910` |  |
| 0x164 | MHF_GET_UD_MONSTER_POINT | `114fda20` |  |
| 0x165 | MHF_GET_UD_DAILY_PRESENT_LIST | `114fdb30` |  |
| 0x166 | MHF_GET_UD_NORMA_PRESENT_LIST | `114fdc40` |  |
| 0x167 | MHF_GET_UD_RANKING_REWARD_LIST | `114fdd50` |  |
| 0x168 | MHF_ACQUIRE_UD_ITEM | `114fde60` |  |
| 0x169 | MHF_GET_REWARD_SONG | `114fdfc0` |  |
| 0x16A | MHF_USE_REWARD_SONG | `114fe0d0` |  |
| 0x16B | MHF_ADD_REWARD_SONG_COUNT | `114fe1e0` |  |
| 0x16C | MHF_GET_UD_RANKING | `114fe350` |  |
| 0x16D | MHF_GET_UD_MY_RANKING | `114fe470` |  |
| 0x16E | MHF_ACQUIRE_MONTHLY_REWARD | `114fe580` |  |
| 0x16F | MHF_GET_UD_GUILD_MAP_INFO | `114fe690` |  |
| 0x170 | MHF_GENERATE_UD_GUILD_MAP | `114fe7a0` |  |
| 0x171 | MHF_GET_UD_TACTICS_POINT | `114fe8b0` |  |
| 0x172 | MHF_ADD_UD_TACTICS_POINT | `114fe9c0` |  |
| 0x173 | MHF_GET_UD_TACTICS_RANKING | `114feb00` |  |
| 0x174 | MHF_GET_UD_TACTICS_REWARD_LIST | `114fec30` |  |
| 0x175 | MHF_GET_UD_TACTICS_LOG | `114fed40` |  |
| 0x176 | MHF_GET_EQUIP_SKIN_HIST | `114ff290` |  |
| 0x177 | MHF_UPDATE_EQUIP_SKIN_HIST | `114ff3a0` |  |
| 0x178 | MHF_GET_UD_TACTICS_FOLLOWER | `114fee50` |  |
| 0x179 | MHF_SET_UD_TACTICS_FOLLOWER | `114fef60` |  |
| 0x17A | MHF_GET_UD_SHOP_COIN | `114ff090` |  |
| 0x17B | MHF_USE_UD_SHOP_COIN | `114ff190` |  |
| 0x17C | MHF_GET_ENHANCED_MINIDATA | `114ff4b0` |  |
| 0x17D | MHF_SET_ENHANCED_MINIDATA | `114ff5e0` |  |
| 0x17E | MHF_SEX_CHANGER | `114ffcb0` |  |
| 0x17F | MHF_GET_LOBBY_CROWD | `11500b90` |  |
| 0x181 | MHF_GUILD_HUNTDATA | `114ff710`, `114ff850`, `114ff970` |  |
| 0x182 | MHF_ADD_KOURYOU_POINT | `115005c0` |  |
| 0x183 | MHF_GET_KOURYOU_POINT | `11500820` |  |
| 0x184 | MHF_EXCHANGE_KOURYOU_POINT | `115006f0` |  |
| 0x185 | MHF_GET_UD_TACTICS_BONUS_QUEST | `114ffa90` |  |
| 0x186 | MHF_GET_UD_TACTICS_FIRST_QUEST_BONUS | `114ffba0` |  |
| 0x187 | MHF_GET_UD_TACTICS_REMAINING_POINT | `11500930` |  |
| 0x188 | SYS_reserve188 | `11500a80` |  |
| 0x189 | MHF_LOAD_PLATE_MYSET | `114fa360` |  |
| 0x18A | MHF_SAVE_PLATE_MYSET | `114fa470` |  |
| 0x18B | SYS_reserve18B | `115010b0` |  |
| 0x18D | MHF_SET_RESTRICTION_EVENT | `11500f50` |  |
| 0x190 | MHF_GET_TREND_WEAPON | `114ffdc0` |  |
| 0x191 | MHF_UPDATE_USE_TREND_WEAPON_LOG | `114ffed0` |  |
| 0x195 | MHF_SAVE_RENGOKU_DATA | `114fffe0` |  |
| 0x196 | MHF_LOAD_RENGOKU_DATA | `11500140` |  |
| 0x197 | MHF_GET_RENGOKU_BINARY | `11500250` |  |
| 0x198 | MHF_ENUMERATE_RENGOKU_RANKING | `11500370` |  |
| 0x199 | MHF_GET_RENGOKU_RANKING_RANK | `115004b0` |  |
| 0x19A | MHF_ACQUIRE_EXCHANGE_SHOP | `114f6510` |  |
| 0x19C | MHF_SAVE_MEZFES_DATA | `11500ce0` |  |
| 0x19D | MHF_LOAD_MEZFES_DATA | `11500e40` |  |
| 0x1A2 | MHF_ENUMERATE_GUILD_MESSAGE_BOARD | `114f8800` |  |
| 0x1A3 | MHF_UPDATE_GUILD_MESSAGE_BOARD | `114f8950`, `114f8b40`, `114f8cb0`, `114f8dd0`, `114f8fc0`, `114f9120` |  |
| 0x1A5 | MHF_REGIST_GUILD_ADVENTURE_DIVA | `114f7d20` |  |
## 5. Open questions / TODO
- Bodies of individual `put*` builders (argument types per opcode) and ACK result layouts: not yet extracted; each builder is 100-500 bytes of byte stores, so a per-opcode field table can be generated mechanically (stores at `puVar1+N`). Cross-check against Erupe `network/mhfpacket/msg_*.go`.
- Confirm check-value ordering and keyrot-to-byte mapping of `114eb340` (section 2.3) by implementing against a captured session.
- Sign/login: opcodes MSG_SYS_LOGIN (0x14), ISSUE_LOGKEY, AUTH_QUERY builders: locate `put*` for 0x14 (no `put` for 0x14 was found in the 301 call sites; probably built through a different helper, e.g. `write_message_code` family `114f52f0`,`114f5830`,`11501210`,`11505910`,`1153d9b0`).
- Player-position broadcast / player data sync (other agents: `106efbd0` broadcast_player_position_packet, `107a0c50` sync_player_data_block_to_server) are game-layer producers feeding `MSG_SYS_POSITION_OBJECT`, `MSG_SYS_SET_OBJECT_BINARY` / `CAST_BINARY` ([M]).
- HTTP web clients (section 1): what the `/v1/` API serves; `0x123` status semantics.
- Entrance reply layout (`114e6160`, `114e6400`, `Build_server_info`, `SERVER_INFO::Entry_host/Entry_process` at `114e6be0`/`114e6cd0`) only partly decoded.
- Name table / stale entries after 0x1A1 (section 3).
