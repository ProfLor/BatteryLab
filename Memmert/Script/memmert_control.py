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
            raise ManualModeError(f"Device did not switch to Manual mode (CurOp={txt2})")
    else:
        raise ManualModeError(f"User aborted: Device is in mode {mode}")
import requests, yaml, time, sys, math
try: 
    import numpy as np
    from thermal_estimator import ThermalEstimator
except ImportError as e:
    np = None
    print(f"[WARN] Could not import required modules: {e}")

# Production controller for Memmert IPP30 temperature chamber
BASE_URL="http://192.168.96.21/atmoweb"; CFG="IPP30_TEMP_CNTRL.yaml"
TIMEOUT_S=10; RETRIES=3; RETRY_DELAY_S=2
TARGET_THRESHOLD=0.1  # °C threshold for "target reached"

class ConfigError(Exception): pass
class DeviceError(Exception): pass
class ManualModeError(Exception): pass

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
        # Load EKF parameters if present
        ekf_params = c.get("ekf", {})
        # Merge all config for downstream use
        merged = {"temps": temps, "idx": idx, "c": {**device, **eta_model, **logging_cfg}, "dt_s": dt_s, "dt_logfile_s": dt_logfile_s, "device": device, "eta_model": eta_model, "logging": logging_cfg, "ekf": ekf_params}
        return float(temps[idx]), wait_s, tol, merged

    if "target_temperature" not in device:
        raise ConfigError("Missing both target_temperatures and target_temperature in device section")
    ekf_params = c.get("ekf", {})
    merged = {"temps": [device["target_temperature"]], "idx": 0, "c": {**device, **eta_model, **logging_cfg}, "dt_s": dt_s, "dt_logfile_s": dt_logfile_s, "device": device, "eta_model": eta_model, "logging": logging_cfg, "ekf": ekf_params}
    return float(device["target_temperature"]), wait_s, tol, merged

def http_get(url):
    """HTTP GET with retry logic"""
    for i in range(1,RETRIES+1):
        try: return requests.get(url,timeout=TIMEOUT_S)
        except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as e:
            if i<RETRIES: print(f"[WARN] Retry {i}/{RETRIES}"); time.sleep(RETRY_DELAY_S)
            else: raise ConnectionError(f"Device unreachable after {RETRIES} retries")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"HTTP request failed: {e}")

def get_state():
    """Returns (current_temp, range_dict)"""
    r = http_get(f"{BASE_URL}?Temp1Read=&TempSet_Range=")
    if r.status_code != 200:
        raise DeviceError(f"HTTP {r.status_code}")
    txt = r.text.strip()
    # Try JSON first
    try:
        d = r.json()
        cur = float(d.get("Temp1Read", 0.0))
        rng = d.get("TempSet_Range", {"min": 0.0, "max": 70.0})
        rng = {"min": float(rng.get("min", 0.0)), "max": float(rng.get("max", 70.0))}
        return float(cur), {"min": float(rng["min"]), "max": float(rng["max"])}
    except Exception:
        # Fallback: parse AtmoWEB-style response for both Temp1Read and TempSet_Range
        import re
        cur = None
        rng = {"min": 0.0, "max": 70.0}
        # Try to find Temp1Read
        m = re.search(r'Temp1Read[":=\s]*([0-9.]+)', txt)
        if m:
            cur = float(m.group(1))
        # Try to find TempSet_Range
        m_rng = re.search(r'TempSet_Range[":=\s]*\{?\"?min[":=\s]*([0-9.]+)[, ]+\"?max[":=\s]*([0-9.]+)', txt)
        if m_rng:
            rng = {"min": float(m_rng.group(1)), "max": float(m_rng.group(2))}
        if cur is not None:
            return float(cur), {"min": float(rng["min"]), "max": float(rng["max"])}
        # Try to find TempSet (for set_target fallback)
        m_set = re.search(r'TempSet[":=\s]*([0-9.]+)', txt)
        if m_set:
            cur = float(m_set.group(1))
            # return float(cur), {"min": float(rng["min"]), "max": float(rng["max"])}
        raise DeviceError("No Temp1Read or TempSet in device response")

