# Renderer and graphics settings (subsystem agent s_render)

Status: first pass written early (see "Open items"). Confidence: [V] verified in decomp/disasm/real files, [D] read from decomp, [I] inference.
Image base 0x10000000. Binary: `mhfo-hd.dll` (HD, selected by launcher) or `mhfo.dll` (SD).

## 1. Launch chain and settings
- `mhf.exe` (non-LAA, 2 GB address space) loads `mhl.dll` (launcher; contains the mhf.ini key strings FULLSCREEN_MODE, TEXTURE_DXT_USE, GRAPHICS_VER, DISP_MAX_CHAR...). mhl parses `mhf.ini` into a large launcher struct (mhf.exe global 0x449190).
- Game DLL selection [V, mhf.exe 0x4028a6]: `cmp [struct+0x1d94],1` -> loads `mhfo-hd.dll` if 1, else `mhfo.dll`. This is GRAPHICS_VER (ini: GRAPHICS_VER=1 = HD).
- `mhDLL_Main(struct)` (114d68a0, export) runs: OS-version detect -> `1158ec70` (copy settings) -> `114d89a0` -> `114d5cb0` (window) -> D3D init -> `114d4cd0` (2 worker threads) -> Win32 message loop. Other exports: `DLL_SetWindowHn` 114d6b60, `mhDLL_ToolMain` 114d6b70.
- The DLL itself contains NO ini key strings; all ini parsing is in mhl.dll (outside the decomp). Struct offsets consumed by `1158ec70` [D] (names inferred from ini keys, [I]):

| struct off | global | meaning |
|---|---|---|
| +0x1d74 | DAT_1e866c70 | window mode (FULLSCREEN_MODE): 0 windowed, 1 borderless at monitor size, 2 popup at 0,0 |
| +0x1d78/+0x1d7c | DAT_119dd740/744 | WINDOW_RESOLUTION_W/H (min clamp 640x480; copies in 119dd738/73c) |
| +0x1d80/+0x1d84 | DAT_1e866c68/6c | FULLSCREEN_RESOLUTION_W/H (0 = use monitor size; min 640x480) |
| +0x1d90 | - | NOW_MONITOR_WH: if nonzero fullscreen size := current monitor rect (114d5cb0) |
| +0x1d8c | DAT_119dd748 | TEXTURE_DXT_USE; forced 0 if none of DXT1-5 supported (114d4fa0) |
| +0x1d94 | - | GRAPHICS_VER (DLL choice) |
| +0x1d98/9c/a0/a4 | DAT_1e866c88, 1e866c8c, 119dd75c, 119dd760 | BRIGHT and 3 colour/gamma values, clamped 0..0x100 then /4 (>=0x3c -> 0x100) |
| +0x1da8, +0x1dac | DAT_119dd754, 119dd758 | clamped 0x40..0x4000 (likely DISP_MAX_CHAR range) [I] |
| +0x1db4/+0x1db8/+0x1dbc | DAT_1e73ab44/48/50 | misc (screenshot path string at 1dbc) |
| +0x1e24 | DAT_119dd750 | late-frame-skip enable (read by limiter 1000a2f0) |
- Aspect `_DAT_119dd768 = width/height` is computed from backbuffer size and used by projection builders (1043fec0, 10b89f60, 10baf300). So any resolution works; UI uses its own 2D scaling.

## 2. Window and display modes
- `114d5cb0`: class "M_H_F", title "MONSTER HUNTER FRONTIER Z ..." window; mode 0 = normal framed window (client area resized to W x H), mode 1 = WS_POPUP at monitor origin sized to monitor, mode 2 = popup 0,0 at fullscreen res. DAT_11aa7ca8 (D3D Windowed flag) = 1 for modes 0/1, 0 for mode 2 [D].
- `114d5420` toggles windowed <-> borderless then calls `114d6e20` (device reset). Also disables screensaver, power-off, sticky keys while running (SystemParametersInfo; restored at exit).

