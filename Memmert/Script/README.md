
# Memmert IPP30 AtmoWEB Control

Automated temperature control for Memmert IPP30 climate chambers via AtmoWEB REST API. Features Extended Kalman Filter (EKF) for adaptive time constant estimation, real-time ETA prediction, multi-setpoint sequencing, and live visualization.

## Quick Start

1. **Install Python 3.7+** and dependencies:
   ```bash
   pip install requests pyyaml numpy scipy matplotlib
   ```

2. **Configure your sequence** in `IPP30_TEMP_CNTRL.yaml`:
   - Set `target_temperatures` (list of setpoints in °C)
   - Adjust `tolerance` and `wait_s` as needed
   - Set device IP in `memmert_control.py` if different from `192.168.96.21`

3. **Run the controller:**
   ```bash
   # Windows:
   .\run_memmert_control.bat
   
   # Or directly:
   python memmert_control.py
   ```

4. **Monitor live (optional):**
   ```bash
   python live_plot.py
   ```

## Configuration

### Device Settings
```yaml
device:
  target_temperatures: [40.0, 25.0]  # Sequence of setpoints (°C)
  current_set_index: 0               # Current position in sequence
  wait_s: 60                         # Hold time after reaching target
  tolerance: 0.5                     # Target tolerance (°C)
```

### Thermal Model
```yaml
eta_model:
  tau_heating: 5.57     # Heating time constant (minutes)
  tau_cooling: 10.62    # Cooling time constant (minutes)
```
*Note: Tau values are automatically learned and updated by the EKF during operation.*

### Logging
```yaml
logging:
  dt_s: 60.0           # Progress update interval (seconds)
  dt_logfile_s: 10.0   # Log file sampling rate (seconds)
```

### EKF Parameters (Advanced)
```yaml
ekf:
  window_size: 20                      # Samples in rolling window
  outlier_threshold: 4.0               # MAD z-score for outlier rejection
  P_init: [10.0, 5.0, 1.0]            # Initial uncertainty [T, tau, Tinf]
  Q_process: [0.0025, 0.01, 0.0001]   # Process noise [T, tau, Tinf]
  R_measurement: 0.01                  # Measurement noise variance
```

## System Architecture

The system uses a modular architecture with separated concerns:

- **`thermal_model.py`**: First-order thermal dynamics (Newton's law of cooling)
  - 3-state model: x = [T_current, tau, T∞]
  - State evolution and Jacobian matrices
  
- **`ekf.py`**: Generic Extended Kalman Filter
  - Prediction and update steps
  - Covariance maintenance and residual tracking
  
- **`thermal_estimator.py`**: Application-level estimator
  - Outlier detection (MAD-based robust statistics)
  - Rolling window estimation
  - ETA calculation
  
- **`memmert_control.py`**: Main controller
  - REST API communication
  - Multi-setpoint sequencing
  - CSV logging and tau persistence

- **`live_plot.py`**: Real-time visualization
  - Live temperature plots with prediction curves
  - Fading historical predictions
  - Target and ETA indicators

## Operation

### Normal Usage
1. Chamber must be in **Manual** mode for remote control
2. Script sets target temperature and monitors progress
3. EKF continuously adapts tau and Tinf estimates
4. When |T - T∞| < tolerance AND elapsed ≥ 5τ, target is reached
5. After `wait_s` seconds, advances to next setpoint
6. Sequence loops back to first setpoint after completion

### EKF State Estimation

The EKF estimates a 3-state vector: **x = [T_current, tau, T∞]**

Estimating temperature in the state vector (even though measured) allows the EKF to absorb model mismatch between Newton's law and the actual PID-controlled chamber dynamics. This enables correct convergence of tau and T∞ to physically meaningful values.

**Key Features:**
- **3-State Model**: T_current absorbs modeling errors, allowing tau and T∞ to converge correctly
- **Rolling Window**: 20-sample window for adaptive estimation
- **Outlier Rejection**: MAD-based robust statistics reject sensor glitches
- **Adaptive Parameters**: Tau can adapt during transient, T∞ remains stable
- **Residual Tracking**: Innovation and covariance logged for diagnostics

**Convergence Criterion:** |T - T∞| ≤ 0.5°C AND elapsed_time ≥ 5τ (99.3% settling)

## Log Files

### Per-Run CSV
`log-files/run_YYYYMMDD_HHMMSS.csv`

Columns: `Timestamp, Elapsed_s, Temperature, ETA_min, Tau_min, Tinf, T0`
- Sampling rate: `dt_logfile_s` (default 10 seconds)
- Includes EKF estimates for each sample

### Tau Lookup Table
`lookup_tau.csv`

Global history of learned tau values with metadata:
- Timestamp, direction (heating/cooling), tau (minutes), initial temp, target temp

## Live Visualization

Run `python live_plot.py` to see:
- Real-time temperature measurements (blue dots)
- Current EKF prediction curve (black solid line)
- Historical prediction curves (fading gray)
- Target temperature (green dashed)
- Estimated T∞ (red dashed)
- Estimated finish time (orange dashed)

Plot updates every 3 seconds from the latest log file.

## Troubleshooting

**Device not responding:**
- Check IP address in `memmert_control.py` (default: `192.168.96.21`)
- Verify network connectivity: `ping 192.168.96.21`
- Ensure chamber is powered and remote controll is enabled

**Chamber not heating/cooling:**
- Check that chamber is actively running (fan audible)
- Verify system is in manual mode without a timer running (**--h:--m**): `http://192.168.96.21/atmoweb?CurOp=`

**EKF predictions drift or oscillate:**
- Check `Q_process` values in config (may be too high)
- Verify log interval matches actual sampling (dt_logfile_s)
- Check residuals in CSV for outliers or measurement issues

**Tau not updating:**
- Ensure initial temperature is close to ambient (~20-25°C)
- EKF requires sufficient transient data (≥10 samples with ΔT > 0.5°C)
- Check if outlier detection is rejecting too many samples

## Exit Codes

| Code | Meaning                              |
|------|--------------------------------------|
| 0    | Success                              |
| 1    | Device not responding (connection)   |
| 2    | Device not in manual mode            |
| 3    | Device error (configuration, range)  |

## Advanced Topics

**Testing Without Hardware:** See `temp_chamber_sim.py` for a software simulator that mimics chamber thermal dynamics.

**Python Environment Override:** Set `MEMMERT_PYTHON` environment variable to use a specific Python interpreter.

**API Timeout/Retry:** Edit `TIMEOUT_S` and `RETRIES` constants in `memmert_control.py`.

## References

- **Newton's Law of Cooling:** dT/dt = (T∞ - T)/τ
- **Extended Kalman Filter:** Recursive Bayesian estimation with linearized dynamics
- **MAD (Median Absolute Deviation):** Robust outlier detection resistant to extreme values