def set_target(temp):
    """Set target temperature"""
    r = http_get(f"{BASE_URL}?TempSet={temp}")
    if r.status_code != 200:
        raise DeviceError(f"Failed to set target: HTTP {r.status_code}")
    # Accept AtmoWEB-style response, do not require JSON
    txt = r.text.strip()
    if not ("TempSet" in txt or r.status_code == 200):
        raise DeviceError(f"Unexpected response to TempSet: {txt}")

def progress_bar(cur,tgt,start,w=20):
    """Progress bar from start to target"""
    if abs(tgt-start)<0.1: return "["+"#"*w+"]"
    p=max(0,min(1,(cur-start)/(tgt-start))); f=int(p*w)
    return f"[{'#'*f}{'_'*(w-f)}]"

def estimate_eta_ekf(readings, target, tau_h, tau_c, dt, ekf_params=None):
    """Extended Kalman Filter for tau, T_infty estimation and ETA prediction.
    All time units in SECONDS internally.
    
    Uses modular ThermalEstimator with 3-state EKF: [T_current, tau, Tinf]
    """
    if np is None or len(readings) < 2:
        return None, {}
    
    # Load EKF parameters from config or use defaults
    if ekf_params is None:
        ekf_params = {}
    
    # Determine if heating or cooling
    cur = readings[-1][1]
    heating = target > cur
    tau_init = tau_h if heating else tau_c
    
    # Create estimator (stateless - creates new EKF each call)
    estimator = ThermalEstimator(ekf_params)
    
    # Run estimation
    result = estimator.update(readings, tau_init, target, dt)
    
    if not result:
        return None, {}
    
    # Extract estimates
    tau = result['tau']
    Tinf = result['Tinf']
    T0 = result['T0']
    residuals = result.get('residuals', [])
    
    # Compute ETA
    eta = estimator.estimate_eta(cur, Tinf, tau)
    
    return eta, {"tau": tau, "Tinf": Tinf, "T0": T0, "residuals": residuals}

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
    """Write config YAML with all sections and arrow pointer"""
    # Only update tau_heating (+info) after heating, tau_cooling (+info) after cooling, and current_set_index
    import yaml
    # Load existing config to preserve all other settings/structure
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[WARN] Could not load config for update: {e}")
        return

    # Parse YAML and preserve comments
    config = yaml.safe_load(''.join([l for l in lines if not l.strip().startswith('#')])) or {}

    # Only update allowed fields, preserve all others
    if 'device' not in config:
        config['device'] = {}
    config['device']['current_set_index'] = idx
    config['device']['target_temperatures'] = [float(t) for t in temps]
    if 'eta_model' not in config:
        config['eta_model'] = {}
    if 'tau_heating' in c:
        config['eta_model']['tau_heating'] = float(c['tau_heating'])
    if 'tau_heating_info' in c:
        config['eta_model']['tau_heating_info'] = c['tau_heating_info']
    if 'tau_cooling' in c:
        config['eta_model']['tau_cooling'] = float(c['tau_cooling'])
    if 'tau_cooling_info' in c:
        config['eta_model']['tau_cooling_info'] = c['tau_cooling_info']
    
    # Write config with arrow pointer in comments
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            # Write header comments
            f.write("# Memmert IPP30 Temperature Controller Configuration\n")
            f.write("# device: Chamber setpoints and control parameters\n")
            f.write("# eta_model: ETA model selection and tau values\n")
            f.write("# logging: Logging intervals\n\n")
            
            # Write device section
            f.write("device:\n")
            f.write("  target_temperatures:\n")
            for i, temp in enumerate(temps):
                arrow = " ← " if i == idx else " "
                ordinal = ["First", "Second", "Third", "Fourth", "Fifth"][i] if i < 5 else f"{i+1}th"
                f.write(f"    - {temp} #{arrow}{ordinal} setpoint\n")
            f.write(f"  current_set_index: {idx}  # Index of active setpoint\n")
            f.write(f"  wait_s: {int(config['device'].get('wait_s', 60))}  # Wait time after reaching target (seconds)\n")
            f.write(f"  tolerance: {float(config['device'].get('tolerance', 0.5))}  # Allowed deviation from target (°C)\n\n")
            
            # Write eta_model section
            em = config.get('eta_model', {})
            f.write("eta_model:\n")
            f.write(f"  model_type: {int(em.get('model_type', 2))}  # 2=EKF, 1=Exponential\n")
            f.write(f"  tau_override: {int(em.get('tau_override', 1))}  # 1=update tau after run\n")
            f.write(f"  tau_heating: {float(em.get('tau_heating', 10.0))}  # Heating time constant (min)\n")
            f.write(f"  tau_heating_info: {em.get('tau_heating_info', '')}  # Info about last heating tau update\n")
            f.write(f"  tau_cooling: {float(em.get('tau_cooling', 10.0))}  # Cooling time constant (min)\n")
            f.write(f"  tau_cooling_info: {em.get('tau_cooling_info', '')}  # Info about last cooling tau update\n\n")
            
            # Write logging section
            lg = config.get('logging', {})
            f.write("logging:\n")
            f.write(f"  dt_s: {float(lg.get('dt_s', 60.0))}  # Device polling interval (seconds)\n")
            f.write(f"  dt_logfile_s: {float(lg.get('dt_logfile_s', 10.0))}  # Log file write interval (seconds)\n\n")
            
            # Write EKF section
            ekf = config.get('ekf', {})
            f.write("# EKF parameters (only for experienced users)\n")
            f.write("# Tuning these parameters affects EKF convergence and stability\n")
            f.write("ekf:\n")
            f.write(f"  window_size: {int(ekf.get('window_size', 20))}  # Number of samples for rolling window fit\n")
            f.write(f"  outlier_threshold: {float(ekf.get('outlier_threshold', 4.0))}  # Robust z-score threshold for outlier detection\n")
            P_init = ekf.get('P_init', [0.5, 1.0, 2.0])
            f.write(f"  P_init: [{float(P_init[0])}, {float(P_init[1])}, {float(P_init[2])}]  # Initial state covariance [T, tau, Tinf]\n")
            Q_process = ekf.get('Q_process', [0.25, 0.01, 0.0025])
            f.write(f"  Q_process: [{float(Q_process[0])}, {float(Q_process[1])}, {float(Q_process[2])}]  # Process noise [T, tau, Tinf]\n")
            f.write(f"  R_measurement: {float(ekf.get('R_measurement', 0.01))}  # Measurement noise variance\n")
    except Exception as e:
        print(f"[WARN] Config write failed: {e}")