## 3. D3D9 device creation `114d4fa0` [V, disasm]
1. Requires `%SYSTEM%\d3d9.dll` (else MessageBox "DirectX 9.0c").  `Direct3DCreate9`. Adapter = the one whose HMONITOR matches the window's monitor (DAT_1e811a30).
2. `GetAdapterDisplayMode` -> backbuffer format = desktop format.
3. D3DPRESENT_PARAMETERS at 0x11aa7c88: BackBufferWidth/Height = `DAT_1ebee5a0 / 1ebee59c` (window W/H or monitor), BackBufferCount 1, MultiSample none, SwapEffect 3 (D3DSWAPEFFECT_COPY), Windowed per mode, EnableAutoDepthStencil 1, AutoDepthStencilFormat 0x4b (D3DFMT_D24S8), Flags 1 (LOCKABLE_BACKBUFFER, needed for screenshots), RefreshRate 0, PresentationInterval 0 (DEFAULT). No MSAA at all: the ini 90C_GRAPHIC_ANTI_ALIASING is a shader post-process, not hardware MSAA.
4. CreateDevice(HAL): behaviour 0x40 (hardware VP) if `VertexShaderVersion > 1.0` and DAT_1e866ca0==0, else 0x20 (software VP) with HAL, then REF. When software VP, `MaxVertexShaderConst` global (copy of caps at 0x11b7fcf0+0xc8) is forced to 0x60; code paths test it (`<0x91` => software-skinning mesh path in 10007b60/10008220; `>0x90` in 10018a70).
5. CheckDeviceFormat for DXT1,2,3,4,5 (texture, usage 0): bitmask; if none, TEXTURE_DXT_USE forced off. NOTE: the game does not itself create DXT textures from PNG; D3DX picks A8R8G8B8 for PNG regardless.
6. Timer mode flags `DAT_11aa6ad8` (QueryPerformanceCounter available | READ_SCANLINE caps | 4) choose the sync method.
7. Default states: SetRenderState(0x16?,...) twice, Clear, Present.
- Device caps usage: ONLY VS version, MaxVertexShaderConst and Caps bit 0x20000 are used. **MaxTextureWidth/Height, NPOT caps, MaxPrimitiveCount and MaxVertexIndex are never read** (no references to caps+0x58/0x5c). So texture size is never validated by the game; D3DX itself clamps to device limits (16384 on modern GPUs).

## 4. Device reset `114d6e20` [D]
Saves (Get*) ~75 render states, ~30 texture-stage + sampler states for stages 0 and 1, VS constants 0..95 (GetVertexShaderConstantF, 0x60 regs) and N-patch mode; releases default-pool objects (`114d3250`, GDI font objects, RT/depth surface DAT_1e73d38c); `Reset(&presentParams)`; GetBackBuffer; recreates `114d2f80`, `114d32b0`, `10baea70`; restores all states; Clear + 2x Present. Managed textures survive; default-pool/render targets (post-process RTs from `10029cb0`) must be recreated. A new engine does not need this.

