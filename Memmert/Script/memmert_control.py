def check_manual_mode():
    """Check if device is in Manual mode. If not, prompt user to abort current operation and switch to Manual."""
    r = http_get(f"{BASE_URL}?CurOp=")
    if r.status_code != 200:
        raise DeviceError(f"HTTP {r.status_code} on CurOp query")
    txt = r.text.strip()
    if 'Manual' in txt:
        return True
    # Extract mode string for user
    mode = txt
    print(f"[WARN] Device is currently in mode: {mode}")
    ans = input("Do you want to abort the current operation and switch to Manual mode to start heating/cooling? (y/n): ").strip().lower()
    if ans == 'y':
        print("[INFO] Sending abort command to device...")
        r_abort = http_get(f"{BASE_URL}?ProgExit=")
        if r_abort.status_code != 200:
            raise DeviceError(f"Failed to abort program: HTTP {r_abort.status_code}")
        time.sleep(2)  # Give device time to switch
        # Re-check mode
        r2 = http_get(f"{BASE_URL}?CurOp=")
        txt2 = r2.text.strip()
        if 'Manual' in txt2:
            print("[INFO] Device is now in Manual mode.")
            return True
        else:
            raise DeviceError(f"Device did not switch to Manual mode (CurOp={txt2})")
    else:
        raise DeviceError(f"User aborted: Device is in mode {mode}")
import requests, yaml, time, sys, math
try: import numpy as np
except: np = None

# Production controller for Memmert IPP30 temperature chamber
BASE_URL="http://192.168.96.21/atmoweb"; CFG="IPP30_TEMP_CNTRL.yaml"
TIMEOUT_S=10; RETRIES=3; RETRY_DELAY_S=2
TARGET_THRESHOLD=0.1  # °C threshold for "target reached"

class ConfigError(Exception): pass
class DeviceError(Exception): pass

def cfg():
    """Load config: returns (target, wait_min, tolerance, config_dict)"""
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            c = yaml.safe_load(f) or {}
    except Exception as e:
        raise ConfigError(f"Failed to load {CFG}: {e}")

    # Extract sections
    device = c.get("device", {})
    eta_model = c.get("eta_model", {})
    logging_cfg = c.get("logging", {})

    wait_s = int(device.get("wait_s", 60))
    tol = float(device.get("tolerance", 0.5))
    dt_s = float(logging_cfg.get("dt_s", 60))
    dt_logfile_s = float(logging_cfg.get("dt_logfile_s", 10))

    # Ensure tau_info keys exist for persistence
    for k in ["tau_heating_info", "tau_cooling_info"]:
        if k not in eta_model:
            eta_model[k] = ''

    if "target_temperatures" in device:
        temps = device["target_temperatures"]
        if not temps or not isinstance(temps, list):
            raise ConfigError("target_temperatures must be non-empty list")
        idx = int(device.get("current_set_index", 0))
        if not (0 <= idx < len(temps)):
            raise ConfigError(f"current_set_index {idx} out of range [0,{len(temps)-1}]")
        # Merge all config for downstream use
        merged = {"temps": temps, "idx": idx, "c": {**device, **eta_model, **logging_cfg}, "dt_s": dt_s, "dt_logfile_s": dt_logfile_s, "device": device, "eta_model": eta_model, "logging": logging_cfg}
        return float(temps[idx]), wait_s, tol, merged

    if "target_temperature" not in device:
        raise ConfigError("Missing both target_temperatures and target_temperature in device section")
    merged = {"temps": [device["target_temperature"]], "idx": 0, "c": {**device, **eta_model, **logging_cfg}, "dt_s": dt_s, "dt_logfile_s": dt_logfile_s, "device": device, "eta_model": eta_model, "logging": logging_cfg}
    return float(device["target_temperature"]), wait_s, tol, merged

def http_get(url):
    """HTTP GET with retry logic"""
    for i in range(1,RETRIES+1):
        try: return requests.get(url,timeout=TIMEOUT_S)
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
            if i<RETRIES: print(f"[WARN] Retry {i}/{RETRIES}"); time.sleep(RETRY_DELAY_S)
            else: raise DeviceError(f"Device unreachable after {RETRIES} retries")
        except requests.exceptions.RequestException as e:
            raise DeviceError(f"HTTP request failed: {e}")