def log_run(start_temp,tgt,final_tau,em,heating,cfg_obj):
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
            f.write(f"# Wait Time (s): {int(cfg_obj.get('device',{}).get('wait_s',60))}\n")
            f.write(f"# Tolerance (°C): {float(cfg_obj.get('device',{}).get('tolerance',0.5))}\n")
            f.write(f"# Sampling Interval (s): {cfg_obj.get('dt_s',60.0)}\n")
            f.write(f"# Setpoint Index: {cfg_obj['idx']}\n")
            f.write(f"# Notes: \n")
            f.write("Timestamp,Elapsed_s,Temperature,ETA_min,Tau_min,Tinf,Progress_pct\n")
            # Write sample data if available (optional: could be passed in future)
    except Exception as e:
        print(f"[WARN] Per-run log failed: {e}")
    # --- Global tau lookup table ---
    lookup_path = os.path.join(os.path.dirname(__file__), "lookup_tau.csv")
    try:
        with open(lookup_path, "a", encoding="utf-8") as f:
            if f.tell()==0:
                f.write("Date,Start_Temp,Target_Temp,Mode,Tau_min,ETA_Model,Wait_s,Tolerance,dt_s,Num_Samples,Notes\n")
            f.write(f"{date_str},{start_temp:.2f},{tgt:.2f},{mode},{final_tau:.2f},{model},{int(cfg_obj.get('device',{}).get('wait_s',60))},{float(cfg_obj.get('device',{}).get('tolerance',0.5))},{cfg_obj.get('dt_s',60.0)},,\n")
    except Exception as e:
        print(f"[WARN] Tau lookup log failed: {e}")

def maybe_update_tau(c,cfg_obj,heating,tau_h_est,tau_c_est,start_temp):
    """Update tau in config if tau_override enabled and starting from ambient"""
    # Only update tau and info fields, leave all other config values untouched
    if int(c.get('tau_override',0))==1 and cfg_obj['idx']==0:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        key, info_key = ("tau_heating", "tau_heating_info") if heating else ("tau_cooling", "tau_cooling_info")
        final_tau = tau_h_est if heating else tau_c_est
        end_temp = cfg_obj['temps'][cfg_obj['idx']]
        info_str = f"Updated {ts} | Start T={start_temp:.1f} °C | End T={end_temp:.1f} °C"
        print(f"[INFO] Updating {key} to {final_tau:.6f} and {info_key}: {info_str}")
        c[key] = float(final_tau)
        c[info_key] = info_str

