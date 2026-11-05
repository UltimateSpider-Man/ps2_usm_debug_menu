# ps2_usm_debug_menu

# USM PS2 beta debug menu → SLES_536.72 (final, PAL)

This folder rebuilds the debug menu from the SLUS_208.70 prototype and injects it into the final `SLES_536.72` ELF.

The final game had the menu compiled out: no `debug_menu` code and no strings. So the menu was re-implemented in R5900 assembly, using the beta's behaviour and layout. It calls only the final game's own functions, at addresses found and checked by disassembly.

Expanded-menu output: `..\out\expanded\SLES_536.72`. It is exactly the same size as the original (6,960,960 bytes), so it can replace the disc's boot ELF in place. Use the clean disc ELF as input; earlier patched executables are not valid build inputs.

## Controls (same bindings as the beta)

| Button | Action |
|---|---|
| SELECT | open / close the menu (`DMENU_TOGGLE`) |
| START | release / grab focus: the menu stays on screen and the game runs (`DMENU_FOCUS_TOGGLE`) |
| D-pad up, down | move the highlight (hold to repeat: 0.25 s, then 0.05 s) |
| L1 / R1 | page up / down (21 lines) |
| D-pad left, right | change a value or toggle a bool |
| X + left/right | accelerated decimal adjustment: default step ×10, AI step ×30 |
| X | select: enter a submenu, run an action, toggle a bool |
| Triangle / Circle | back to the parent menu |

Up/down/left/right use the same pad axes as the game's front-end menus (`FE_UD`/`FE_LR`).

While the menu has focus, physics is stopped (`game::enable_physics(false)`, as in the beta). The previous state is restored when the menu closes or loses focus. Pause (START) and the city map (SELECT) are ignored while the menu is using those buttons, matching the beta's `had_menu_this_frame` checks.

One difference from the beta: SELECT opens the menu at any time. The beta only allowed it while physics was stopped from a devkit keyboard or while the "spider monkey" tester was running. On a retail console that meant the menu couldn't be opened at all.

## Menu contents

The root follows the reference videos: Warp, Game, Missions, Replay, Debug Render,
District variants, AI, Memory, Entity Variants, Level Select, Script, Progression,
Camera. Replay remains at the root as requested. A private copy of the beta's
fixed-width font gives the original 10-pixel character width and 15-pixel rows;
the game's own font stays unchanged.

- **Warp**: "--WARP TO POI--" (teleports to the mission arrow target), then every warpable region (`flags & 0x4000`), sorted by name. Locked districts are unlocked first, then `malor_point` to the region spawn point.
- **Game**
  - **Devopt Ints**: all 76 `os_developer_options` ints, range -1000..1000.
  - **Devopt Flags**: all 150 flags, read and written live.
  - **Physics Enabled**, **Single Step**, **Slow Motion Enabled** (`FRAME_LOCK` = 120), **Rumble Enabled**, **God Mode** (0–5, `set_god_mode`), **Show Districts**, **Show Hero Position**, **Show FPS**.
- **Debug Render**: the final's 51 `debug_render_items`, using the game's own names, min and max.
- **District variants**: every region with more than one variant, shown as `n [0, max]`; changes call `terrain::set_district_variant`.
- **Level Select / Hero Select**: the beta hero list (ultimate_spiderman, venom_rampage, venom, shield_agent, mary_jane, green_goblin, peter_parker, peter_hooded). Only heroes whose character pack exists on the disc are listed. The swap follows the beta sequence: remove player → wait 2 frames → `add_player` → wait 2 frames → set the health-widget type → close.
- **Camera**: Chase / User / SceneAnalizer, as in the beta.

### Expanded layout

The expansion moves **Hero Select into Level Select**. Replay is at the main
root, as requested. The following additions use retail structures and functions;
they do not require beta-only game assets.