def get_state():
    """Returns (current_temp, range_dict)"""
    r=http_get(f"{BASE_URL}?Temp1Read=&TempSet_Range=")
    if r.status_code!=200:
        raise DeviceError(f"HTTP {r.status_code}")
    try:
        d=r.json()
        cur=float(d["Temp1Read"])
        rng={"min":float(d["TempSet_Range"]["min"]),"max":float(d["TempSet_Range"]["max"])}
        return cur,rng
    except Exception as e:
        txt = r.text.strip()
        # Fallback: parse AtmoWEB-style response
        try:
            # Example: '"Temp1Read": 19.531, TempSet_Range=unknown'
            cur = None
            if "Temp1Read" in txt:
                # Handles both '"Temp1Read": 19.531' and 'Temp1Read=19.531'
                import re
                m = re.search(r'Temp1Read[":=\s]*([0-9.]+)', txt)
                if m:
                    cur = float(m.group(1))
            rng = {"min": 0.0, "max": 70.0}  # fallback/default
            if cur is not None:
                return cur, rng
            else:
                raise DeviceError("No Temp1Read in device response")
        except Exception as e2:
            raise DeviceError(f"Invalid device response (unparsable): {e2}")

def set_target(temp):
    """Set target temperature"""
    r=http_get(f"{BASE_URL}?TempSet={temp}")
    if r.status_code!=200:
        raise DeviceError(f"Failed to set target: HTTP {r.status_code}")

def progress_bar(cur,tgt,start,w=20):
    """Progress bar from start to target"""
    if abs(tgt-start)<0.1: return "["+"#"*w+"]"
    p=max(0,min(1,(cur-start)/(tgt-start))); f=int(p*w)
    return f"[{'#'*f}{'_'*(w-f)}]"

