# Test results - 2026-11-07, Bambu A1 (LAN mode), owner present at the printer

## T0 - starting a job
- Plain .gcode via `start` (gcode_file): **REFUSED** by the A1 (reply result=fail, "error string").
- .gcode.3mf via `start3mf` (project_file): **PASS**, reply success and the job went RUNNING.
- Fixes needed along the way: the FTPS upload hung on TLS shutdown (now sent without unwrap); the MQTT send
  published before it was connected (now waits for the connection and reads the printer's reply).

## T1 - pause / resume / stop
- pause -> PAUSE: **PASS** (printer reply success)
- resume -> RUNNING: **PASS**
- stop -> FAILED, both heater targets 0: **PASS**
- Finding: with the bed set to 35 C, the bed reached ~52 C (the A1 seems to heat the bed itself during homing
  when the setting is low). The tests now use a realistic 55 C bed.

## T2 - no false alarm when the target drops (bed now 55 C)
- **PASS**: the guard stayed quiet through the 210 -> 180 C drop and exited 0 at FINISH.
- One strike (1/2) was logged on the reading taken right as the target dropped. Fixed: a reading right after a
  target change no longer counts. Unit test added with the real readings.
- The bed wandered 52-58.6 C around its 55 C target (within the 10 C margin).

## T3 - the guard stops a job by itself (NOZZLE_OVER=-100 fake fault)
- **PASS**: 2 strikes in a row -> THERMAL ALARM -> stop sent -> printer state FAILED, targets 0, exit code 2. Took ~1.5 min.

## T4 - camera spaghetti check
- **PASS (detection + pause)**: frame 1 (pad printing) was judged fine, no pause. Frame 2 showed no pad on the
  plate and loose strands hanging from the nozzle -> judged failed -> paused (printer confirmed PAUSE) and sent
  the frame to the owner. Then stopped.
- The test itself under-performed: much less plastic came out than planned and no pad stuck. Likely causes:
  start3mf sends use_ams=false while the filament is in the AMS lite, and/or no Z offset / bed levelling without
  Bambu's start G-code. A full mid-air "tangle" was not produced, so detection of a big tangle is still unproven.