## 5. Threading and the texture slot system
- Device calls are serialized: `1158ffd0` runs a job on the "render" thread (thread id DAT_1e866d0c) or queues it with an event handshake; texture create/release go through it.
- Texture slot table: base 0x11aa7d80 (record id N at 0x11aa7cf0+N*0xd8, texture pointer at +0x90), 4096 records (ids 1..4095; id 0 invalid). Alloc `100113f0` returns 4096 when full (callers do not check -> corruption). Record keeps a copy of D3DSURFACE_DESC (0x48 B) and width/height.
- Create: `10011af0(data,size,id)` -> job `10011a70`: reads PNG IHDR (`100119f0`; or DDS header) and calls **D3DXCreateTextureFromFileInMemoryEx(device,data,size,Width,Height,MipLevels=1,Usage=0,Format=D3DFMT_UNKNOWN,Pool=MANAGED,Filter=NONE,MipFilter=NONE,ColorKey=0,...)** [V]. So: PNG decoded by D3DX (not GDI+; gdiplus.dll is imported for screenshots/UI fonts only [I]); no mipmaps; no downscaling; any size, NPOT ok (D3DX rounds up to pow2 only on devices that demand it).
- Per-model texture-id table `DAT_1ecda320` (u16 entries, 0x109d used): `108df7d0(array)` with EAX=base index loops over the PNG list: allocates an id and stores it at table[base+i]. Entries listed in permanent list (DAT_11887934, terminated by -1) or protected ids (DAT_1ed7d500..20) are skipped/reset. Writes are 4 bytes into a 2-byte table (clobbers next entry with 0; harmless when filled in order but the entry right after the last image gets zeroed). No bound check of count vs the 0x44 capacity.
- Release: `108df700(base,count,force)`, `108df660` (sweep all).
- Monster slots: set A base `0x5ed + slot*0x48`, set B `0x631 + slot*0x48` (72 ids/slot, table ends 0x109d => 38 slots).

## 6. Texture limits relevant to HD injection (summary; see spec\model-format.md section 7 for arena limits)
1. 4095 live textures globally (each PNG = 1); overflow is unchecked.
2. 68 images per monster set A (capacity before overwriting set B / next slot), 4 for set B.
3. Memory: managed A8R8G8B8 w*h*4 per PNG regardless of PNG bit depth (palette PNG 512x512 = 1 MiB, 1024x1024 = 4 MiB, 2048x1024 = 8 MiB), plus D3D keeps a sysmem copy. Process is **32-bit, NOT large-address-aware, 2 GB limit**; DLL image alone is 241 MB (static arena, includes 14 MiB monster arena + 144 MiB read buffer BSS) plus a 192 MiB malloc raw buffer. Replacing a monster's 24 PNGs with 1024^2 (T3) adds ~96 MB sysmem x ~2; plausible to exhaust address space together with area stage textures. **Experiment T6: set IMAGE_FILE_LARGE_ADDRESS_AWARE (0x20 in COFF characteristics) on a COPY of mhf.exe**, or use a 4GB patcher, then retest T3. [I, untested]
4. D3DX load failure (bad PNG, e.g. 16-bit/interlaced unsupported) leaves slot pointer NULL: later SetTexture(NULL) is legal in D3D9, shaders sample black; not a crash by itself.
5. Sizes are read from the PNG header, not from the model's type-0xa descriptor (w/h there are informational) [D].
6. Strongest crash candidates remain: entry-6 material table vs mesh mismatch (MessageBox + discard), arena overflow if model grew, texture count > 68, and address space exhaustion.

## 7. Shader system [V for container, D for use]
- File `dat\mhf_90c.bin` (6.9 MB, "90c" = DX9.0c / SM3): `u32 count=93; {u32 offset,u32 size}*93`; entries 0..6 PNG (UI/lookup textures), 7 and 8 data tables, **9 = JKR block (2,171,251 B decompressed) = shader pack**, 10,14 JKR, 11-13 PNG, 15-49 small binary tables, 50-92 PNG (post-process/UI/lighting textures).
- Loaded once by `100121b0` (reads entry 9, JKR-decompresses to malloc). Layout of the decompressed shader pack (offsets from start) [V]:
  - 0x0000: 9 classes x 4 sub-variants x 14 vertex shaders, each pair `{u32 size, u32 offset}` (36 groups x 14 = 504 VS); **all are VS 3.0 (0xFFFE0300)**. Each is created with one of the 3 vertex declarations (below). Class index = bone-palette class (render flags & 0xf00), see model-format 3.3.
  - 0xfc0..: 8 more standalone VS (+decl) and PS table at 0x1004 (8 PS), VS arrays at 0x1044 (8), 0x1084 (12), 0x10e4 (12), 0x1144 (0x2a8/8=85), PS arrays at 0x13ec, 0x142c, 0x148c, 0x14ec (PS 3.0); 4 D3DX effects `{offset,size}` at 0x17e4 (compiled with D3DXCreateEffect, shown with MessageBox on compile error); 2 textures at 0x1800 (D3DXCreateTextureFromFileInMemory), the first is bound as owner object (+0xd4) field.
  - So the game REQUIRES Shader Model 3.0 hardware; there is no fixed-function path for models, only UI quads and some legacy.
