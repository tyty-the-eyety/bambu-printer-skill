#!/usr/bin/env -S uv run --quiet --script
# /// script
# dependencies = ["paho-mqtt>=2"]
# ///
"""Bambu Lab printer (A1 / P1) local-network helper.

  bambu.py setup IP          save the printer's IP and serial (read from its certificate) to the config file
  bambu.py status            one status line (JSON)
  bambu.py camera OUT.jpg    save one camera frame
  bambu.py watch [SECS]      print status every SECS (default 120) until the job is no longer RUNNING
  bambu.py pause | resume | stop     send that command to the current print
  bambu.py ls                list files on the printer's storage
  bambu.py upload FILE       upload a file to the printer's storage (FTPS, port 990)
  bambu.py start NAME        start a plain .gcode already on the printer (the A1 refuses this: use start3mf)
  bambu.py start3mf NAME     start a .gcode.3mf already on the printer (plate 1, no AMS/levelling/timelapse)
  bambu.py guard [SECS] [--dry-run]  thermal watchdog: poll every SECS (default 30) while a job is
                             active; STOP the print on overheating, report firmware errors. Exits when
                             the job ends or after acting. --dry-run only reports what it would do.

Printer IP and serial come from BAMBU_IP / BAMBU_SERIAL, or from the config file written by `setup`
(~/.config/bambu-printer/config.json). If only the IP is known, the serial is read from the printer's
TLS certificate. The LAN access code is read at runtime from OrcaSlicer's config (never stored by
this tool), or from BAMBU_CODE if set.
"""
import json, os, socket, ssl, struct, sys, time, glob

CONFIG = os.path.expanduser(os.environ.get("BAMBU_CONFIG", "~/.config/bambu-printer/config.json"))

def load_config():
    try:
        return json.load(open(CONFIG))
    except (OSError, ValueError):
        return {}

def serial_from_cert(ip):
    """The printer's serial number is the CN of the TLS certificate it serves on port 8883."""
    s = tls_ctx().wrap_socket(socket.create_connection((ip, 8883), timeout=10), server_hostname=ip)
    der = s.getpeercert(binary_form=True); s.close()
    # The CN is stored as ASN.1 OID 2.5.4.3 followed by a string; find the last one (the subject's).
    oid = bytes([0x06, 0x03, 0x55, 0x04, 0x03])
    i = der.rfind(oid)
    if i < 0: sys.exit("could not read the serial from the printer's certificate; set BAMBU_SERIAL")
    n = der[i + len(oid) + 1]
    return der[i + len(oid) + 2 : i + len(oid) + 2 + n].decode()

_cfg = load_config()
IP = os.environ.get("BAMBU_IP") or _cfg.get("ip")
SERIAL = os.environ.get("BAMBU_SERIAL") or _cfg.get("serial")
ORCA_CONFS = [
    "~/.var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer/OrcaSlicer.conf",
    "~/.config/OrcaSlicer/OrcaSlicer.conf",
    "~/.var/app/io.github.softfever.OrcaSlicer/config/OrcaSlicer/OrcaSlicer.conf",
]

