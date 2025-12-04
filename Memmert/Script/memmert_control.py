import json
import os
import re
import sys
import time
import math
import yaml
import requests

try:
    import numpy as np
    from thermal_estimator import ThermalEstimator
except ImportError as e:
    np = None
    print(f"[WARN] Could not import required modules: {e}")

# ========== CONSTANTS ==========
BASE_URL = "http://192.168.96.21/atmoweb"
CFG = "IPP30_TEMP_CNTRL.yaml"
TIMEOUT_S = 10
RETRIES = 3
RETRY_DELAY_S = 2
TARGET_THRESHOLD = 0.1  # °C threshold for "target reached"
MIN_TAU_SECONDS = 6.0
TAU_HISTORY_SIZE = 10
TEMP_EPSILON = 0.1
PROGRESS_BAR_WIDTH = 20
MODE_SWITCH_DELAY_SECONDS = 2
DEFAULT_TEMP_MIN = 0.0
DEFAULT_TEMP_MAX = 70.0

# ========== EXCEPTIONS ==========
class ConfigError(Exception):
    pass

class DeviceError(Exception):
    pass

class ManualModeError(Exception):
    pass

class ConnectionError(Exception):
    pass

# ========== DEVICE OPERATIONS ==========
def check_manual_mode() -> bool:
    """Check if device is in Manual mode. If not, prompt user to abort current operation and switch to Manual."""
    response = http_get(f"{BASE_URL}?CurOp=")
    if response.status_code != 200:
        raise ConnectionError(f"HTTP {response.status_code} on CurOp query")
    
    text = response.text.strip()
    if 'Manual' in text:
        return True
    
    mode = text
    print(f"[WARN] Device is currently in mode: {mode}")
    answer = input("Do you want to abort the current operation and switch to Manual mode to start heating/cooling? (y/n): ").strip().lower()
    
    if answer == 'y':
        print("[INFO] Sending abort command to device...")
        r_abort = http_get(f"{BASE_URL}?ProgExit=")
        if r_abort.status_code != 200:
            raise ConnectionError(f"Failed to abort program: HTTP {r_abort.status_code}")
        time.sleep(MODE_SWITCH_DELAY_SECONDS)
        
        r_check = http_get(f"{BASE_URL}?CurOp=")
        if 'Manual' in r_check.text.strip():
            print("[INFO] Device is now in Manual mode.")
            return True
        else:
            raise ManualModeError(f"Device did not switch to Manual mode (CurOp={r_check.text.strip()})")
    else:
        raise ManualModeError(f"User aborted: Device is in mode {mode}")

# ========== CONFIG MANAGEMENT ==========
def cfg() -> tuple[float, int, float, dict]:
    """Load configuration from YAML file.
    
    Returns:
        Tuple containing:
            - target_temperature (float): Target temperature in °C
            - wait_seconds (int): Wait time after reaching target
            - tolerance (float): Allowed deviation from target in °C
            - config_dict (dict): Full configuration parameters
            
    Raises:
        ConfigError: If config file is invalid or missing required fields
    """
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, FileNotFoundError, IOError) as e:
        raise ConfigError(f"Failed to load {CFG}: {e}") from e

    # Extract sections
    device = config_data.get("device", {})
    eta_model = config_data.get("eta_model", {})
    logging_cfg = config_data.get("logging", {})

    wait_s = int(device.get("wait_s", 60))
    tolerance = float(device.get("tolerance", 0.5))
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
        index = int(device.get("current_set_index", 0))
        if not (0 <= index < len(temps)):
            raise ConfigError(f"current_set_index {index} out of range [0,{len(temps)-1}]")
        # Load EKF parameters if present
        ekf_params = config_data.get("ekf", {})
        # Merge all config for downstream use
        merged = {"temps": temps, "idx": index, "c": {**device, **eta_model, **logging_cfg}, "dt_s": dt_s, "dt_logfile_s": dt_logfile_s, "device": device, "eta_model": eta_model, "logging": logging_cfg, "ekf": ekf_params}
        return float(temps[index]), wait_s, tolerance, merged

    if "target_temperature" not in device:
        raise ConfigError("Missing both target_temperatures and target_temperature in device section")
    ekf_params = config_data.get("ekf", {})
    merged = {"temps": [device["target_temperature"]], "idx": 0, "c": {**device, **eta_model, **logging_cfg}, "dt_s": dt_s, "dt_logfile_s": dt_logfile_s, "device": device, "eta_model": eta_model, "logging": logging_cfg, "ekf": ekf_params}
    return float(device["target_temperature"]), wait_s, tolerance, merged