- Vertex declarations (dumped from DLL, D3DVERTEXELEMENT9) [V]:
  - 0x11979f60 "plain" stride 28: POSITION f3@0, NORMAL f3@12, COLOR0 D3DCOLOR@24
  - 0x11979ef0 "static" stride 52: POSITION@0, NORMAL@12, COLOR0@24, TEXCOORD0 f2@28, TANGENT f4@36
  - 0x11979f20 "skinned" stride 72: POSITION@0, BLENDINDICES ubyte4@12, BLENDWEIGHT f4@16, NORMAL@32, COLOR0@44, TEXCOORD0 f2@48, TANGENT f4@56
- Constant upload: per-pass constant table at 0x11aa6af8, uploaded by `1000c390`/`10029280`/`10015450` (view matrix reg 38, lights regs 9,21-25, bone palette reg 0x2a x4, misc 0x26,0x2e,0xc3,5), SetVertexShaderConstantF(+0x178) in 26 functions, SetPixelShaderConstantF(+0x1b4) in 51. Render-flag word editor `1000c390`; current flags `DAT_11b7fe20`, cached `DAT_11b8c658` (state applied by `1000b3c0` when they differ) [D]. Bits (from model-format): 0xff000000 pass type, 0xf00 palette class, 0x1c light flags, 0x8000, 0x4000, 0x10000/0x60000 etc.

## 8. Render pass structure (summary of earlier notes + verified)
Frame: logic tick `108e3f00`; `1080fe60` runs update then render block: pass 2 (main scene), pass 4 + pass 3 (if `DAT_1edba1bc->+0x15`; pass 4 clears ZBUFFER only, pass 3 draws with state `DAT_119b840c`). Pass id is stored at `*(DAT_1e3cbd64+0x64)`; per-pass shared state at +0x10. Post-process quad `1002a760` (FVF 0x104, sampler 5). `10029cb0` constructs the 0x210-byte owner (RT textures, depth surfaces). BeginScene/EndScene nested wrappers `1000a260/1000a2b0`. Present at end of frame in `1000a4c0` (Present `Present(0,0,0,0)` vtable +0x44) after Clear(TARGET|ZBUFFER, colour DAT_1199cb64).
NOTE: ini keys 90C_GRAPHIC_* (shadow, DOF, bloom, SSAO, godray, soft particle) select which of the effects/post-process shaders run; consumers not traced yet.

## 9. HD mode asset selection
- Launcher picks mhfo-hd.dll when GRAPHICS_VER=1. The HD DLL's path builder (`108fba70`) tries `emmodel-hd\emNNN[_b..e]-hd.pac` then `emmodel\...`. Stages: `stage-hd\` directory exists too. mhfo.dll (SD) contains only SD paths [D, string search of mhfo-hd: both lists present in HD DLL].
- TEXTURE_DXT_USE has no effect on PNG decode (see 3.5); it only gates DXT usage where the game calls D3DX with explicit formats [I].

## Open items / next
- Trace consumers of DAT_119dd748 (DXT flag), 90C_GRAPHIC_* settings, and what 114d2f80/114d32b0/10baea70 recreate.
- Decode 0xf0000 render-state block to D3D states; name the 4 effects (.fx) in pack entries; map shader index -> function.
- Runtime tests T4-T6 (see section 6).