def access_code():
    if os.environ.get("BAMBU_CODE"):
        return os.environ["BAMBU_CODE"]
    def find(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "user_access_code" and isinstance(v, dict) and SERIAL in v:
                    return v[SERIAL]
                r = find(v)
                if r: return r
    for p in ORCA_CONFS:
        p = os.path.expanduser(p)
        if os.path.exists(p):
            c = find(json.load(open(p)))
            if c: return c
    sys.exit("No access code: connect the printer once in OrcaSlicer, or set BAMBU_CODE")

def tls_ctx():
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    return ctx

KEYS = ["gcode_state", "subtask_name", "mc_percent", "mc_remaining_time", "layer_num", "total_layer_num",
        "nozzle_temper", "nozzle_target_temper", "bed_temper", "bed_target_temper", "print_error", "spd_lvl"]

def status(code, wait=6):
    import paho.mqtt.client as mqtt
    state = {}
    def on_connect(c, u, f, rc, props=None):
        c.subscribe(f"device/{SERIAL}/report")
        c.publish(f"device/{SERIAL}/request", json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
    def on_message(c, u, m):
        p = json.loads(m.payload).get("print", {})
        state.update({k: v for k, v in p.items() if not isinstance(v, (dict, list))})
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set("bblp", code); c.tls_set_context(tls_ctx())
    c.on_connect = on_connect; c.on_message = on_message
    c.connect(IP, 8883, 30); c.loop_start(); time.sleep(wait); c.loop_stop()
    return {k: state.get(k) for k in KEYS}

def camera(code, out):
    s = tls_ctx().wrap_socket(socket.create_connection((IP, 6000), timeout=10), server_hostname=IP)
    s.sendall(struct.pack("<IIII", 0x40, 0x3000, 0, 0) + b"bblp".ljust(32, b"\0") + code.encode().ljust(32, b"\0"))
    def readn(n):
        b = b""
        while len(b) < n:
            d = s.recv(n - len(b))
            if not d: sys.exit("camera connection closed")
            b += d
        return b
    size = struct.unpack("<I", readn(16)[:4])[0]
    img = readn(size)
    if img[:2] != b"\xff\xd8": sys.exit("camera did not return a JPEG")
    open(out, "wb").write(img); print("saved", out)

def ftp(code):
    import ftplib
    class ImplicitFTPS(ftplib.FTP_TLS):
        # the printer uses implicit TLS: wrap the socket before the greeting
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self._sock = None
        @property
        def sock(self): return self._sock
        @sock.setter
        def sock(self, value):
            if value is not None and not isinstance(value, ssl.SSLSocket):
                value = self.context.wrap_socket(value, server_hostname=IP)
            self._sock = value
        def ntransfercmd(self, cmd, rest=None):
            conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
            if self._prot_p:
                conn = self.context.wrap_socket(conn, server_hostname=IP, session=self.sock.session)
            return conn, size
    f = ImplicitFTPS(context=tls_ctx(), timeout=20)
    f.connect(IP, 990); f.login("bblp", code); f.prot_p()
    return f

def send_print(code, payload, verify=True):
    """Publish a {"print": payload} request once connected; return the printer's matching reply (or None)."""
    import paho.mqtt.client as mqtt, threading
    connected, reply = threading.Event(), {}
    cmd = payload.get("command")
    def on_connect(c, u, f, rc, props=None):
        c.subscribe(f"device/{SERIAL}/report"); connected.set()
    def on_message(c, u, m):
        p = json.loads(m.payload).get("print", {})
        if p.get("command") == cmd and "result" in p: reply.update(p)
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.username_pw_set("bblp", code); c.tls_set_context(tls_ctx())
    c.on_connect = on_connect; c.on_message = on_message
    c.connect(IP, 8883, 30); c.loop_start()
    try:
        if not connected.wait(15): sys.exit("could not connect to printer MQTT")
        c.publish(f"device/{SERIAL}/request", json.dumps({"print": payload}))
        for _ in range(16):
            if reply: break
            time.sleep(0.5)
    finally:
        c.loop_stop(); c.disconnect()
    return reply or None

def send(code, command):
    r = send_print(code, {"sequence_id": "0", "command": command, "param": ""})
    print("sent", command, "| printer reply:", (r or {}).get("result", "none"), (r or {}).get("reason", ""), flush=True)

# Thermal limits (defaults suit the A1: max nozzle 300 C, max bed 100 C).
# All limits can be overridden with env vars of the same name (used by the test plan).
NOZZLE_OVER = float(os.environ.get("NOZZLE_OVER", 15))   # C above target
BED_OVER    = float(os.environ.get("BED_OVER", 10))
NOZZLE_ABS  = float(os.environ.get("NOZZLE_ABS", 305))
BED_ABS     = float(os.environ.get("BED_ABS", 105))
IDLE_RISE   = 5     # C rise between polls while the heater target is 0
STRIKES     = 2     # consecutive bad readings needed before acting (avoids one-off glitches)

def thermal_problem(prev, st):
    n, nt = st["nozzle_temper"] or 0, st["nozzle_target_temper"] or 0
    b, bt = st["bed_temper"] or 0, st["bed_target_temper"] or 0
    if n > NOZZLE_ABS: return f"nozzle {n:.0f}C above absolute limit"
    if b > BED_ABS: return f"bed {b:.0f}C above absolute limit"
    # Over target only counts if the temperature is not falling: a print that lowers its own
    # target (e.g. after the first layer) is briefly above target while it cools - that's fine.
    pn = (prev or {}).get("nozzle_temper") or 0
    pb = (prev or {}).get("bed_temper") or 0
    # ...and a reading taken right after the target changed doesn't count either (cooling hasn't started yet).
    nt_changed = prev is not None and (prev.get("nozzle_target_temper") or 0) != nt
    bt_changed = prev is not None and (prev.get("bed_target_temper") or 0) != bt
    if nt > 0 and n > nt + NOZZLE_OVER and not nt_changed and (not prev or n >= pn - 0.5): return f"nozzle {n:.0f}C, target {nt:.0f}C, not cooling"
    if bt > 0 and b > bt + BED_OVER and not bt_changed and (not prev or b >= pb - 0.5): return f"bed {b:.0f}C, target {bt:.0f}C, not cooling"
    if prev:
        if nt == 0 and n > 60 and n - (prev["nozzle_temper"] or 0) > IDLE_RISE: return f"nozzle heating to {n:.0f}C with heater off"
        if bt == 0 and b > 40 and b - (prev["bed_temper"] or 0) > IDLE_RISE: return f"bed heating to {b:.0f}C with heater off"
    return None

def guard(code, every, dry):
    prev, strikes = None, 0
    while True:
        st = status(code, wait=4)
        stamp = time.strftime("%H:%M:%S")
        if st["gcode_state"] is None:
            print(stamp, "no data from printer", flush=True); time.sleep(every); continue
        prob = thermal_problem(prev, st)
        strikes = strikes + 1 if prob else 0
        print(stamp, st["gcode_state"], f'{st["mc_percent"]}%', f'nozzle {st["nozzle_temper"]}/{st["nozzle_target_temper"]}',
              f'bed {st["bed_temper"]}/{st["bed_target_temper"]}', f"PROBLEM: {prob} ({strikes}/{STRIKES})" if prob else "ok", flush=True)
        if strikes >= STRIKES:
            print("THERMAL ALARM:", prob, flush=True)
            if not dry: send(code, "stop")
            else: print("dry-run: would send stop", flush=True)
            return 2
        if st["print_error"]:
            print("PRINTER ERROR CODE:", st["print_error"], "(the firmware handles it; check the printer)", flush=True)
            return 3
        if st["gcode_state"] not in ("RUNNING", "PREPARE", "PAUSE", "SLICING"):
            print("job not active:", st["gcode_state"], flush=True)
            return 0
        prev = st
        time.sleep(every)

def main():
    global SERIAL
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd in ("-h", "--help", "help"):
        sys.exit(__doc__)

    if cmd == "setup":
        if len(sys.argv) < 3: sys.exit("usage: bambu.py setup PRINTER_IP")
        ip = sys.argv[2]; serial = serial_from_cert(ip)
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        json.dump({"ip": ip, "serial": serial}, open(CONFIG, "w"), indent=2)
        print(f"saved {CONFIG}: ip {ip}, serial {serial}")
        sys.exit(0)
    if not IP:
        sys.exit("Printer IP unknown: run `bambu.py setup PRINTER_IP` or set BAMBU_IP")
    if not SERIAL:
        SERIAL = serial_from_cert(IP)
    code = access_code()
    if cmd == "status":
        print(json.dumps(status(code)))
    elif cmd == "camera":
        camera(code, sys.argv[2] if len(sys.argv) > 2 else "printer.jpg")
    elif cmd == "watch":
        every = float(sys.argv[2]) if len(sys.argv) > 2 else 120
        while True:
            st = status(code)
            print(time.strftime("%H:%M"), json.dumps(st), flush=True)
            if st["gcode_state"] != "RUNNING" or st["print_error"]:
                break
            time.sleep(every)
    elif cmd == "ls":
        f = ftp(code); print("\n".join(f.nlst())); f.quit()
    elif cmd == "upload":
        path = sys.argv[2]; f = ftp(code)
        # Bambu's FTPS never answers the TLS shutdown after a STOR, so send without unwrap()
        f.voidcmd("TYPE I")
        conn = f.transfercmd("STOR " + os.path.basename(path))
        with open(path, "rb") as fh:
            while chunk := fh.read(65536): conn.sendall(chunk)
        conn.close(); f.voidresp()
        f.quit(); print("uploaded", os.path.basename(path))
    elif cmd == "start":
        name = os.path.basename(sys.argv[2])
        r = send_print(code, {"sequence_id": "0", "command": "gcode_file", "param": f"/sdcard/{name}"})
        print("sent start for", name, "| printer reply:", r, "- check `status` in ~20 s")
    elif cmd == "start3mf":
        name = os.path.basename(sys.argv[2])
        r = send_print(code, {"sequence_id": "0", "command": "project_file", "param": "Metadata/plate_1.gcode",
                          "url": f"file:///sdcard/{name}", "subtask_name": name, "md5": "",
                          "use_ams": False, "timelapse": False, "bed_leveling": False, "bed_type": "auto",
                          "flow_cali": False, "vibration_cali": False, "layer_inspect": False,
                          "profile_id": "0", "project_id": "0", "subtask_id": "0", "task_id": "0"})
        print("sent start for", name, "| printer reply:", r, "- check `status` in ~20 s")
    elif cmd in ("pause", "resume", "stop"):
        send(code, cmd)
    elif cmd == "guard":
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        sys.exit(guard(code, float(args[0]) if args else 30, "--dry-run" in sys.argv))
    else:
        sys.exit(__doc__)

if __name__ == "__main__":
    try:
        main()
    except (OSError, socket.timeout) as e:
        sys.exit(f"Could not reach the printer at {IP or sys.argv[2:3]}: {e}. Is it on and on this network?")