# ========== HTTP & PARSING HELPERS ==========
def http_get(url: str) -> requests.Response:
    """Execute HTTP GET request with automatic retry logic.
    
    Args:
        url: Target URL to fetch
        
    Returns:
        Response object from successful request
        
    Raises:
        ConnectionError: If all retry attempts fail or request fails
    """
    for attempt in range(1, RETRIES + 1):
        try:
            return requests.get(url, timeout=TIMEOUT_S)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < RETRIES:
                print(f"[WARN] Retry {attempt}/{RETRIES}")
                time.sleep(RETRY_DELAY_S)
            else:
                raise ConnectionError(f"Device unreachable after {RETRIES} retries") from e
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"HTTP request failed: {e}")

def parse_json_response(response: requests.Response) -> tuple[float | None, dict | None]:
    """Parse JSON response from device.
    
    Args:
        response: HTTP response object to parse
        
    Returns:
        Tuple of (temperature, temp_range) or (None, None) if parsing fails
    """
    try:
        data = response.json()
        temp = float(data.get("Temp1Read", 0.0))
        range_data = data.get("TempSet_Range", {"min": DEFAULT_TEMP_MIN, "max": DEFAULT_TEMP_MAX})
        temp_range = {
            "min": float(range_data.get("min", DEFAULT_TEMP_MIN)),
            "max": float(range_data.get("max", DEFAULT_TEMP_MAX))
        }
        return temp, temp_range
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None, None

def parse_text_response(text: str) -> tuple[float | None, dict | None]:
    """Parse text response from device using regex.
    
    Args:
        text: Raw text response to parse
        
    Returns:
        Tuple of (temperature, temp_range) or (None, None) if parsing fails
    """
    temp = None
    temp_range = {"min": DEFAULT_TEMP_MIN, "max": DEFAULT_TEMP_MAX}
    
    # Try to find Temp1Read
    match_temp = re.search(r'Temp1Read[":=\s]*([0-9.]+)', text)
    if match_temp:
        temp = float(match_temp.group(1))
    
    # Try to find TempSet_Range
    match_range = re.search(r'TempSet_Range[":=\s]*\{?\"?min[":=\s]*([0-9.]+)[, ]+\"?max[":=\s]*([0-9.]+)', text)
    if match_range:
        temp_range = {
            "min": float(match_range.group(1)),
            "max": float(match_range.group(2))
        }
    
    if temp is not None:
        return temp, temp_range
    
    # Try to find TempSet as fallback
    match_set = re.search(r'TempSet[":=\s]*([0-9.]+)', text)
    if match_set:
        temp = float(match_set.group(1))
        return temp, temp_range
    
    return None, None

def write_config(temps: list[float], idx: int, config_updates: dict) -> None:
    """Write configuration to YAML file with arrow pointer.
    
    Args:
        temps: List of target temperatures
        idx: Index of currently active setpoint
        config_updates: Dictionary of config values to update
    """
    # Load existing config to preserve all other settings/structure
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, IOError) as e:
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
    if 'tau_heating' in config_updates:
        config['eta_model']['tau_heating'] = float(config_updates['tau_heating'])
    if 'tau_heating_info' in config_updates:
        config['eta_model']['tau_heating_info'] = config_updates['tau_heating_info']
    if 'tau_cooling' in config_updates:
        config['eta_model']['tau_cooling'] = float(config_updates['tau_cooling'])
    if 'tau_cooling_info' in config_updates:
        config['eta_model']['tau_cooling_info'] = config_updates['tau_cooling_info']
    
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
    except (IOError, OSError) as e:
        print(f"[WARN] Config write failed: {e}")

def get_state() -> tuple[float, dict]:
    """Get current device state including temperature and valid range.
    
    Returns:
        Tuple of (current_temperature, temp_range_dict)
        
    Raises:
        DeviceError: If device response is invalid or missing required data
    """
    response = http_get(f"{BASE_URL}?Temp1Read=&TempSet_Range=")
    if response.status_code != 200:
        raise DeviceError(f"HTTP {response.status_code}")
    
    # Try JSON first
    temp, temp_range = parse_json_response(response)
    if temp is not None:
        return temp, temp_range
    
    # Fallback to text parsing
    temp, temp_range = parse_text_response(response.text.strip())
    if temp is not None:
        return temp, temp_range
    
    raise DeviceError("No Temp1Read or TempSet in device response")

