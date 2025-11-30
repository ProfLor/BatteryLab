# Memmert IPP30 AtmoWEB Control

Remote temperature control for Memmert IPP30 cooled incubators via the AtmoWEB REST interface. Features real-time monitoring, ETA prediction, and EC-LAB EXTAPP compatibility.

## Features

- **YAML configuration**: Target temperature, wait time, tolerance, sampling interval
- **Multi-setpoint sequencing**: Configure `target_temperatures` (list) with `current_set_index`; script advances and wraps to the first after the last
- **Smart monitoring**: Configurable interval (`dt_minutes`, default 1.0) for updates & ETA
- **Dual ETA models**: 
  - **Exponential (mode 1)**: Uses fixed τ from config only (no fitting)
  - **Extended Kalman Filter (mode 2)**: Real-time τ learning with gradient-limited convergence
- **Adaptive tau learning**: EKF can update tau_heating/tau_cooling in config when `tau_override: 1` (only from ambient starts)
- **Run history logging**: Automatic CSV logging with timestamp, temperatures, learned tau, model type, and heating/cooling mode
- **Progress visualization**: Text-based progress bar showing completion percentage with real-time ETA and τ display
- **Network resilience**: Automatic retries (3×), configurable timeouts
- **Exit codes**: Clear error reporting for automation integration (0=success, 1=error, 2=not manual, 3=no range)

## Prerequisites

- **Memmert IPP30** with AtmoWEB REST interface enabled (IP address accessible)
- **Network connection** (Ethernet) between control PC and device
- **Python 3.7+** (3.11+ recommended)
- **Python packages**: `requests`, `pyyaml`

### Installation

```bash
pip install requests pyyaml
```

## Files

| File                       | Description                                                      |
|---------------------------|------------------------------------------------------------------|
| memmert_control.py        | Production controller for Memmert IPP30 hardware                 |
| memmert_control_fast.py   | Fast controller (100x accelerated) for simulator testing         |
| temp_chamber_sim.py       | Thermal simulator with realistic exponential dynamics for testing ETA models |
| IPP30_TEMP_CNTRL.yaml     | Configuration file (target temps, wait time, tolerance, tau values, ETA model) |
| run_memmert_control.bat   | Batch launcher for production controller                         |
| run_memmert_control_fast.bat | Batch launcher for fast simulator testing                     |
| run_history.csv           | Auto-generated run history log (timestamp, temps, tau, model, mode) |

## Usage

### 1. Set IP Address

Edit the `BASE_URL` at the top of `memmert_control.py` to match your device:

```python
BASE_URL = "http://192.168.96.21/atmoweb"
```

### 2. Configure Parameters

Edit `IPP30_TEMP_CNTRL.yaml`:

```yaml
target_temperatures:
  - 25.0
  - 37.5  # <-- current SetTemp
  - 15.0
current_set_index: 1        # 0-based index of active set temperature
wait_time: 15               # Minutes to wait after stabilization
tolerance: 0.5              # Acceptable deviation in °C

# ETA prediction model: 1=Exponential (least-squares τ fit), 2=EKF (Extended Kalman Filter)
eta_model: 2

# Update tau with EKF estimates: 0=no (keep user values), 1=yes (override with learned values)
tau_override: 1

# Heating time constant (minutes) - updated automatically when tau_override=1
tau_heating: 10.0
tau_heating_info: "Updated 2025-12-01 14:30:22 | Start T=22.0°C"

# Cooling time constant (minutes) - updated automatically when tau_override=1
tau_cooling: 14.0
tau_cooling_info: "Updated 2025-12-01 14:45:10 | Start T=22.0°C"

# Sampling interval for temperature readings (minutes)
dt_minutes: 1.0
```

### 3. Run the Script

#### Option A: Direct Python

```bash
python memmert_control.py
```

#### Option B: Batch Launcher (Recommended for EXTAPP)

```bash
run_memmert_control.bat
```

The batch launcher auto-detects Python (Miniconda, Python.org installs, `py` launcher) or uses `MEMMERT_PYTHON` environment variable if set.

