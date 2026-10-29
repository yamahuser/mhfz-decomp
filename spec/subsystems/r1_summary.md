# Region 0x10000000-0x101FFFFF: subsystem summary (agent r1)

Engine-neutral notes. Names are in `analysis\claude_names\r1.jsonl`. Confidence tags: [H] verified (code + disassembly/constants), [M] strong inference, [L] guess.

## 1. What the region contains (by address)
- 1000xxxx-1004xxxx: renderer core. Packed render-state filter, D3D9 state capture/restore around 2D passes, screen-space quad primitives, texture slot table, shader/light constant uploads, mesh draw, plus the **model/skeleton/animation runtime** (1000-1000a).
- 1005xxxx-100fxxxx and 1010xxxx-1016xxxx: per-monster AI modules (one contiguous block of code per species), shared helpers for effects/action nodes.
- 1017xxxx-101fxxxx: more monster AI, shared actor-state helpers (101bxxxx-101exxxx), action-node spawners (101f5xxx, 101fd5xx).
- Species id lives in actor byte +3. Blocks found (id -> first/last address of functions that gate on it): 0x67 1004b2a0-10051c80; 0x79 1005fbe0-10067100; 0x81 1006f500-1006f680; 0x8d 10082bc0-10086ad0; 0x8e 10087a20-1008f3c0; 0x99 100b2580-100b5920 and 101b6b60-101ba580; 0xa3 100e5ca0-100f98a0; 0x9f 100e7610-100f8980; 0xa4 1011b8e0-1012f870; 0x11 1019ef00-101a10e0; 0x5f 101b0890-101b63e0; 0x63 101b8d10.. (ids hex, partial list).

## 2. Model file (mesh) chunk tree [M]
All model/skeleton data is a tree of chunks `{u32 tag, u32 count_or_value, u32 byteSize_to_next}` followed by children at +0xc.
Tag (high word) meanings seen in the mesh builders (10002af0, 10002bf0, 10003190, 10003790):
- 2: list of mesh objects (count = parts); each child (tag 4 in the switch) is one mesh part.
- 5: index/strip runs. Per part: sequence of runs `u32 (len | bit31 flag)` + `len` u32 indices. Runtime form: u16 header `len | 0x4000` (flag clear) or `len | 0x8000` (flag set), optional u16 material id per run (from chunk 6 when ids differ), then u16 indices.
- 6: per-run material/texture ids (u32 each).
- 7: positions (3 f32). 8: normals (3 f32). 0xb: vertex colours (4 f32, 0-255, RGBA -> packed ARGB). 0xa: UV (2 f32).
- 0x12: 4 f32 per vertex (blend weights or tangent, unverified); 0xc: extra attribute (second UV/tangent, unverified); 5/0x5 (0x50000): u32 bone-map array per part.
- Runtime vertex strides: 0x1c (pos,normal,color), 0x24 (+UV), 0x48 (+vec4), 0x3c (extra attr). Format ids 0x25/0x35/0x4025/0x4035/0x4135. Index flags 0x21000 (+0x100000 per-run material, +0x200000 extra).
- Runtime mesh slot table: 0xb40 entries at DAT_11aa3dd8 (alloc 10007aa0); D3D vertex/index buffers created by 10007b00/10007b60. Vertex-flag helpers: 10007050 (to FVF-ish code), 100070c0 (stride).
Implication for HD models: the vertex stream is simple float data; a replacement mesh can be re-emitted into the same chunk layout. UVs are a separate chunk, so UV remapping is independent of positions.

## 3. Skeleton and animation runtime [H unless noted]
- Clip file -> runtime clip: `100018b0` (see spec\animation-format.md).
- **Key sampling (answers spec Q1/Q2):** per channel, find the segment with `track_find_segment_*` (10004820 etc.) and evaluate. For type 0x12 keys (s16 value,u16 frame,s16 tanIn,s16 tanOut) the result is a **cubic Hermite**: with u=(t-t0)/(t1-t0), dt=t1-t0: `v = h00*v0 + h01*v1 + dt*h10*tanOut0 + dt*h11*tanIn1` (tanOut of the left key at +6, tanIn of the right key at +4). Disassembly 10004120. Float key types 0x21-0x23 exist; the 0x21 path in mode 0x1000 uses plain linear interpolation (10008da0).
- **Units:** track flag 0x2000 = fixed-point: rotation channels (slots 3..5) are multiplied by 0.00038349520 = **2*pi/16384** (16384 units per turn, NOT 65536); every other channel (scale/translation) by **0.0625 (1/16)**. Flag 0x1000 = already float. (10009ed0, 10008da0, constants DAT_119b6810 / DAT_119b6078.)
- Channel slots per bone: 0-2 scale xyz, 3-5 Euler rotation, 6-8 translation. Local matrix = Scaling(s) then Euler rotation (10004f80) then translation in the 4th row.
- **Skeleton runtime node** (array stride 0x1c0, up to ~0x76 nodes; this array is the "part matrix table" at model resource +0x24 used by effect attachment code): +0x00 world matrix (translation at +0x30..0x38), +0x40 local matrix, +0x80 inverse-bind/skin matrix, +0xc4 shader slot id, +0xc6 bone index, +0xc8 parent ptr, +0xcc next sibling ptr, +0xd0 first child ptr, +0xd4 track base, +0xd8 track offset, +0xdc..0x100 bind channel block (10 floats), +0x104..0x128 current channels, +0x17c next sibling index, +0x17e first child index, +0x180 final skin matrix. Built by 10009640 from skeleton records (0x40 bytes each at skeleton chunk +0x10; chunk +2 = bone count).
- Pose per frame: `100083d0` (recursive: copy bind->current, sample track, rebuild local matrix 10009a20), then `100092a0` (world matrices, iterative, with parent-scale compensation) -> `10008970`/`10008b20` upload skin matrices as shader constant blocks (id = slot + 0x1a, palette DAT_1dcd2060 stride 0x40). Cross-fade between two clips: `10008670` weighted sum of channels.
- Actor-level motion start is `1084fe60` (outside region): per-species motion table, record stride 0xc; motion records fetched by `111a5080` (stride 0x28, id + bank*200).