def set_target(temp: float) -> None:
    """Set device target temperature.
    
    Args:
        temp: Target temperature in °C
        
    Raises:
        DeviceError: If temperature setting fails
    """
    r = http_get(f"{BASE_URL}?TempSet={temp}")
    if r.status_code != 200:
        raise DeviceError(f"Failed to set target: HTTP {r.status_code}")
    # Accept AtmoWEB-style response, do not require JSON
    txt = r.text.strip()
    if not ("TempSet" in txt or r.status_code == 200):
        raise DeviceError(f"Unexpected response to TempSet: {txt}")

# ========== DISPLAY HELPERS ==========
def progress_bar(current: float, target: float, start: float, width: int = PROGRESS_BAR_WIDTH) -> str:
    """Generate text-based progress bar.
    
    Args:
        current: Current temperature value
        target: Target temperature value
        start: Starting temperature value
        width: Width of progress bar in characters
        
    Returns:
        String representation of progress bar
    """
    if abs(target - start) < TEMP_EPSILON:
        return f"[{'#' * width}]"
    
    progress = max(0, min(1, (current - start) / (target - start)))
    filled = int(progress * width)
    return f"[{'#' * filled}{'_' * (width - filled)}]"

# ========== ESTIMATION LOGIC ==========
def estimate_eta_ekf(
    readings: list[tuple[float, float]], 
    target: float, 
    tau_h: float, 
    tau_c: float, 
    dt: float, 
    ekf_params: dict | None = None
) -> tuple[float | None, dict]:
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

def estimate_eta_exp(
    readings: list[tuple[float, float]], 
    target: float, 
    tau_h: float, 
    tau_c: float, 
    tolerance: float
) -> tuple[float | None, dict]:
    """Exponential model with fixed tau from config (no fitting)"""
    if not readings:
        return None, {}
    
    window = readings[-10:]
    T0 = window[0][1]
    current = window[-1][1]
    heating = target > current
    Tinf = float(target)
    tau = float(tau_h if heating else tau_c)
    error = abs(current - Tinf)
    
    if error < TEMP_EPSILON:
        return 0.0, {"tau": tau}
    
    eta = max(0.0, -tau * math.log(TEMP_EPSILON / error))
    return eta, {"tau": tau}

# ========== LOGGING ==========
def initialize_log_file(
    log_path: str, 
    start_temp: float, 
    target: float, 
    model_type: int, 
    cfg_obj: dict, 
    dt_s: float, 
    dt_logfile_s: float
) -> None:
    """Create and initialize log file with metadata header.
    
    Args:
        log_path: Path to log file
        start_temp: Starting temperature in °C
        target: Target temperature in °C
        model_type: ETA model type (2=EKF, 1=Exponential)
        cfg_obj: Configuration dictionary
        dt_s: Sampling interval in seconds
        dt_logfile_s: Log file write interval in seconds
    """
    if os.path.exists(log_path):
        return
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("# Memmert IPP30 Run Log\n")
        f.write(f"# Date: {time.strftime('%Y-%m-%d')}\n")
        f.write(f"# Start Time: {time.strftime('%H:%M:%S')}\n")
        f.write(f"# Start Temperature (°C): {start_temp:.2f}\n")
        f.write(f"# Target Temperature (°C): {target:.2f}\n")
        f.write(f"# ETA Model: {'EKF' if model_type == 2 else 'EXP'}\n")
        f.write(f"# Mode: {'heating' if target > start_temp else 'cooling'}\n")
        f.write(f"# Wait Time (s): {int(cfg_obj.get('device', {}).get('wait_s', 60))}\n")
        f.write(f"# Tolerance (°C): {float(cfg_obj.get('device', {}).get('tolerance', 0.5))}\n")
        f.write(f"# Sampling Interval (s): {dt_s}\n")
        f.write(f"# Log File Sampling Interval (s): {dt_logfile_s}\n")
        f.write(f"# Setpoint Index: {cfg_obj['idx']}\n")
        f.write("# Notes: \n")
        f.write("Timestamp,Elapsed_s,Temperature,ETA_min,Tau_min,Tinf,T0,Progress_pct\n")
        f.write("hh:mm:ss,s,°C,min,min,°C,°C,%\n")

