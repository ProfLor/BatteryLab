import requests, yaml, time, sys

BASE_URL = "http://192.168.96.21/atmoweb"
CFG = "IPP30_TEMP_CNTRL.yaml"
TIMEOUT_S = 10
RETRIES = 3
RETRY_DELAY_S = 2

# Minimal controller for Memmert IPP30 via AtmoWEB.
# Exit codes: 1=error, 2=not manual, 3=no range

def cfg():
    """Load YAML config -> (target °C, wait min, tolerance °C)."""
    try:
        c = yaml.safe_load(open(CFG, "r", encoding="utf-8")) or {}
        return float(c["target_temperature"]), int(c.get("wait_time", 0)), float(c.get("tolerance", 0.5))
    except Exception as e:
        print(f"[ERROR] Config read: {e}"); sys.exit(1)

def _get(url, timeout=TIMEOUT_S):
    """HTTP GET with simple retry on connect/read timeouts. Returns Response or exits."""
    last_exc = None
    for i in range(1, RETRIES+1):
        try:
            return requests.get(url, timeout=timeout)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as e:
            last_exc = e
            print(f"[WARN] Timeout contacting device (attempt {i}/{RETRIES})")
            time.sleep(RETRY_DELAY_S)
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            print(f"[WARN] Connection error to device (attempt {i}/{RETRIES})")
            time.sleep(RETRY_DELAY_S)
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] HTTP request failed: {e}")
            sys.exit(1)
    print("[ERROR] Device not connected or unreachable after retries.")
    print("[HINT] Check network connection, IP 192.168.96.21, cable/power, and firewall.")
    sys.exit(1)

def check_device():
    """Quick preflight check to verify device is reachable."""
    try:
        r = requests.get(BASE_URL, timeout=3)
        # Even non-200 indicates host reachable; only network errors concern us
        return True
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        print("[ERROR] Memmert device appears disconnected or offline.")
        print("[HINT] Ensure the chamber is powered and connected; verify IP and VLAN.")
        sys.exit(1)

def mode():
    """Return device operating mode (expects 'Manual')."""
    r = _get(f"{BASE_URL}?CurOp=")
    if r.status_code != 200: print(f"[ERROR] HTTP {r.status_code}"); sys.exit(1)
    t = r.text.strip()
    if "CurOp=" in t: return t.split("CurOp=")[1].split("&")[0].strip()
    try: return str(r.json().get("CurOp",""))
    except: print("[ERROR] Parse mode"); sys.exit(1)

def state():
    """Fetch (Temp1Read, TempSet_Range). Exits if missing."""
    r = _get(f"{BASE_URL}?Temp1Read=&TempSet_Range=")
    if r.status_code != 200: print(f"[ERROR] HTTP {r.status_code}"); sys.exit(1)
    t = r.text.strip(); cur = None; rng = None
    try:
        d = r.json(); cur = float(d["Temp1Read"]) if "Temp1Read" in d else None
        rr = d.get("TempSet_Range");
        if isinstance(rr, dict) and "min" in rr and "max" in rr:
            rng = {"min": float(rr["min"]), "max": float(rr["max"])}
    except: 
        pass
    if cur is None and "Temp1Read=" in t:
        try: cur = float(t.split("Temp1Read=")[1].split("&")[0])
        except: pass
    if cur is None: print("[ERROR] No Temp1Read"); sys.exit(1)
    if rng is None: print("[ERROR] No TempSet_Range"); sys.exit(3)
    return cur, rng

def set_temp(x):
    """Set TempSet to x °C and print immediate readback."""
    r = _get(f"{BASE_URL}?TempSet={x}&Temp1Read=")
    if r.status_code != 200: print(f"[ERROR] HTTP {r.status_code}"); sys.exit(1)
    try:
        d = r.json(); sv = d.get("TempSet", x); cv = d.get("Temp1Read")
        print(f"[INFO] Set {sv} °C");
        if cv is not None: print(f"[INFO] Current {float(cv):.2f} °C")
    except:
        t = r.text.strip()
        if "TempSet=" in t:
            print(f"[INFO] Set {t.split('TempSet=')[1].split('&')[0]} °C")
        else:
            print(f"[INFO] Set {x} °C")

