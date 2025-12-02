
# Memmert IPP30 AtmoWEB Control

Remote temperature control for Memmert IPP30 incubators via the AtmoWEB REST API. Features robust ETA prediction, multi-setpoint sequencing, and granular logging.

---

## Quickstart

1. **Install Python 3.7+** and required packages:
   ```bash
   pip install requests pyyaml
   # For ETA model 2 (EKF):
   pip install numpy
   ```
2. **Edit `IPP30_TEMP_CNTRL.yaml`** to set your temperature sequence and parameters (see below).
3. **Set the device IP** in `memmert_control.py` (`BASE_URL = "http://<your-ip>/atmoweb"`).
4. **Run the script:**
   - Windows: `run_memmert_control.bat`
   - Or: `python memmert_control.py`

---

## Configuration (`IPP30_TEMP_CNTRL.yaml`)

```yaml
device:
  target_temperatures:  # List of setpoints (°C)
    - 40.0
    - 0.0  # <-- current SetTemp
    - 25.0
  current_set_index: 1  # Active setpoint (0-based)
  wait_s: 60            # Wait time after reaching target (seconds)
  tolerance: 0.5        # Allowed deviation from setpoint (°C)

eta_model:
  model_type: 2         # 1=Exponential, 2=EKF
  tau_override: 1       # 1=update tau with EKF, 0=keep user values
  tau_heating: 3.9      # Heating time constant (minutes)
  tau_heating_info: "Updated 2025-12-02 11:17:25 | Start T=23.0°C"
  tau_cooling: 14.6     # Cooling time constant (minutes)
  tau_cooling_info: "Updated 2025-12-01 00:32:04 | Start T=0.0°C"

logging:
  dt_s: 60.0            # Main control sampling interval (seconds)
  dt_logfile_s: 10.0    # Log file sampling interval (seconds)
```

---

## Operation

- The script advances through `target_temperatures`, updating `current_set_index` after each run.
- After the last entry, the index wraps to 0.
- The chamber must be in **Manual** mode for remote control.
- **Log files** are written to `log-files/` with per-run CSVs at the interval set by `dt_logfile_s`.

---

## ETA Models

- **Exponential (model_type: 1):** Uses fixed tau from config, no learning.
- **EKF (model_type: 2):** Learns tau in real time, can update tau in config if `tau_override: 1` and starting from ambient.

**Target reached = within tolerance AND at least 5×tau elapsed.**

---

## Logging & Output

- Each run creates a CSV log in `log-files/` with columns:
  `Timestamp,Elapsed_s,Temperature,ETA_min,Tau_min,Progress_pct`
- Log interval is set by `dt_logfile_s` (e.g., 10 s).
- A global tau lookup table is appended to `lookup_tau.csv`.

---

## Troubleshooting & Safety

- **Device not found:** Check IP, network, and device settings.
- **Not in Manual mode:** Script will prompt or exit.
- **Device does not heat/cool:** Device must be actively running (fan noise is audible). If not, ensure the chamber is in "Active" mode (not just Manual) and a timer is set on the device. See device manual for details.
- **Last setpoint:** Always end with room temperature to avoid leaving the chamber at extreme temps.
- **Range validation:** Script checks device range before setting.

---

## Advanced

- **Python override:** Set `MEMMERT_PYTHON` env variable to use a specific Python install.
- **Timeouts/retries:** Configurable in `memmert_control.py` (`TIMEOUT_S`, `RETRIES`).
- **Simulator/testing:** See `memmert_control_fast.py` and `temp_chamber_sim.py` for advanced users.

### EKF Parameter Tuning (Experienced Users Only)

The EKF parameters in `IPP30_TEMP_CNTRL.yaml` under the `ekf:` section control the Kalman filter behavior:

- **window_size:** Number of temperature samples used for rolling window fit (default: 20)
- **outlier_threshold:** Robust z-score threshold for outlier detection (default: 4.0)
- **fit_range:** Progress range `[start, end]` where tau is fitted (default: `[0.3, 0.7]`)
  - Only fits tau during middle 30-70% of transient to avoid artifacts at start/end
  - Outside this range, tau is frozen to prevent drift near equilibrium
- **P_init:** Initial state covariance `[T, tau, Tinf]` (default: `[10.0, 2.0, 5.0]`)
- **Q_process:** Process noise covariance `[T, tau, Tinf]` (default: `[0.0025, 0.0001, 0.000025]`)
  - Lower values = more stable estimates, slower convergence
  - Higher values = faster adaptation, more noise sensitivity
- **R_measurement:** Measurement noise variance (default: 0.01)

**Tip:** If tau overestimates or drifts, reduce `Q_process[1]` (tau process noise) or narrow the `fit_range`.

---

## Exit Codes

| Code | Meaning                        |
|------|--------------------------------|
| 0    | Success                        |
| 1    | Device not connected or not responding |
| 2    | Device not in Manual mode      |

---

## Notes

- Both ETA models assume first-order exponential thermal dynamics.
- EKF model is robust to outliers and adapts tau over time.
- For best results, run several cycles from ambient to let EKF converge.
