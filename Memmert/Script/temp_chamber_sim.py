"""
Thermal Chamber Simulator for Testing ETA Models

Simulates realistic first-order exponential thermal dynamics:
    T(t) = T∞ + (T₀ - T∞) * e^(-t/τ)

Features:
- Variable time constants with per-run jitter (±15%)
- 100x time acceleration (complete cycles in ~1 min vs ~100 min)
- AtmoWEB-compatible REST API for drop-in controller testing
- Validates EKF tau learning and convergence behavior

Use with memmert_control_fast.py for rapid ETA model validation.
"""

import threading, time, math, random, json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Simulator settings (can be tuned)
HOST = "0.0.0.0"
PORT = 8000
BASE_PATH = "/atmoweb"

# Chamber capabilities
TEMP_MIN = 0.0
TEMP_MAX = 70.0

# Default time constants (minutes)
TAU_HEAT_MIN = 8.0
TAU_HEAT_MAX = 14.0
TAU_COOL_MIN = 10.0
TAU_COOL_MAX = 18.0

# Noise/drift (uncertainty)
TINFTY_DRIFT_MAX = 0.3   # +/- °C bounded drift around setpoint
TAU_JITTER = 0.15        # +/-15% multiplicative jitter

# Integration timestep and time scaling (simulate faster than real-time)
DT_S = 1.0
TIME_SCALE = 100.0  # 100x faster dynamics

class ChamberState:
    def __init__(self):
        self.lock = threading.Lock()
        self.temp = 22.0
        self.setpoint = 22.0
        self.cur_op = "Manual"
        self._tinf_drift = 0.0
        self._last_drift_update = 0.0

    def _pick_tau_min(self, heating: bool) -> float:
        base = (TAU_HEAT_MIN + TAU_HEAT_MAX)/2 if heating else (TAU_COOL_MIN + TAU_COOL_MAX)/2
        jitter = 1.0 + random.uniform(-TAU_JITTER, TAU_JITTER)
        return max(0.1, base * jitter)

    def _t_inf(self, heating: bool) -> float:
        # Base T∞ is the setpoint, perturbed by slow bounded drift
        now = time.time()
        # Update drift per simulated time (~30s), so scale the real threshold down
        if now - self._last_drift_update > (30.0 / max(1.0, TIME_SCALE)):
            # update every ~30s with small step
            self._tinf_drift += random.uniform(-0.05, 0.05)
            self._tinf_drift = max(-TINFTY_DRIFT_MAX, min(TINFTY_DRIFT_MAX, self._tinf_drift))
            self._last_drift_update = now
        t_inf = self.setpoint + self._tinf_drift
        return max(TEMP_MIN, min(TEMP_MAX, t_inf))

    def step(self, dt_s: float):
        with self.lock:
            heating = self.setpoint > self.temp
            tau_min = self._pick_tau_min(heating)  # minutes
            tau_s = tau_min * 60.0
            t_inf = self._t_inf(heating)
            a = math.exp(-dt_s / max(0.1, tau_s))
            self.temp = t_inf + (self.temp - t_inf) * a

    def set_temp(self, t: float):
        with self.lock:
            self.setpoint = max(TEMP_MIN, min(TEMP_MAX, float(t)))

    def snapshot(self):
        with self.lock:
            return {
                "Temp1Read": round(self.temp, 2),
                "TempSet": round(self.setpoint, 2),
                "TempSet_Range": {"min": TEMP_MIN, "max": TEMP_MAX},
                "CurOp": self.cur_op,
            }

STATE = ChamberState()

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # Quiet logs
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        # Honor base path prefix
        if not parsed.path.startswith(BASE_PATH):
            return self._send_json({"error": "not-found"}, 404)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        want_temp = "Temp1Read" in qs
        want_range = "TempSet_Range" in qs
        want_curop = "CurOp" in qs
        set_cmd = "TempSet" in qs

        # Apply set if present
        resp = {}
        if set_cmd:
            try:
                val = qs.get("TempSet", [None])[0]
                STATE.set_temp(float(val))
                resp["TempSet"] = STATE.snapshot()["TempSet"]
            except Exception:
                return self._send_json({"error": "bad-TempSet"}, 400)

        snap = STATE.snapshot()
        if want_temp:
            resp["Temp1Read"] = snap["Temp1Read"]
        if want_range:
            resp["TempSet_Range"] = snap["TempSet_Range"]
        if want_curop:
            resp["CurOp"] = snap["CurOp"]

        # If no specific keys requested, provide a minimal heartbeat
        if not (want_temp or want_range or want_curop or set_cmd):
            resp = {"ok": True, "Temp1Read": snap["Temp1Read"]}

        return self._send_json(resp)


def integrator_loop():
    while True:
        # Advance state by scaled timestep to simulate faster dynamics
        STATE.step(DT_S * TIME_SCALE)
        time.sleep(DT_S)


def main():
    import socket
    # Check if port is already in use
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1)
        test_sock.bind((HOST, PORT))
        test_sock.close()
    except OSError:
        print(f"[SIM] Temperature chamber simulator already running on port {PORT}. Exiting.")
        return
    
    print(f"[SIM] Temperature chamber simulator at http://127.0.0.1:{PORT}{BASE_PATH}")
    print("[SIM] Endpoints: ?Temp1Read=, ?TempSet_Range=, ?TempSet=XX, ?CurOp=")
    print(f"[SIM] Time scaling: x{TIME_SCALE}. Change BASE_URL to this address for local tests.")
    th = threading.Thread(target=integrator_loop, daemon=True)
    th.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SIM] Stopping...")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