def progress_bar(current, target, start, width=20):
    """Generate progress bar showing temperature progress.
    Each character represents 5% of progress from start to target.
    """
    if abs(target - start) < 0.1:  # Avoid division by zero
        return "[" + "#" * width + "]"
    
    progress = (current - start) / (target - start)
    progress = max(0, min(1, progress))  # Clamp between 0 and 1
    filled = int(progress * width)
    bar = "#" * filled + "_" * (width - filled)
    return f"[{bar}]"

def estimate_eta(readings, target):
    """Estimate time to reach target using linear regression on recent readings.
    readings: list of (timestamp, temp) tuples
    Returns: estimated minutes to target, or None if insufficient data or moving away
    """
    if len(readings) < 3:
        return None
    
    # Use last N readings for trend (max 10 to adapt to recent behavior)
    window = readings[-10:]
    times = [(t - window[0][0]) / 60.0 for t, _ in window]  # minutes from first reading
    temps = [temp for _, temp in window]
    
    # Linear regression: temp = a * time + b
    n = len(times)
    sum_t = sum(times)
    sum_temp = sum(temps)
    sum_t2 = sum(t * t for t in times)
    sum_t_temp = sum(times[i] * temps[i] for i in range(n))
    
    denom = n * sum_t2 - sum_t * sum_t
    if abs(denom) < 1e-9:
        return None
    
    slope = (n * sum_t_temp - sum_t * sum_temp) / denom
    intercept = (sum_temp - slope * sum_t) / n
    
    # Check if we're moving toward target
    current_temp = temps[-1]
    delta = target - current_temp
    
    if abs(slope) < 0.01:  # Nearly flat, very slow change
        return None
    
    if (delta > 0 and slope < 0) or (delta < 0 and slope > 0):
        # Moving away from target
        return None
    
    # Estimate time from current point
    time_to_target = delta / slope
    return max(0, time_to_target)

def main():
    """Main flow: check mode, validate target, set, monitor, wait."""
    tgt, wait_m, tol = cfg()
    check_device()
    if mode().lower() not in {"manual","man"}: print("[ERROR] Not in Manual"); sys.exit(2)
    cur, rng = state(); mn, mx = rng["min"], rng["max"]
    print(f"[INFO] Target {tgt} °C | Range {mn}–{mx} °C | Current {cur:.2f} °C | Tol ±{tol} °C")
    if not (mn <= tgt <= mx): print(f"[ERROR] Target {tgt} °C outside [{mn},{mx}]"); sys.exit(1)
    set_temp(tgt)
    print("[INFO] Monitoring with 1-minute updates …")
    
    # Track temperature readings for trend analysis
    readings = []
    start_time = time.time()
    start_temp = cur  # Store initial temperature for progress calculation
    
    while True:
        cur, _ = state()
        current_time = time.time()
        readings.append((current_time, cur))
        
        # Estimate time to target
        eta_min = estimate_eta(readings, tgt)
        eta_str = f" | ETA ~{eta_min:.1f} min" if eta_min is not None else ""
        
        # Generate progress bar
        bar = progress_bar(cur, tgt, start_temp)
        
        print(f"[INFO] {bar} {cur:.2f} °C (Δ{cur-tgt:+.2f} °C){eta_str}")
        
        if abs(cur - tgt) <= tol:
            elapsed = (current_time - start_time) / 60
            print(f"[INFO] Target reached in {elapsed:.1f} minutes. Waiting {wait_m} min …")
            break
        
        time.sleep(60)  # Check every minute
    
    time.sleep(wait_m*60); print("[INFO] Complete.")

if __name__ == "__main__": main()