| Menu | Behavior |
|---|---|
| Level Select | Hero Select with current-hero True/False markers, direct level actions from the resident `level` resource, and the beta's `-- REBOOT --` row. `CITY_ARENA` displays as `city`. Selecting it restarts the current executable through native `LoadExecPS2`, supplying `skip_to_loading`, the real scene key, and the current hero, to repeat the logos/loading sequence and enter gameplay directly. Other levels retain their native in-process loader. Only available level packs are offered. The original beta reboot handler is empty; that row retains its original no-op behavior. |
| Missions | District submenus followed by `UNLOAD CURRENT MISSION` and global missions, using the original `script (instance)` labels. Lists are filtered for the current hero and available packs, with pagination when needed. |
| Replay | A single `Start` action reruns the last mission launched through Missions, limited to the same scene and hero. It has no submenu arrow or last-selected status row. With no valid selection it does nothing. |
| Debug Render / NGL | Native performance information, performance bar, and queued low-resolution screenshot. Uses packed byte flags without modifying neighbouring options. |
| AI | Live actor hashes → Core params / inode params → typed parameters. Floats and integers are editable; structured values are read only. Export writes the entire block to `host:param_dump_0x<actor>.txt`, with explicit failure when host output is unavailable. |
| Memory / Slabs | Total/free slab counts and per-size full/partial slabs, allocated objects and free objects. Read-only snapshots are reconstructed from the real allocator lists. |
| Entity Variants | Current hero and loaded conglomerates with variant interfaces; paged variant selection through the native apply function. Removed/replaced entities are rejected. |
| Script | Original debug callbacks discovered in loaded Chuck executables. This includes KILL HERO and, while V08 is loaded, WIN V08, MAIM ELECTRO and STUN ELECTRO. Actions resolve their live instance again before dispatch. |
| Progression | Original script-authored progression on/off and story jump callbacks, rather than editing completion counters. The retail city executable retains 25 such callbacks plus KILL HERO. |
| Game / Progression Settings | Saved upgrades, unlocks, counters and statistics; these edits do not execute mission-completion scripts. |
| Game / Saved Game Settings | All 97 fields shown by the beta editor, mapped to verified retail offsets, including booleans, integers and decimal values. |

Dynamic catalogs rebuild when opened. Mission names are copied into menu-owned
storage; entity variant children use a separate pool so Back preserves their
parent list. Empty/unavailable resources do not call native action functions.
Saved-settings edits change the current in-memory settings; saving to a memory
card is a separate action.

City restart validates and copies the scene, hero and boot path before releasing
sound/render/input resources. The running executable must remain available at
its boot path; host-based launches require a working host filesystem mapping.
Preflight failures leave the game intact and show a message beside `city`.

Script dispatch is limited to the 29 audited CITY/V08 callbacks; other missions'
callbacks and those requiring the removed native menu-entry ABI are excluded.
The video actions above do not read that argument and execute through the game's
own VM. Mission-specific actions appear only when their executable is resident.
AI and entity pointers are revalidated before input and rendering so a streaming
unload closes a stale editor instead of writing to a replaced object.

The generated expanded ISO also restores an earlier malformed `game_finished`
script entry: its offset/length are returned to the intact original function
body. This is an eight-byte metadata repair, recorded beside the ISO in
`ULTIMATESPIDERMAN_debug_expanded.game_finished.repair.json`; the previous bytes
are backed up there. The remaining packed assets are preserved byte for byte.

`Report SLF Recall Timeouts` defaults to False. When True, it reports an SLF
recall exceeding the native ten-second threshold to the EE debug console/serial
output, including the thread and instruction addresses. Reporting follows the
native timer reset and preserves its return value and script state. NGL screenshots use
the game's PS2 host-file output and require a suitable host mapping; use PCSX2's
screenshot command when a normal Windows image file is needed.

## Building

Only the Python standard library is needed.

From the project root, double-click `build_injected_elf.cmd` to build from
`source/SLES_536.72`, the clean ELF previously extracted from the original disc.
The earlier original-ISO path is no longer present, so the default uses this
preserved clean source. Its SHA-256 is
`cd4d9344e4aac38a6e9409a568b6ee61ae483dcc330f49230030674d5a1772d7`.
To choose a different source, run:

```bat
build_injected_elf.cmd "path\original.iso"
```

Or invoke the Python helper directly with a clean PAL ELF or ISO:

```bat
python build_injected_elf.py "path\SLES_536.72" --output "out\expanded\SLES_536.72"
```

The helper assembles and injects the menu, runs the full interpreter checks on a
temporary output, and then saves the verified ELF. It accepts an existing output
only when its bytes already match the new build. This produces an ELF; archive
recovery and a complete repaired disc use `patch_iso.py` below.

To build a disc image, keep the packed assets and replace the boot ELF at its
existing location. Run these commands from this folder:

```
python patch_iso.py "path\ULTIMATESPIDERMAN.iso" "..\out\ULTIMATESPIDERMAN_debug_fixed.iso"
```

`patch_iso.py` extracts the ISO's own PAL executable, injects the menu, and writes
a new ISO. It preserves file locations and refuses to overwrite an existing
destination. It does not unpack or rebuild the game's resource archives.

For an archive with a confirmed zero-filled tail, supply the matching intact
local archive:

```
python patch_iso.py "path\ULTIMATESPIDERMAN.iso" "..\out\ULTIMATESPIDERMAN_debug_fixed.iso" --restore-amalga "path\AMALGA.PAK"
```

The optional repair requires equal archive sizes, a matching header and prefix,
and an entirely zero-filled remainder in the ISO. It restores only that suffix;
any conflicting nonzero data is rejected. The source files are read only.

For a loose ELF, use a trusted original PAL executable:

```
python patch_elf.py ..\source\SLES_536.72 ..\out\expanded\SLES_536.72
python test_dm.py ..\out\expanded\SLES_536.72
```

- `patch_iso.py`: validates the ISO9660 boot entry and preserves the disc layout; optionally recovers a verified zero-filled archive tail.
- `dm_build.py`: menu core and module integration. `dm_missions.py`, `dm_entities.py`, `dm_game_extra.py` and `dm_game_actions.py` contain the expanded handlers and verified retail addresses; `retail_settings.py` lists the 97 saved fields.
- `asm5900.py`: a small assembler. It rejects R5900 hazards: short loops (CPU erratum), FP compare directly before `bc1x`, a branch or split `li`/`la` in a delay slot, and writes to `$gp` or `$f31` (the game keeps 1.0 in `$f31`).
- `patch_elf.py`: checks every patch site against the original instruction before changing it.
- `emu.py` + `test_dm.py`: an R5900 interpreter that runs the menu inside the real ELF image, with the game functions replaced by stubs. The tests cover input repeat, navigation, rendering, every handler, the hooks, and preservation of callee-saved registers.

## What the patch changes

| Address | Change |
|---|---|
| new PT_LOAD at `0xE0000`–`0xF84C0` | menu code and data, in user RAM below the game image (`0x100000`). Stored in the file inside the unused `.DVP.overlay` link data, which is never loaded. The game's BSS, heap and stack are exactly as shipped. |
| `0x311DAC` `jal` | `app::tick`: the menu's frame advance runs before `link_system::frame_advance`, where the beta called `debug_menu::frame_advance` |
| `0x295B78` `jal` | `game::render_ui`: the menu is drawn just before the UI scene's `nglListEndScene` |
| `0x37E09C` `jal` | `IGOFrontEnd::CheckPauseUnpause`: pause input is ignored while the menu used input this frame |
| `0x381254` `jal` | `IGOZoomOutMap::UpdateSelectButton`: the map won't open while the menu is up |
| `0x2F659C` `jal` | `vm_thread::call_script_library_function`: optional reporting after a native SLF recall timeout |

Final-build offsets that differ from the beta and were checked in code: `game` `stop_physics` 0x1A8, `single_step` 0x1A4, `user_camera` 0x1C8; world `terrain` 0x1B0, `hero_ptr[0]` 0x234, `num_players` 0x23C; region flags 0x50, spawn point 0xA4, district id 0xC0, variant count 0xC8; `os_developer_options` ints at 0x33C. The flag and int indices were remapped by name, because the final added options.

`patch_elf.py` asserts that, apart from the new segment, the loaded game image differs from the original only at these four instructions.

### Why the menu lives at 0xE0000