def estimate_eta_ekf(readings, target, tau_h, tau_c, dt):
    """Extended Kalman Filter for tau, T_infty estimation and ETA prediction"""
    if np is None or len(readings) < 2:
        return None, {}
    # Use last 20 samples for smoother estimation
    w = readings[-20:]
    temps = [x for _, x in w]
    T0, cur = temps[0], temps[-1]
    # Outlier detection: skip update if latest reading is a robust outlier
    if len(temps) > 5:
        med = np.median(temps)
        mad = np.median(np.abs(temps - med))
        if mad < 1e-6:
            mad = 1e-6  # avoid div by zero
        z = 0.6745 * (cur - med) / mad
        if abs(z) > 4:  # robust z-score threshold (4 = very conservative)
            # Outlier detected, skip update
            return None, {}
    heating = target > cur
    tau0 = tau_h if heating else tau_c
    Tinf0 = float(target)
    # 3-state EKF: [T_current, tau, T_infty]
    x = np.array([T0, tau0, Tinf0], dtype=float)
    P = np.diag([10.0, 2.0, 5.0])
    # Smoother process noise for tau and Tinf
    Q = np.diag([0.05 ** 2, 0.001 ** 2, 0.002 ** 2])
    R = 0.1 ** 2
    H = np.array([1.0, 0.0, 0.0])
    for i in range(1, len(temps)):
        Tm, Tp = temps[i], temps[i - 1]
        tau_k = max(x[1], 1e-3)
        Tinf_k = x[2]
        a = np.exp(-dt / tau_k)
        # Jacobian: ∂T/∂τ = (dt/τ²)(Tp-Tinf)e^(-dt/τ), ∂T/∂Tinf = 1-e^(-dt/τ)
        A = np.array([
            [a, (dt / tau_k ** 2) * (Tp - Tinf_k) * a, 1 - a],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        # Predict
        x_pred = np.array([a * Tp + (1 - a) * Tinf_k, x[1], x[2]])
        P_pred = A @ P @ A.T + Q
        # Update with gain limiting
        K = (P_pred @ H) / (H @ P_pred @ H + R)
        # Limit tau and Tinf gain
        K_lim = np.array([K[0], np.clip(K[1], -0.5, 0.5), np.clip(K[2], -0.2, 0.2)])
        x = x_pred + K_lim * (Tm - H @ x_pred)
        P = P_pred - np.outer(K_lim, K_lim) * (H @ P_pred @ H + R)
        P = 0.5 * (P + P.T)  # Enforce symmetry
        P[P < 1e-6] = 1e-6  # Prevent negative eigenvalues
    tau = max(float(x[1]), 1e-3)
    Tinf = float(x[2])
    err = abs(cur - Tinf)
    if err < 0.1:
        return 0.0, {"tau": tau, "Tinf": Tinf}
    return max(0.0, -tau * np.log(0.1 / err)), {"tau": tau, "Tinf": Tinf}

def estimate_eta_exp(readings,target,tau_h,tau_c,tol):
    """Exponential model with fixed tau from config (no fitting)"""
    if not readings: return None,{}
    w=readings[-10:]; T0,cur=w[0][1],w[-1][1]
    heating=target>cur; Tinf=float(target)
    tau=float(tau_h if heating else tau_c)
    err=abs(cur-Tinf)
    if err<0.1: return 0.0,{"tau":tau}
    return max(0.0,-tau*math.log(0.1/err)),{"tau":tau}

def write_config(temps,idx,c):
    """Write config YAML with all sections"""
    # Only update tau_heating (+info) after heating, tau_cooling (+info) after cooling, and current_set_index
    import yaml
    # Load existing config to preserve all other settings/structure
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[WARN] Could not load config for update: {e}")
        return

    # Update only the relevant fields
    if 'device' not in config:
        config['device'] = {}
    config['device']['target_temperatures'] = [float(t) for t in temps]
    config['device']['current_set_index'] = idx
    # Only update tau_heating/info or tau_cooling/info if present in c
    if 'eta_model' not in config:
        config['eta_model'] = {}
    if 'tau_heating' in c:
        config['eta_model']['tau_heating'] = float(c.get('tau_heating', 10.0))
    if 'tau_heating_info' in c:
        config['eta_model']['tau_heating_info'] = c.get('tau_heating_info', '')
    if 'tau_cooling' in c:
        config['eta_model']['tau_cooling'] = float(c.get('tau_cooling', 10.0))
    if 'tau_cooling_info' in c:
        config['eta_model']['tau_cooling_info'] = c.get('tau_cooling_info', '')
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            yaml.dump(config, f, sort_keys=False, allow_unicode=True)
    except Exception as e:
        print(f"[WARN] Config write failed: {e}")

def log_run(start_temp,tgt,final_tau,em,heating):
    """Log completed run to CSV history"""
    import os
    ts_full = time.strftime("%Y-%m-%d_%H-%M-%S")
    date_str = time.strftime("%Y-%m-%d")
    time_str = time.strftime("%H:%M:%S")
    model = "EKF" if em==2 else "EXP"
    mode = "heating" if heating else "cooling"
    # --- Per-run detailed log ---
    log_dir = os.path.join(os.path.dirname(__file__), "log-files")
    os.makedirs(log_dir, exist_ok=True)
    log_filename = f"{ts_full}_{start_temp:.1f}_{tgt:.1f}.csv"
    log_path = os.path.join(log_dir, log_filename)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            # Write header with metadata
            f.write(f"# Memmert IPP30 Run Log\n")
            f.write(f"# Date: {date_str}\n")
            f.write(f"# Start Time: {time_str}\n")
            f.write(f"# Start Temperature (°C): {start_temp:.2f}\n")
            f.write(f"# Target Temperature (°C): {tgt:.2f}\n")
            f.write(f"# ETA Model: {model}\n")
            f.write(f"# Mode: {mode}\n")
            f.write(f"# Wait Time (min): {int(cfg().c.get('wait_time',0))}\n")
            f.write(f"# Tolerance (°C): {float(cfg().c.get('tolerance',0.5))}\n")
            f.write(f"# Sampling Interval (min): {float(cfg().c.get('dt_minutes',1.0))}\n")
            f.write(f"# Setpoint Index: {cfg().c.get('current_set_index',0)}\n")
            f.write(f"# Temperature Range (min-max °C): {cfg()[3]['c'].get('min',0.0)}–{cfg()[3]['c'].get('max',70.0)}\n")
            f.write(f"# Notes: \n")
            f.write("Timestamp,Elapsed_min,Temperature,ETA_min,Tau_min,Progress_pct\n")
            # Write sample data if available (optional: could be passed in future)
    except Exception as e:
        print(f"[WARN] Per-run log failed: {e}")
    # --- Global tau lookup table ---
    lookup_path = os.path.join(os.path.dirname(__file__), "lookup_tau.csv")
    try:
        with open(lookup_path, "a", encoding="utf-8") as f:
            if f.tell()==0:
                f.write("Date,Start_Temp,Target_Temp,Mode,Tau_min,ETA_Model,Wait_min,Tolerance,dt_min,Num_Samples,Notes\n")
            f.write(f"{date_str},{start_temp:.2f},{tgt:.2f},{mode},{final_tau:.2f},{model},{int(cfg().c.get('wait_time',0))},{float(cfg().c.get('tolerance',0.5))},{float(cfg().c.get('dt_minutes',1.0))},,\n")
    except Exception as e:
        print(f"[WARN] Tau lookup log failed: {e}")

def maybe_update_tau(c,cfg_obj,heating,tau_h_est,tau_c_est,start_temp):
    """Update tau in config if tau_override enabled and starting from ambient"""
    if int(c.get('tau_override',0))==1 and cfg_obj['idx']==0:
        final_tau=tau_h_est if heating else tau_c_est
        ts=time.strftime("%Y-%m-%d %H:%M:%S")
        key,info_key=("tau_heating","tau_heating_info") if heating else ("tau_cooling","tau_cooling_info")
        print(f"[INFO] Updating {key} to {final_tau:.2f}m (learned from EKF)")
        c[key],c[info_key]=final_tau,f"Updated {ts} | Start T={start_temp:.1f}°C"

def run_single_setpoint(tgt,wait_m,tol,cfg_obj):
    """Execute control loop for one setpoint"""
    c = cfg_obj['c']
    cur, rng = get_state(); mn, mx = rng['min'], rng['max']
    print(f"[INFO] Target {tgt}°C | Range {mn}–{mx}°C | Current {cur:.2f}°C | Tol ±{tol}°C")
    if not (mn <= tgt <= mx):
        raise ConfigError(f"Target {tgt}°C outside valid range [{mn},{mx}]")

    set_target(tgt)
    dt_s = float(cfg_obj.get('dt_s', 60))
    dt_logfile_s = float(cfg_obj.get('dt_logfile_s', 10))
    tau_h = float(cfg_obj.get('eta_model', {}).get('tau_heating', 10.0))
    tau_c = float(cfg_obj.get('eta_model', {}).get('tau_cooling', 10.0))
    sleep_s = max(1, dt_s)
    start_temp = cur
    em = int(cfg_obj.get('eta_model', {}).get('model_type', 1))

    if em == 2:
        print("[INFO] ETA Model: Extended Kalman Filter (EKF) | T(t)=T∞+(T₀-T∞)e^(-t/τ)")
    else:
        print(f"[INFO] ETA Model: Exponential | T(t)=T∞+(T₀-T∞)e^(-t/τ), τ={(tau_h if tgt > start_temp else tau_c):.2f}m")
    print(f"[INFO] Monitoring with {dt_s:.1f}s updates …")

    readings = []
    start = time.time()
    tau_h_est, tau_c_est = tau_h, tau_c
    tau_last = tau_h if tgt > start_temp else tau_c

    # Prepare per-run log file for appending sample data
    import os
    ts_full = time.strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = os.path.join(os.path.dirname(__file__), "log-files")
    log_filename = f"{ts_full}_{start_temp:.1f}_{tgt:.1f}.csv"
    log_path = os.path.join(log_dir, log_filename)
    # Write header if file does not exist
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Memmert IPP30 Run Log\n")
            f.write(f"# Date: {time.strftime('%Y-%m-%d')}\n")
            f.write(f"# Start Time: {time.strftime('%H:%M:%S')}\n")
            f.write(f"# Start Temperature (°C): {start_temp:.2f}\n")
            f.write(f"# Target Temperature (°C): {tgt:.2f}\n")
            f.write(f"# ETA Model: {'EKF' if em==2 else 'EXP'}\n")
            f.write(f"# Mode: {'heating' if tgt>start_temp else 'cooling'}\n")
            f.write(f"# Wait Time (s): {int(cfg_obj.get('device',{}).get('wait_s',60))}\n")
            f.write(f"# Tolerance (°C): {float(cfg_obj.get('device',{}).get('tolerance',0.5))}\n")
            f.write(f"# Sampling Interval (s): {dt_s}\n")
            f.write(f"# Log File Sampling Interval (s): {dt_logfile_s}\n")
            f.write(f"# Setpoint Index: {cfg_obj['idx']}\n")
            f.write(f"# Notes: \n")
            f.write("Timestamp,Elapsed_s,Temperature,ETA_min,Tau_min,Progress_pct\n")
            f.write("hh:mm:ss,s,°C,min,min,%\n")

    # Decouple device polling (dt_s) from log writing (dt_logfile_s)
    last_log_t = start - dt_logfile_s  # ensure first sample is logged
    next_poll_t = start
    cur = None
    eta = None
    tag = ''
    tau_show = tau_last
    Tinf_show = tgt
    param_str = ''
    while True:
        now = time.time()
        # Poll device if it's time
        if now >= next_poll_t or cur is None:
            cur, _ = get_state()
            readings.append((now, cur))
            if em == 2:
                eta, ex = estimate_eta_ekf(readings, tgt, tau_h_est, tau_c_est, dt_s / 60.0)
                tag = '[EKF]'
                tau_show = ex.get('tau', tau_h if tgt > start_temp else tau_c)
                Tinf_show = ex.get('Tinf', tgt)
                if tau_show > 0.1:
                    if tgt > start_temp:
                        tau_h_est = tau_show
                    else:
                        tau_c_est = tau_show
                tau_last = tau_show
                eta_str = f"ETA~{eta:.1f}m" if eta else "ETA~--"
                param_str = f" τ={tau_show:.2f}m T∞={Tinf_show:.2f}°C"
            else:
                eta, ex = estimate_eta_exp(readings, tgt, tau_h, tau_c, tol)
                tag = '[EXP]'
                tau_last = tau_h if tgt > start_temp else tau_c
                Tinf_show = tgt
                eta_str = f"ETA~{eta:.1f}m" if eta else "ETA~--"; param_str = f" T∞={Tinf_show:.2f}°C"
            next_poll_t += dt_s
        ts_disp = time.strftime("%H:%M:%S", time.localtime(now))
        elapsed_s = now - start
        progress = 100.0 * max(0, min(1, (cur - start_temp) / (tgt - start_temp))) if abs(tgt - start_temp) > 1e-6 else 100.0
        print(f"[INFO] {ts_disp} {progress_bar(cur, tgt, start_temp)} {tag} {eta_str} | T={cur:.2f}°C{param_str}")
        # Log sample if enough time has passed
        if now - last_log_t >= dt_logfile_s:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{ts_disp},{elapsed_s:.1f},{cur:.3f},{eta if eta is not None else ''},{tau_last:.3f},{progress:.1f}\n")
            last_log_t += dt_logfile_s
        # Hybrid criterion: must be within tolerance of Tinf AND at least 5*tau (latest) elapsed
        if abs(cur - Tinf_show) <= tol and elapsed_s >= 5 * float(tau_last) * 60.0:
            print(f"[INFO] Target reached (within ±{tol}°C of T∞={Tinf_show:.2f}°C and >5τ) in {elapsed_s/60.0:.1f}m. Waiting {int(cfg_obj.get('device',{}).get('wait_s',60))}s …")
            break
        # Sleep until next event (poll or log)
        sleep_until = min(next_poll_t, last_log_t + dt_logfile_s)
        time.sleep(max(0.1, sleep_until - time.time()))

    time.sleep(int(cfg_obj.get('device',{}).get('wait_s',60)))
    print("[INFO] Complete.")
    
    # Log and update
    heating=tgt>start_temp; final_tau=tau_h_est if heating else tau_c_est
    log_run(start_temp,tgt,final_tau,em,heating)
    maybe_update_tau(c,cfg_obj,heating,tau_h_est,tau_c_est,start_temp)
    
    # Advance setpoint if needed
    temps,idx=cfg_obj['temps'],cfg_obj['idx']
    if len(temps)>1 or int(c.get('tau_override',0))==1:
        ni=(idx+1)%len(temps) if len(temps)>1 else idx
        if len(temps)>1: print(f"[INFO] Advancing set index {idx}->{ni}")
        write_config(temps,ni,c)

def main():
    try:
        tgt,wait_m,tol,cfg_obj=cfg()
        check_manual_mode()
        run_single_setpoint(tgt,wait_m,tol,cfg_obj)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user. Shutting down cleanly.")
        sys.exit(130)
    except (ConfigError,DeviceError) as e:
        print(f"[ERROR] {e}")
        print("[ERROR] Exit code 1: Device not connected or not responding.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        print("[ERROR] Exit code 1: Device not connected or not responding.")
        sys.exit(1)

if __name__ == "__main__":
    main()