#### Option C: From EC-LAB EXTAPP

Set `run_memmert_control.bat` as an external program trigger in your EC-Lab technique.

### 4. Monitor Progress

Script output shows real-time status with progress bar and ETA (interval reflects `dt_minutes`):

#### Exponential Model (eta_model: 1)
```text
[INFO] Target 37.5°C | Range 0–70°C | Current 21.34°C | Tol ±0.5°C
[INFO] ETA Model: Exponential | T(t)=T∞+(T₀-T∞)e^(-t/τ), τ=10.00m
[INFO] Monitoring with 1.0m updates …
[INFO] [#####_______________] [EXP] ETA~18.3m | T=25.80°C
[INFO] [##########__________] [EXP] ETA~10.1m | T=31.20°C
[INFO] [##################__] [EXP] ETA~1.2m | T=36.90°C
[INFO] Target reached in 19.4m. Waiting 15m …
[INFO] Complete.
```

#### EKF Model (eta_model: 2)
```text
[INFO] Target 37.5°C | Range 0–70°C | Current 21.34°C | Tol ±0.5°C
[INFO] ETA Model: Extended Kalman Filter (EKF) | T(t)=T∞+(T₀-T∞)e^(-t/τ)
[INFO] Monitoring with 1.0m updates …
[INFO] [#####_______________] [EKF] ETA~18.3m | T=25.80°C τ=11.20m
[INFO] [##########__________] [EKF] ETA~10.1m | T=31.20°C τ=11.05m
[INFO] [##################__] [EKF] ETA~1.2m | T=36.90°C τ=10.98m
[INFO] Target reached in 19.4m. Waiting 15m …
[INFO] Complete.
[INFO] Updating tau_heating to 10.98m (learned from EKF)
```

Each `#` in the progress bar represents 5% completion from start to target temperature.
- **Exponential model**: Shows fixed τ in model info line (from config), estimates ETA using fixed tau only
- **EKF model**: Shows evolving τ in each progress line, learns tau in real-time with gain-limited convergence

### Multi-setpoint behavior

- After completing a run, the script increments `current_set_index` and rewrites the YAML marking the new active entry.
- When the last entry is reached, the index wraps back to `0` on the next run.

### Sampling Interval (`dt_minutes`)

#### Recommended Ranges

- 0.5–1.0 min: Rapid ramps or tighter ETA resolution
- 1.0–2.0 min: Typical usage (default 1.0)
- 2.0–5.0 min: Slow stabilization phases (reduces network traffic)


Rule of thumb for EKF accuracy: choose `dt_minutes <= tau/10`. Avoid values >5 (coarse ETA, slower deviation detection).

## Simulator (Local Testing & ETA Model Validation)

The thermal simulator provides realistic exponential heating/cooling dynamics for testing both ETA prediction models without hardware:

### Features
- **Realistic thermal behavior**: First-order exponential model T(t) = T∞ + (T₀-T∞)e^(-t/τ)
- **Variable time constants**: 
  - Heating: τ = 8-14 min (avg 11 min, ±15% jitter per run)
  - Cooling: τ = 10-18 min (avg 14 min, ±15% jitter per run)
- **100x time acceleration**: Dynamics run 100× faster than real chamber (TIME_SCALE=100)
- **AtmoWEB-compatible API**: Drop-in replacement for testing
- **Port conflict detection**: Auto-exits if simulator already running

### Usage

#### Start Simulator
```powershell
python temp_chamber_sim.py
```

Listens at `http://127.0.0.1:8000/atmoweb` with endpoints:
- `?Temp1Read=`: Current chamber temperature
- `?TempSet_Range=`: Returns `{min: 0.0, max: 70.0}`
- `?TempSet=XX`: Sets target setpoint
- `?CurOp=`: Returns `Manual`

#### Run Fast Controller
```powershell
.\run_memmert_control_fast.bat
```