def log_run(
    start_temp: float, 
    target: float, 
    final_tau: float, 
    model_type: int, 
    heating: bool, 
    cfg_obj: dict
) -> None:
    """Log completed run to CSV history files.
    
    Args:
        start_temp: Starting temperature in °C
        target: Target temperature in °C
        final_tau: Final tau value in minutes
        model_type: ETA model type (2=EKF, 1=Exponential)
        heating: True if heating mode, False if cooling
        cfg_obj: Configuration dictionary
    """
    ts_full = time.strftime("%Y-%m-%d_%H-%M-%S")
    date_str = time.strftime("%Y-%m-%d")
    time_str = time.strftime("%H:%M:%S")
    model = "EKF" if model_type == 2 else "EXP"
    mode = "heating" if heating else "cooling"
    # --- Per-run detailed log ---
    log_dir = os.path.join(os.path.dirname(__file__), "log-files")
    os.makedirs(log_dir, exist_ok=True)
    log_filename = f"{ts_full}_{start_temp:.1f}_{target:.1f}.csv"
    log_path = os.path.join(log_dir, log_filename)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            # Write header with metadata
            f.write(f"# Memmert IPP30 Run Log\n")
            f.write(f"# Date: {date_str}\n")
            f.write(f"# Start Time: {time_str}\n")
            f.write(f"# Start Temperature (°C): {start_temp:.2f}\n")
            f.write(f"# Target Temperature (°C): {target:.2f}\n")
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
            f.write(f"{date_str},{start_temp:.2f},{target:.2f},{mode},{final_tau:.2f},{model},{int(cfg_obj.get('device',{}).get('wait_s',60))},{float(cfg_obj.get('device',{}).get('tolerance',0.5))},{cfg_obj.get('dt_s',60.0)},,\n")
    except Exception as e:
        print(f"[WARN] Tau lookup log failed: {e}")

def maybe_update_tau(
    config: dict, 
    cfg_obj: dict, 
    heating: bool, 
    tau_h_est: float, 
    tau_c_est: float, 
    start_temp: float
) -> None:
    """Update tau in config if tau_override enabled and starting from ambient.
    
    Args:
        config: Configuration dictionary to update
        cfg_obj: Full configuration object
        heating: True if heating mode
        tau_h_est: Estimated heating tau in minutes
        tau_c_est: Estimated cooling tau in minutes
        start_temp: Starting temperature in °C
    """
    if int(config.get('tau_override', 0)) == 1 and cfg_obj['idx'] == 0:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        key, info_key = ("tau_heating", "tau_heating_info") if heating else ("tau_cooling", "tau_cooling_info")
        final_tau = tau_h_est if heating else tau_c_est
        end_temp = cfg_obj['temps'][cfg_obj['idx']]
        info_str = f"Updated {ts} | Start T={start_temp:.1f} °C | End T={end_temp:.1f} °C"
        print(f"[INFO] Updating {key} to {final_tau:.6f} and {info_key}: {info_str}")
        config[key] = float(final_tau)
        config[info_key] = info_str

# ========== MAIN CONTROL LOOP ==========
def initialize_log_file(
    log_path: str, 
    start_temp: float, 
    target: float, 
    model_type: int, 
    cfg_obj: dict, 
    dt_s: float, 
    dt_logfile_s: float
) -> None:
    """Create and initialize log file with metadata header"""
    if os.path.exists(log_path):
        return
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("# Memmert IPP30 Run Log\n")
        f.write(f"# Date: {time.strftime('%Y-%m-%d')}\n")
        f.write(f"# Start Time: {time.strftime('%H:%M:%S')}\n")
        f.write(f"# Start Temperature (°C): {start_temp:.2f}\n")
        f.write(f"# Target Temperature (°C): {target:.2f}\n")
        f.write(f"# ETA Model: {'EKF' if model_type == 2 else 'EXP'}\n")
        f.write(f"# Mode: {'heating' if target > start_temp else 'cooling'}\n")
        f.write(f"# Wait Time (s): {int(cfg_obj.get('device', {}).get('wait_s', 60))}\n")
        f.write(f"# Tolerance (°C): {float(cfg_obj.get('device', {}).get('tolerance', 0.5))}\n")
        f.write(f"# Sampling Interval (s): {dt_s}\n")
        f.write(f"# Log File Sampling Interval (s): {dt_logfile_s}\n")
        f.write(f"# Setpoint Index: {cfg_obj['idx']}\n")
        f.write("# Notes: \n")
        f.write("Timestamp,Elapsed_s,Temperature,ETA_min,Tau_min,Tinf,T0,Progress_pct\n")
        f.write("hh:mm:ss,s,°C,min,min,°C,°C,%\n")