The first build put the menu right after the BSS and moved the heap start up by
about 46 KB. A smaller heap was initially suspected when gameplay showed a black
screen. That diagnosis was not established. The low-memory placement retains the
game's original BSS and heap layout.

`0xD0000`–`0x100000` is never referenced by the game. EELOAD (`0x82000`) and OPL's EE core and IOP-module storage (`0x84000`–`0xD0000`) stay below it, so the menu can sit there without taking any game memory. One OPL caveat: compatibility modes that move OPL's EE core elsewhere haven't been checked, and cheat devices that use low RAM may collide.

## Status

### Expanded build

The packaged expanded ELF passes the full interpreter suite (7,785,443
instructions), including native argument contracts, null/busy guards, packed
byte writes, signed floats, dynamic-list pagination, stale resource protection,
and asynchronous auto-load transitions. `build_injected_elf.py` verifies the
actual packaged ELF, not just an unattached payload.

The expanded ISO cold-booted in PCSX2 2.9.155, reached the opening stadium fight,
and displayed all requested root menus. The private test session is stopped.
Individual native actions, later levels, physical-console compatibility and PS2
host-file screenshot export have not all been exercised in the emulator.
The prior gameplay video below documents the earlier build, not this expansion.

Expanded deliverables:

- `../out/expanded/ULTIMATESPIDERMAN_debug_expanded.iso`
- `../out/expanded/SLES_536.72`
- `../out/expanded/verification.json`
- `../out/expanded/menu_in_gameplay.png`

The expanded disc is exactly 5,527,797,760 bytes. A complete byte comparison
against the previously verified repaired ISO confirms that only the boot ELF
changed; all repaired resources and disc extents are preserved.

Game now also provides Monkey Enabled, combined X/Y camera inversion,
controller-2 user camera, district streaming toggle, native Save/Load screens,
Attempt Auto Load, and low/high-resolution screenshot requests. Save/Load use
the game's existing three-slot memory-card UI and its confirmations/error
handling. Auto Load waits for valid card data and selects the newest save;
leaving the native screen or a card error cancels it. High-resolution capture
uses a bounded 1280x960 native process. The Game menu has no `Last action` row.
The SLF timeout-reporting entry is explicitly marked unavailable, because no
working retail hook was found. Script variable editing requires retained type
metadata; this does not restore stripped script-authored custom menu commands.

### Earlier repaired build

Verified: assembly checks, the instruction check at every patch site, and the full interpreter test suite on the patched ELF loaded the same way the PS2 loader loads it.

The repaired ISO was also cold-booted in PCSX2 2.9.155. It passed the memory-card
screen, loaded the opening stadium fight, and ran past the previous assertion.
The injected menu opened during gameplay; Warp, Debug Render, and Game submenu
navigation was exercised, and gameplay resumed after the menu closed. This is
an opening-gameplay check, not verification of every menu action or later level.

Local deliverables from this run:

- Repaired disc: `J:\USM_PS2_Debug_Menu_Fixed\ULTIMATESPIDERMAN_debug_fixed.iso`.
- Verified injected ELF: `..\out\SLES_536.72`.
- Game-only video, including the menu and resumed combat: `..\out\gameplay_debug_menu.mp4` (50 seconds).
- Image hashes and full-disc byte-comparison results: `..\out\verification.json`.

### November 5, 2026 loading failure

The reported `ReadFIFO_VIF1` / `FQC = 0 on VIF FIFO READ!` assertion was reproduced
with the rebuilt `ULTIMATESPIDERMAN - Copia.iso`, including with the unmodified
game executable and no injected menu. Native `nglUploadTexture` received invalid
texture metadata and followed a child-texture pointer into hardware registers.
That ISO used hundreds of loose packs instead of the original packed layout.

The other supplied `ULTIMATESPIDERMAN.iso` had a separate damaged archive tail:
the first 162,416,640 bytes of `PACKS/AMALGA.PAK` matched the local archive exactly,
but the remaining 30,867,712 bytes were all zero. The repair command above
recovers that suffix and injects the menu into the ISO's own executable.

Start the repaired image with a fresh boot. Earlier save states retain the old
executable and loaded resource data. Console compatibility remains untested.