The fast controller (`memmert_control_fast.py`):
- Automatically divides `dt_minutes`, `tau_*`, and `wait_time` by 100 (FAST scaling)
- Points to simulator at `http://127.0.0.1:8000/atmoweb`
- Multiplies learned tau by 100 before saving to config
- Enables rapid testing of ETA models (complete heating cycle in ~1 minute vs ~100 minutes)

#### Testing ETA Models
1. Set `eta_model: 2` and `tau_override: 1` in config
2. Run `.\run_memmert_control_fast.bat`
3. Observe EKF converging to simulator's true tau (displayed as τ=11-14m in progress, saved unscaled)
4. Check `run_history.csv` for logged tau values
5. Verify `tau_heating_info` and `tau_cooling_info` persistence across multiple runs

The simulator's random tau jitter lets you validate EKF robustness across varying thermal dynamics.

## Exit Codes

| Code | Meaning                                                           |
|------|-------------------------------------------------------------------|
| 0    | Success                                                           |
| 1    | General error (config, HTTP, communication failure)               |
| 2    | Device not in Manual mode                                         |
| 3    | Device did not provide TempSet_Range                              |

## Advanced Configuration

### Python Environment Override

If Python is not in PATH or you want to use a specific installation:

```powershell
$env:MEMMERT_PYTHON="C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe"
./run_memmert_control.bat
```

### Network Settings

- **Timeout**: 10 seconds (configurable via `TIMEOUT_S` in script)
- **Retries**: 3 attempts (configurable via `RETRIES`)
- **Retry delay**: 2 seconds between attempts

### Dependencies

Required for EKF ETA model (`eta_model: 2`) and simulator:

```powershell
pip install numpy
```

Optional for simulator only:

```powershell
pip install psutil  # For port conflict detection
```

## ETA Model Details

### Exponential Model (eta_model: 1)
- Always uses `tau_heating`/`tau_cooling` from config (no fitting, no regression)
- ETA is computed using the fixed tau value only
- Does NOT update config file
- Fast computation, no dependencies
- Best for: Stable systems, quick setup, when tau learning/persistence not needed

### Extended Kalman Filter (eta_model: 2)
- 2-state EKF tracking [T_current, tau]
- Jacobian: ∂T/∂τ = (dt/τ²)(T_prev - T∞)e^(-dt/τ)
- Kalman gain limiting: ±0.05 (fast mode) / ±0.5 (production) for stable convergence
- Initial covariance: P = diag([10.0, 2.0])
- Process noise: Q = diag([0.05², 0.002²])
- Measurement noise: R = 0.1²
- Best for: Adaptive learning, unknown/varying tau, continuous improvement

### Tau Override (tau_override: 1)
When enabled with EKF:
- Updates `tau_heating` or `tau_cooling` in config after each run
- Only triggers when `current_set_index: 0` (ambient start condition)
- Stores timestamp and start temperature in `tau_*_info` keys
- Enables self-calibrating system that improves ETA accuracy over time

### Run History CSV
Auto-logged after each run:
```csv
Timestamp,Initial_Temp,Target_Temp,Tau_calc,Model,Mode
YYYY-MM-DD HH:MM:SS,°C,°C,min,-,-
2025-12-01 14:30:22,22.00,50.00,10.98,EKF,heating
2025-12-01 14:45:10,22.00,0.00,14.12,EKF,cooling
```

## Notes & Troubleshooting

- **Device not found**: Verify IP address, network connection, power, and firewall settings.
- **Not in Manual mode**: Device must be in Manual mode for setpoints to be applied. Script exits with code 2.
- **Range validation**: Target temperature validated against device `TempSet_Range`. If unavailable, script exits with code 3.
- **ETA accuracy**: Both models assume first-order exponential thermal dynamics T(t)=T∞+(T₀-T∞)e^(-t/τ). More accurate than linear regression.
- **EKF convergence**: If tau jumps erratically, gain limits prevent instability. Increase `dt_minutes` or adjust Q/R matrices if needed.
- **Tau learning**: For best results, run several cycles from ambient (idx=0) to let EKF converge before relying on learned tau values.
- **Temperature ramps**: For complex multi-step profiles, create programs in AtmoCONTROL and trigger via REST (`ProgStart`).

---