def run_single_setpoint(target: float, wait_s: int, tolerance: float, cfg_obj: dict) -> None:
    """Execute temperature control loop for single setpoint.
    
    Monitors device temperature, estimates ETA, logs data, and controls
    until target temperature is reached within tolerance.
    
    Args:
        target: Target temperature in °C
        wait_s: Wait time in seconds after reaching target
        tolerance: Allowed deviation from target in °C
        cfg_obj: Full configuration dictionary
        
    Raises:
        ConfigError: If target is outside valid range
        DeviceError: If device communication fails
    """
    config = cfg_obj['c']
    current, temp_range = get_state()
    current = float(current)
    min_temp = float(temp_range['min'])
    max_temp = float(temp_range['max'])
    
    print(f"[INFO] Target {target}°C | Range {min_temp}–{max_temp}°C | Current {current:.2f}°C | Tol ±{tolerance}°C")
    if not (min_temp <= target <= max_temp):
        raise ConfigError(f"Target {target}°C outside valid range [{min_temp},{max_temp}]")

    set_target(target)
    dt_s = float(cfg_obj.get('dt_s', 60))
    dt_logfile_s = float(cfg_obj.get('dt_logfile_s', 10))
    tau_h_min = float(cfg_obj.get('eta_model', {}).get('tau_heating', 10.0))
    tau_c_min = float(cfg_obj.get('eta_model', {}).get('tau_cooling', 10.0))
    
    # Convert tau from minutes to seconds for internal use
    tau_h = tau_h_min * 60.0
    tau_c = tau_c_min * 60.0
    start_temp = current
    model_type = int(cfg_obj.get('eta_model', {}).get('model_type', 1))

    if model_type == 2:
        print("[INFO] ETA Model: Extended Kalman Filter (EKF) | T(t)=T∞+(T₀-T∞)e^(-t/τ)")
    else:
        print(f"[INFO] ETA Model: Exponential | T(t)=T∞+(T₀-T∞)e^(-t/τ), τ={(tau_h_min if target > start_temp else tau_c_min):.2f}m")
    print(f"[INFO] Monitoring with {dt_s:.1f}s updates …")

    readings = []
    start_time = time.time()
    tau_history = []

    # Initialize log file
    ts_full = time.strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = os.path.join(os.path.dirname(__file__), "log-files")
    log_filename = f"{ts_full}_{start_temp:.1f}_{target:.1f}.csv"
    log_path = os.path.join(log_dir, log_filename)
    initialize_log_file(log_path, start_temp, target, model_type, cfg_obj, dt_s, dt_logfile_s)

    # Separate intervals for progress bar (dt_s) and log file (dt_logfile_s)
    last_log_time = start_time - dt_logfile_s
    last_progress_time = start_time - dt_s
    current = None
    eta = None
    tag = ''
    tau_last_min = tau_h_min if target > start_temp else tau_c_min
    Tinf_show = target
    param_str = ''
    
    while True:
        now = time.time()
        # Poll device and log at dt_logfile_s intervals
        if now - last_log_time >= dt_logfile_s or current is None:
            current, _ = get_state()
            readings.append((now, current))
            if model_type == 2:
                ekf_params = cfg_obj.get('ekf', {})
                ekf_params['tolerance'] = tolerance
                # EKF works in seconds internally
                eta_s, estimates = estimate_eta_ekf(readings, target, tau_h, tau_c, dt_logfile_s, ekf_params)
                tag = '[EKF]'
                tau_new = estimates.get('tau', tau_h if target > start_temp else tau_c)
                Tinf_show = estimates.get('Tinf', target)
                T0_show = estimates.get('T0', current)
                # Convert eta from seconds to minutes for display
                eta = eta_s / 60.0 if eta_s is not None else None
                # Rolling median tau (in seconds)
                if tau_new > MIN_TAU_SECONDS:
                    tau_history.append(tau_new)
                    if len(tau_history) > TAU_HISTORY_SIZE:
                        tau_history.pop(0)
                    tau_last = float(np.median(tau_history)) if tau_history else tau_new
                    if target > start_temp:
                        tau_h = tau_last
                    else:
                        tau_c = tau_last
                else:
                    tau_last = tau_h if target > start_temp else tau_c
                # Convert tau to minutes for display/logging
                tau_last_min = tau_last / 60.0
                eta_str = f"ETA~{eta:.1f}m" if eta else "ETA~--"
                param_str = f" τ={tau_last_min:.2f}m T∞={Tinf_show:.2f}°C"
            else:
                eta, estimates = estimate_eta_exp(readings, target, tau_h_min, tau_c_min, tolerance)
                tag = '[EXP]'
                tau_last_min = tau_h_min if target > start_temp else tau_c_min
                Tinf_show = target
                T0_show = current
                eta_str = f"ETA~{eta:.1f}m" if eta else "ETA~--"
                param_str = f" T∞={Tinf_show:.2f}°C"
            
            elapsed_s = now - start_time
            timestamp = time.strftime("%H:%M:%S", time.localtime(now))
            progress_pct = 100.0 * max(0, min(1, (current - start_temp) / (target - start_temp))) if abs(target - start_temp) > 1e-6 else 100.0
            
            with open(log_path, "a", encoding="utf-8") as f:
                t0_val = f"{T0_show:.3f}" if model_type == 2 else ""
                f.write(f"{timestamp},{elapsed_s:.1f},{current:.3f},{eta if eta is not None else ''},{tau_last_min:.3f},{Tinf_show:.3f},{t0_val},{progress_pct:.1f}\n")
            last_log_time = now
        # Print progress bar at dt_s intervals
        if now - last_progress_time >= dt_s:
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines):
                    if not line.startswith('#') and not line.startswith('Timestamp') and not line.startswith('hh:mm:ss'):
                        parts = line.strip().split(',')
                        if len(parts) >= 6:
                            timestamp = parts[0]
                            current_log = float(parts[2])
                            break
                print(f"[INFO] {timestamp} {progress_bar(current_log, target, start_temp)} {tag} {eta_str} | T={current_log:.2f}°C{param_str}")
            except Exception as e:
                print(f"[WARN] Could not read log for progress bar: {e}")
            last_progress_time = now
        
        # Check convergence: Tolerance + 5τ criterion
        if abs(current - Tinf_show) <= tolerance and (now - start_time) >= 5.0 * tau_last:
            print(f"[INFO] Target reached (within ±{tolerance}°C of T∞={Tinf_show:.2f}°C and ≥5τ={5*tau_last_min:.1f}m) in {(now-start_time)/60.0:.1f}m. Waiting {wait_s}s …")
            break
        
        # Sleep until next event
        next_progress = last_progress_time + dt_s
        next_log = last_log_time + dt_logfile_s
        sleep_until = min(next_progress, next_log)
        time.sleep(max(0.1, sleep_until - time.time()))

    time.sleep(wait_s)
    print("[INFO] Complete.")
    
    # Log and update (convert tau from seconds to minutes for storage)
    heating = target > start_temp
    final_tau = tau_h if heating else tau_c
    final_tau_min = final_tau / 60.0
    log_run(start_temp, target, final_tau_min, model_type, heating, cfg_obj)
    maybe_update_tau(config, cfg_obj, heating, tau_h / 60.0, tau_c / 60.0, start_temp)
    
    # Advance setpoint if needed
    temps = cfg_obj['temps']
    idx = cfg_obj['idx']
    if len(temps) > 1 or int(config.get('tau_override', 0)) == 1:
        next_idx = (idx + 1) % len(temps) if len(temps) > 1 else idx
        if len(temps) > 1:
            print(f"[INFO] Advancing set index {idx}->{next_idx}")
        write_config(temps, next_idx, config)

# ========== ENTRY POINT ==========
def main() -> None:
    """Main entry point for temperature controller.
    
    Loads configuration, checks device mode, and runs control loop.
    Handles all exceptions with appropriate exit codes.
    """
    try:
        target, wait_s, tolerance, cfg_obj = cfg()
        check_manual_mode()
        run_single_setpoint(target, wait_s, tolerance, cfg_obj)
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