def run_single_setpoint(tgt,wait_m,tol,cfg_obj):
    """Execute control loop for one setpoint"""
    c = cfg_obj['c']
    cur, rng = get_state()
    cur = float(cur)
    mn, mx = float(rng['min']), float(rng['max'])
    print(f"[INFO] Target {tgt}°C | Range {mn}–{mx}°C | Current {cur:.2f}°C | Tol ±{tol}°C")
    if not (mn <= tgt <= mx):
        raise ConfigError(f"Target {tgt}°C outside valid range [{mn},{mx}]")

    set_target(tgt)
    dt_s = float(cfg_obj.get('dt_s', 60))
    dt_logfile_s = float(cfg_obj.get('dt_logfile_s', 10))
    tau_h_min = float(cfg_obj.get('eta_model', {}).get('tau_heating', 10.0))
    tau_c_min = float(cfg_obj.get('eta_model', {}).get('tau_cooling', 10.0))
    # Convert tau from minutes to seconds for internal use
    tau_h = tau_h_min * 60.0
    tau_c = tau_c_min * 60.0
    sleep_s = max(1, dt_s)
    start_temp = cur
    em = int(cfg_obj.get('eta_model', {}).get('model_type', 1))

    if em == 2:
        print("[INFO] ETA Model: Extended Kalman Filter (EKF) | T(t)=T∞+(T₀-T∞)e^(-t/τ)")
    else:
        print(f"[INFO] ETA Model: Exponential | T(t)=T∞+(T₀-T∞)e^(-t/τ), τ={(tau_h_min if tgt > start_temp else tau_c_min):.2f}m")
    print(f"[INFO] Monitoring with {dt_s:.1f}s updates …")

    readings = []
    start = time.time()
    # tau_history stores tau in seconds
    tau_history = []  # Store last N tau estimates for rolling median

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
            f.write("Timestamp,Elapsed_s,Temperature,ETA_min,Tau_min,Tinf,T0,Progress_pct\n")
            f.write("hh:mm:ss,s,°C,min,min,°C,°C,%\n")

    # Separate intervals for progress bar (dt_s) and log file (dt_logfile_s)
    last_log_t = start - dt_logfile_s  # ensure first sample is logged
    last_progress_t = start - dt_s     # ensure first progress is printed
    cur = None
    eta = None
    tag = ''
    tau_last_min = tau_h_min if tgt > start_temp else tau_c_min  # Initialize for first log entry
    Tinf_show = tgt
    param_str = ''
    while True:
        now = time.time()
        # Poll device and log at dt_logfile_s intervals
        if now - last_log_t >= dt_logfile_s or cur is None:
            cur, _ = get_state()
            readings.append((now, cur))
            if em == 2:
                ekf_params = cfg_obj.get('ekf', {})
                # Add tolerance to ekf_params for ETA calculation
                ekf_params['tolerance'] = tol
                # EKF works in seconds internally
                eta_s, ex = estimate_eta_ekf(readings, tgt, tau_h, tau_c, dt_logfile_s, ekf_params)
                tag = '[EKF]'
                tau_new = ex.get('tau', tau_h if tgt > start_temp else tau_c)
                Tinf_show = ex.get('Tinf', tgt)
                T0_show = ex.get('T0', cur)
                # Convert eta from seconds to minutes for display
                eta = eta_s / 60.0 if eta_s is not None else None
                # --- Rolling median tau (in seconds) ---
                if tau_new > 6.0:  # at least 6 seconds
                    tau_history.append(tau_new)
                    if len(tau_history) > 10:
                        tau_history.pop(0)
                    tau_last = float(np.median(tau_history)) if tau_history else tau_new
                    if tgt > start_temp:
                        tau_h = tau_last
                    else:
                        tau_c = tau_last
                else:
                    tau_last = tau_h if tgt > start_temp else tau_c
                # Convert tau to minutes for display/logging
                tau_last_min = tau_last / 60.0
                eta_str = f"ETA~{eta:.1f}m" if eta else "ETA~--"
                param_str = f" τ={tau_last_min:.2f}m T∞={Tinf_show:.2f}°C"
            else:
                eta, ex = estimate_eta_exp(readings, tgt, tau_h_min, tau_c_min, tol)
                tag = '[EXP]'
                tau_last_min = tau_h_min if tgt > start_temp else tau_c_min
                Tinf_show = tgt
                T0_show = cur  # Not used in EXP mode, but needed for consistent log format
                eta_str = f"ETA~{eta:.1f}m" if eta else "ETA~--"; param_str = f" T∞={Tinf_show:.2f}°C"
            elapsed_s = now - start
            ts_disp = time.strftime("%H:%M:%S", time.localtime(now))
            progress = 100.0 * max(0, min(1, (cur - start_temp) / (tgt - start_temp))) if abs(tgt - start_temp) > 1e-6 else 100.0
            with open(log_path, "a", encoding="utf-8") as f:
                # Write T0 for both modes (empty for EXP since it doesn't use rolling window)
                t0_val = f"{T0_show:.3f}" if em == 2 else ""
                f.write(f"{ts_disp},{elapsed_s:.1f},{cur:.3f},{eta if eta is not None else ''},{tau_last_min:.3f},{Tinf_show:.3f},{t0_val},{progress:.1f}\n")
            last_log_t = now
        # Print progress bar at dt_s intervals, using last log entry
        if now - last_progress_t >= dt_s:
            # Read last line from log file for display
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines):
                    if not line.startswith('#') and not line.startswith('Timestamp') and not line.startswith('hh:mm:ss'):
                        parts = line.strip().split(',')
                        if len(parts) >= 6:
                            ts_disp = parts[0]
                            elapsed_s = float(parts[1])
                            cur_log = float(parts[2])
                            eta_log = float(parts[3]) if parts[3] else None
                            tau_last_log = float(parts[4]) if parts[4] else None
                            progress = float(parts[5])
                            break
                print(f"[INFO] {ts_disp} {progress_bar(cur_log, tgt, start_temp)} {tag} {eta_str} | T={cur_log:.2f}°C{param_str}")
            except Exception as e:
                print(f"[WARN] Could not read log for progress bar: {e}")
            last_progress_t = now
        # --- END CONDITION: Tolerance + 5τ criterion (using latest tau only) ---
        if abs(cur - Tinf_show) <= tol and (now - start) >= 5.0 * tau_last:
            print(f"[INFO] Target reached (within ±{tol}°C of T∞={Tinf_show:.2f}°C and ≥5τ={5*tau_last_min:.1f}m) in {(now-start)/60.0:.1f}m. Waiting {int(cfg_obj.get('device',{}).get('wait_s',60))}s …")
            break
        # Sleep until next event (progress or log)
        next_progress = last_progress_t + dt_s
        next_log = last_log_t + dt_logfile_s
        sleep_until = min(next_progress, next_log)
        time.sleep(max(0.1, sleep_until - time.time()))

    time.sleep(int(cfg_obj.get('device',{}).get('wait_s',60)))
    print("[INFO] Complete.")
    
    # Log and update (convert tau from seconds to minutes for storage)
    heating=tgt>start_temp
    final_tau = tau_h if heating else tau_c
    final_tau_min = final_tau / 60.0
    log_run(start_temp,tgt,final_tau_min,em,heating,cfg_obj)
    maybe_update_tau(c,cfg_obj,heating,tau_h/60.0,tau_c/60.0,start_temp)
    
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
    except ManualModeError as e:
        print(f"[ERROR] {e}")
        print("[ERROR] Exit code 2: Device not in Manual mode.")
        sys.exit(2)
    except (ConnectionError, TimeoutError) as e:
        print(f"[ERROR] {e}")
        print("[ERROR] Exit code 1: Device not responding.")
        sys.exit(1)
    except (ConfigError, DeviceError) as e:
        print(f"[ERROR] {e}")
        print("[ERROR] Exit code 3: Device error.")
        sys.exit(3)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        print("[ERROR] Exit code 3: Device error.")
        sys.exit(3)

if __name__ == "__main__":
    main()
