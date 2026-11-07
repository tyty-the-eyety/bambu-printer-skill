# Printer-safety test plan (Bambu A1, LAN mode)

Run ONLY with someone at home and present at the printer. The plate must be empty, with PLA loaded.
Regenerate the files with `python3 make_tests.py`. Script: `B=../scripts/bambu.py` (run from this folder).
Record the result of each step in RESULTS.md (date, pass/fail, notes).

## T0 - starting a job (decides the start method)
1. `$B upload t1_pause_resume_stop.gcode` then `$B start t1_pause_resume_stop.gcode`; wait 30 s; `$B status`.
   PASS: gcode_state becomes PREPARE/RUNNING. If nothing happens:
2. `$B upload t1_pause_resume_stop.gcode.3mf` then `$B start3mf t1_pause_resume_stop.gcode.3mf`.
3. If neither works: open the file in OrcaSlicer and sends it from there. The tests still work.

## T1 - pause / resume / stop (job from T0; nozzle 150 C, no extrusion, air moves at Z40)
- `$B pause` -> within 15 s the state is PAUSE and the head stops.  PASS/FAIL
- `$B resume` -> the state is RUNNING again and the head moves.     PASS/FAIL
- `$B stop` -> the state is FAILED or IDLE; heaters go to 0.        PASS/FAIL

## T2 - no false alarm when the print lowers its own temperature
- Start t2_target_drop, then run `$B guard 15` (background).
- The job heats to 210 C, then drops the target to 180 C while hot.
- PASS: the guard logs "ok" all the way through and exits 0 when the job ends (about 6 min). FAIL: it stops the job.

## T3 - the guard stops a job on its own
- Start t3_guard_stop, then run `NOZZLE_OVER=-100 $B guard 15` (fake fault: any normal temperature counts as overheating).
- PASS: within about 1 minute of heating the guard prints THERMAL ALARM, sends stop, exits with code 2, and the
  printer's state goes to FAILED/IDLE.
- Then follow the alarm procedure: camera frame + SendUserFile.

## T4 - spaghetti detection by camera
- Start t4_spaghetti. It prints a 20x20 mm pad, then extrudes about 25 cm of PLA in the air (real spaghetti),
  then parks at Z60 for 6 minutes.
- Take a camera frame every ~1 min. PASS: Claude correctly says "fine" during the pad, flags spaghetti
  after the air extrusion, and pauses. Also check that the frames during the pad do NOT cause a pause.
- Afterwards: `$B stop`, and clear the plate.

## Notes
- start3mf sends use_ams=false. If the filament is in the AMS lite, start it from Orca instead.
- The tests leave files on the printer's storage. Delete them in Orca's device file browser, or ask Claude to.