## 4. Renderer state machine [H]
- Packed render state: DAT_11b7fe20 (current), DAT_11b8c658 (cached) -> `1000bec0` issues only changed D3D9 SetRenderState/SetTextureStageState; `1000b3c0` handles the masked groups; `1000c7d0` (3394 callers) = set option + flush.
- 2D passes bracket: `10010d50` captures state (render states 0x89,0x1c,0x16, textures stage0/1) and picks a pixel shader; `10011060` restores. All screen-space primitives (1000da40 rect, 1000dec0 coloured quad, 1000e800 textured quad, 1000e1a0 gradient quad, 1000f1d0 slot-texture rect) use pretransformed vertices and DrawPrimitiveUP.
- Singletons: DAT_1e73d3c0 (0x210 render helper, ctor 10029cb0), DAT_1e73d3bc (0x550 effect helper, ctor 10025810), DAT_1e73d3b8 (0x2e1c manager, ctor 1001f650).
- Shader pack: file index 9 (JKR) loaded by `100121b0`, creating vertex declarations + vertex shaders for the pass table.
- Texture slot table DAT_11aa7d80 (stride 0xd8; width/height cached by 10011af0); mesh slots DAT_11aa3dd8.

## 5. Actor/monster model (what the AI code touches) [M]
Actor record fields recurring across AI code: +3 species id; +5 step within action; +0x14 action id; +0x15 action group; +0xa4 yaw (u16, 0x10000 = 360 deg; angle*2pi/65536 conversion constants DAT_119b5f1c*DAT_119b5f34); +0xac/+0xb0/+0xb4 position; +0xb20 playback speed multiplier (default 1.0); +0x1d4 remaining motion time; +0x1dc.. motion channel records (stride 0x50) tested by `108ff650` (frame window trigger, 20k callers); +0x204 hit-stop; +0x32c.. motion ids; +0x410/+0x4e3 per-action scratch bytes; +0x624/+0x6bc obfuscated u16 values (decode: rotate + XOR with entity key and 0x5ec0; 10aa0d70/10aa0ce0); +0x678 model resource; +0x7f8 area id (must equal DAT_1e7fff3c+0x14); +0xaa6 airborne; +0xab3 locked; +0xcc4 mode byte.
AI structure: each species has a dispatcher `switch(actor+0x14)` calling one handler per attack; handlers are small state machines on `actor+5` using the template "step 0: clear scratch, start motion (1084fe60); step 1: wait until +0x1d4==0; then advance". Examples: 100659b0 (0x79), 101b48c0 (0x5f), 101b8d10 (0x63).
Action nodes: pooled 0x200-byte records (alloc 111d4e20 under CRITICAL_SECTION 1e73ad88) with class id at +4 (0x6f, 0x71, 0x98, 0x9a, 0x9e, 0x9f...), sub-id +6, update callback +0x28, owner +0xac, position +0x38.., prior position +0x44.., area +0xf2. Spawners per class: 101de750, 101e6210, 101eda40, 101f5030, 101f9f00, 101fd570. Effect emitters are looked up by id in the table at 0x1e8d31a8 (stride 0x44) via 113d61f0/113d6250.
Global action serial counter: DAT_1e7fff3c+0x23fc (u16, skip 0, under CRITICAL_SECTION 1e73ae00), assigned by 100b7bb0/10140b90/100f9ce0.

## 6. Math helpers [H]
vec3: 100068d0 length, 10006900 distance, 10006930 normalize; 10006880 yaw rotation (xz), 10006830 pitch; matrices: 10004c20/10004d10/10004dd0/10004e90 build rotation from Euler angles in different orders, 10004f80 + 100051a0/100053c0/100055e0/10005830 rotate a basis by Euler sequences in various orders, 10005a60 extract axis scales, 10005fa0/10006290/10006570 extract Euler angles, 1000cf30 identity, wrappers 1000cf90/1000cfc0 for D3DXMatrixScaling/Translation.

## 7. Constants read from the DLL
1.0=DAT_1199cb64, 0.0=DAT_1199cb60, 0.5=DAT_116038a8, 2pi=DAT_119b5f1c, 1/65536=DAT_119b5f34, 360=DAT_119b5f14, 1/360=DAT_119b5f18, -1.0=DAT_1195780c, 3.0=DAT_11617770, 2.0=DAT_119a65d0, 2pi/16384=DAT_119b6810, 1/16=DAT_119b6078.

## 8. Open questions
- Meaning of mesh chunks 0xc and 0x12, and of per-part bone-map use at skinning time (HD model injection).
- Whether animation frame advance happens at draw time (skeleton pose caller chain from entity draw callbacks not traced here).
- Which exact quest/area structure 1087cb30 consults (named quest_monster_has_role at low confidence).
- Obfuscated values at actor +0x624/+0x6bc: what they represent (HP-like?).
