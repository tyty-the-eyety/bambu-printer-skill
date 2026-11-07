---
name: bambu-printer
description: Check on and safeguard a Bambu Lab 3D printer (built and tested on the A1; A1 mini and P1 should work but are untested) over the local network - print progress, temperatures, errors, camera snapshots, watching a print to completion, and guarding a print (auto-stop on overheating, camera checks for spaghetti with auto-pause). Use when the user asks how a print is going, to monitor/watch/guard the printer, to check the camera, or whether a print finished/failed.
---

# Bambu printer (local LAN)

All commands use `scripts/bambu.py` in this skill's folder (usually `~/.claude/skills/bambu-printer/scripts/bambu.py`;
written as `bambu.py` below). It runs via `uv`, which installs paho-mqtt automatically.

Setup (once): `bambu.py setup <printer-ip>` saves the IP and serial to `~/.config/bambu-printer/config.json`.
If any command says the printer IP is unknown, ask the user for the IP (printer screen: Settings -> WLAN/Network)
and run setup. If the printer's IP changes, run setup again.

The LAN access code is NOT stored by this skill. The script reads it at runtime from OrcaSlicer's config
(key `user_access_code.<serial>`, filled in once the printer has been connected in OrcaSlicer), or from the
`BAMBU_CODE` env var. Never print or echo the code.

- Status: `bambu.py status`
  -> JSON with gcode_state (IDLE/PREPARE/RUNNING/PAUSE/FINISH/FAILED), subtask_name, mc_percent,
     mc_remaining_time (minutes), layer_num/total_layer_num, nozzle/bed temps + targets, print_error (0 = ok).
- Camera: `bambu.py camera <scratchpad>/cam.jpg`, then Read the image
  to judge the print (spaghetti, detached part, blobs, layer shift). Send it to the user with SendUserFile if they asked.
- Watch: run `bambu.py watch 120` with Bash `run_in_background: true`.
  It exits when the job stops RUNNING or reports an error. On completion, read the last line, grab a camera
  frame, and report the result to the user.

- Files: `bambu.py ls`, `bambu.py upload FILE`, `bambu.py start3mf NAME.gcode.3mf`
  (starting a print heats the printer: only when the user asks and is nearby).
  The A1 REFUSES plain .gcode (`start` -> result fail), so wrap G-code as .gcode.3mf (see tests/make_tests.py).
  start3mf sends use_ams=false and skips levelling: fine for test moves. For real prints, have the user send from Orca.
- Control: `bambu.py pause`, `bambu.py resume`, `bambu.py stop` (stop cancels the print and can't be undone).

> **Tested on a real A1 in LAN mode, 2026-11-07** (tests/RESULTS.md): pause/resume/stop, upload + `start3mf`, the guard
> staying quiet when a print lowers its temperature, the guard stopping a job by itself, and camera detection
> + pause of a failed print. Not yet proven: spotting a large mid-air tangle (the test didn't produce one).

## Guarding a print ("monitor it and stop it if something goes wrong")

When the user asks to guard/protect a print, that request IS the authorization for the actions below for
that print only. Do not take control actions in any other situation without asking.

1. **Overheating (thermal runaway): script, no judgement needed.**
   Start `bambu.py guard 30` with Bash `run_in_background: true`.
   It polls every 30 s, and after 2 bad readings in a row it sends STOP itself. Limits: nozzle >15 C over target,
   bed >10 C over target, nozzle >305 C, bed >105 C, or a heater rising while its target is 0.
   Exit codes: 0 = job ended normally, 2 = thermal alarm (print stopped), 3 = firmware error code.
   On exit 2 or 3: grab a camera frame, SendUserFile it with status "proactive", and explain what happened.
   Test the logic without acting: `bambu.py guard 5 --dry-run`.

2. **Spaghetti / detached part / failed print: camera check by Claude.**
   Use ScheduleWakeup (or /loop) to check about every 5 minutes while the job is RUNNING:
   take a `camera` frame and Read it. Compare with the previous frame and with what the part should look like.
   - **PAUSE (never stop)** only when it's clearly failing: a loose tangle of extruded strands, the part knocked
     over or dragged off its spot, or a blob growing on the nozzle. Then SendUserFile the frame (status
     "proactive") and say what was seen. The user can resume from the printer or Bambu Handy.
   - If it's unclear (glare, odd angle, a support that looks messy): don't pause. Note it, check again sooner
     (1-2 min), and send the user the frame if it still looks doubtful.
   - Stop checking when the status is no longer RUNNING/PREPARE/PAUSE, and send a final frame.
   This only runs while a Claude session is open. In LAN-only mode Bambu's own failure detection
   may need the cloud, so don't count on it.

Notes
- Every control command prints the printer's reply ("success success" = accepted). Check `status` after.
- A bed set below ~45 C may be heated higher by the A1 itself (35 C read 52 C). Use realistic PLA temps (55+) in tests.
- In the A1's start routine (nozzle wipe and levelling, layer 0) the bed can overshoot a lot (65 C target -> 91 C on
  2026-11-07) and then cool. The guard correctly ignores it because it's falling. Mention it to the user, but don't act.
- Camera: the A1 serves ONE viewer at a time. If `camera` times out, Orca's device tab or Bambu Handy probably has
  the live view open. Retry a few times and tell the user. During the start routine the camera can also be unavailable.
- Only tested on an A1. Thermal defaults assume A1 limits; override with NOZZLE_OVER, BED_OVER, NOZZLE_ABS, BED_ABS env vars.
- Ports: 8883 MQTT (status + commands), 6000 camera (A1/P1 protocol), 990 FTPS.
- The printer firmware has its own thermal-runaway protection; the guard is an extra layer, not a replacement.
- The guard only runs while a job is active, and exits after the job ends.
