# mhfz-decomp

Reverse-engineering research for the Monster Hunter Frontier Z PC client (`mhfo-hd.dll`): function names, file-format and
subsystem specs, analysis tools and the naming pipeline.

**No Capcom code or data is included.** There is no decompiled output, Ghidra database, game binary or asset in this repo.
Everything here is either original tooling or a description of how the client works. To get readable decompiled code,
apply the names in this repo to your own copy of the game (see below).

## Layout

| Path | Contents |
|---|---|
| `spec/` | File formats (archives, models, animation) and per-subsystem specs (`spec/subsystems/`: combat, monster AI, effects, game data, network, UI, quests, ...) |
| `NOTES.md` | Dated research log |
| `analysis/merged_names.csv` | Final function-name map: `addr,name,confidence,tier,subsystem,purpose` (~47k functions) |
| `analysis/ghidra_names.csv` | First-pass names from the small-model naming run |
| `analysis/mh2_matches.csv`, `mh2_names.jsonl` | Functions matched against the Monster Hunter 2 (Dos) PS2 decompilation |
| `analysis/em130_fx_map.json` | Varusaburosu (em130) motion -> effect mapping |
| `ghidra/scripts/` | Ghidra headless scripts: export functions, decompile in shards, apply names |
| `tools/` | Python tools: archive/JKR unpacking, model/pac readers, disassembly helpers, MH2 matcher, name merging |
| `orchestrator/` | The distributed LLM naming pipeline (hub + feeders); see `orchestrator/SETUP.md` |

## Regenerating the named decompilation

1. Import your own `mhfo-hd.dll` into a Ghidra project and run auto-analysis.
2. Apply the names: `analyzeHeadless <proj> mhfz -process mhfo-hd.dll -postScript ApplyNames.java analysis/merged_names.csv`
3. Optionally dump C per function with `DecompileShard.java` (output stays local; do not commit it).

