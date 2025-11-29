import requests, yaml, time, sys

BASE_URL = "http://192.168.96.21/atmoweb"
CFG = "IPP30_TEMP_CNTRL.yaml"

# Minimal controller for Memmert IPP30 via AtmoWEB.
# Exit codes: 1=error, 2=not manual, 3=no range

def cfg():
    """Load YAML config -> (target °C, wait min, tolerance °C)."""
    try:
        c = yaml.safe_load(open(CFG, "r", encoding="utf-8")) or {}
        return float(c["target_temperature"]), int(c.get("wait_time", 0)), float(c.get("tolerance", 0.5))
    except Exception as e:
        print(f"[ERROR] Config read: {e}"); sys.exit(1)

def mode():
    """Return device operating mode (expects 'Manual')."""
    r = requests.get(f"{BASE_URL}?CurOp=", timeout=5)
    if r.status_code != 200: print(f"[ERROR] HTTP {r.status_code}"); sys.exit(1)
    t = r.text.strip()
    if "CurOp=" in t: return t.split("CurOp=")[1].split("&")[0].strip()
    try: return str(r.json().get("CurOp",""))
    except: print("[ERROR] Parse mode"); sys.exit(1)

def state():
    """Fetch (Temp1Read, TempSet_Range). Exits if missing."""
    r = requests.get(f"{BASE_URL}?Temp1Read=&TempSet_Range=", timeout=5)
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
    r = requests.get(f"{BASE_URL}?TempSet={x}&Temp1Read=", timeout=5)
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

def main():
    """Main flow: check mode, validate target, set, monitor, wait."""
    tgt, wait_m, tol = cfg()
    if mode().lower() not in {"manual","man"}: print("[ERROR] Not in Manual"); sys.exit(2)
    cur, rng = state(); mn, mx = rng["min"], rng["max"]
    print(f"[INFO] Target {tgt} °C | Range {mn}–{mx} °C | Current {cur:.2f} °C | Tol ±{tol} °C")
    if not (mn <= tgt <= mx): print(f"[ERROR] Target {tgt} °C outside [{mn},{mx}]"); sys.exit(1)
    set_temp(tgt)
    print("[INFO] Monitoring …")
    while True:
        cur, _ = state(); print(f"[INFO] Current {cur:.2f} °C")
        if abs(cur - tgt) <= tol: print(f"[INFO] Target reached. Waiting {wait_m} min …"); break
        time.sleep(10)
    time.sleep(wait_m*60); print("[INFO] Complete.")

if __name__ == "__main__": main()
