"""Generate the safety-test G-code files for the Bambu A1 (bed 256x256, PLA loaded).
Every file: low risk, short, ends by cooling down. Run: python3 make_tests.py"""
import math, os
HERE = os.path.dirname(os.path.abspath(__file__))
CX, CY = 128, 128

def head(nozzle, bed, wait_nozzle=True):
    g = ["; Claude printer-safety test - not a real print",
         "M17", "G90", "M83",                       # absolute XYZ, relative E
         f"M140 S{bed}", f"M104 S{nozzle}",
         "G28",                                      # home (A1 homes Z on the plate)
         "G1 Z40 F600"]
    if wait_nozzle: g.append(f"M109 S{nozzle}")
    return g

def tail():
    return ["M104 S0", "M140 S0", "M106 S0", "G1 Z60 F600", "G1 X0 Y250 F6000", "M84", "; end"]

def hold_moves(minutes, z=40, size=30):
    """Slow square moves in the air so the job stays RUNNING (no extrusion)."""
    g, per_lap = [], 4 * size / (1200 / 60)          # seconds per lap at F1200
    for _ in range(max(1, int(minutes * 60 / per_lap))):
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            g.append(f"G1 X{CX+dx*size/2:.1f} Y{CY+dy*size/2:.1f} Z{z} F1200")
    return g

def write(name, lines):
    p = os.path.join(HERE, name); open(p, "w").write("\n".join(lines) + "\n"); print("wrote", p, len(lines), "lines")

# T1: pause / resume / stop. Nozzle 150 C (PLA doesn't ooze), no extrusion, ~8 min of air moves.
write("t1_pause_resume_stop.gcode", head(150, 55) + hold_moves(8) + tail())

# T2: target drop must NOT trip the guard (false-positive check). 210 C, then drop target to 180 and hold.
write("t2_target_drop.gcode", head(210, 55) + ["G4 S20", "M104 S180"] + hold_moves(4) + tail())

# T3: guard trips and STOPS the job. Same harmless job as T1; the guard runs with NOZZLE_OVER=-100 so
#     any nozzle reading above (target-100) counts as a fault -> it must send STOP within ~1 minute.
write("t3_guard_stop.gcode", head(150, 55) + hold_moves(6) + tail())

# T4: real spaghetti for the camera check. 20x20 mm 2-layer pad in the middle, then extrude
#     ~250 mm of PLA while zig-zagging 25 mm in the air -> loose strands. Then hold 6 min for the camera check.
g = head(215, 55) + ["M190 S55", "M106 S255", "G1 Z0.3 F600", f"G1 X{CX-10} Y{CY-10} F3000"]
for layer, z in enumerate((0.3, 0.5)):
    g.append(f"G1 Z{z} F600")
    for i in range(0, 21, 1):                        # 1 mm raster lines
        y = CY - 10 + i
        x0, x1 = (CX - 10, CX + 10) if i % 2 == 0 else (CX + 10, CX - 10)
        g += [f"G1 X{x0} Y{y} F3000", f"G1 X{x1} Y{y} E{20*0.42*0.2*1.0/2.405:.4f} F1500"]
g += ["G1 Z25 F600"]
for i in range(60):                                  # air spaghetti
    a = i * 0.6
    g.append(f"G1 X{CX+15*math.cos(a):.1f} Y{CY+15*math.sin(a*1.3):.1f} E4.2 F2400")
g += ["G1 Z60 F600"] + hold_moves(6, z=60, size=20) + tail()
write("t4_spaghetti.gcode", g)

# Also wrap each test as a minimal .gcode.3mf (the format Orca sends), as a fallback if the
# printer refuses to start plain .gcode.
import zipfile, hashlib, glob
CT = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="gcode" ContentType="text/x.gcode"/></Types>'
RELS = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
MODEL = '<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build/></model>'
for gpath in sorted(glob.glob(os.path.join(HERE, "t*.gcode"))):
    data = open(gpath, "rb").read()
    out = gpath + ".3mf"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT); z.writestr("_rels/.rels", RELS); z.writestr("3D/3dmodel.model", MODEL)
        z.writestr("Metadata/plate_1.gcode", data)
        z.writestr("Metadata/plate_1.gcode.md5", hashlib.md5(data).hexdigest().upper())
    print("wrote", out)
