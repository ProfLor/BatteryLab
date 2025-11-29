# Memmert IPP30 AtmoWEB Control

Remote temperature control for Memmert IPP30 cooled incubators via the AtmoWEB REST interface. Features real-time monitoring, ETA prediction, and EC-LAB EXTAPP compatibility.

## Features

- **YAML configuration**: Target temperature, wait time, tolerance
- **Multi-setpoint sequencing**: Configure `target_temperatures` (list) with `current_set_index`; script advances and wraps to the first after the last
- **Smart monitoring**: Minute-by-minute updates with live temperature readings
- **ETA prediction**: Linear regression on recent data to estimate time to target
- **Progress visualization**: Text-based progress bar (`[#####_______________]`) showing completion percentage
- **Network resilience**: Automatic retries (3×), configurable timeouts (10s), preflight connectivity checks
- **Mode validation**: Ensures device is in Manual mode before applying setpoints
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

| File                    | Description                                                      |
|------------------------|------------------------------------------------------------------|
| memmert_control.py     | Control script (main logic, callable via Python)                 |
| IPP30_TEMP_CNTRL.yaml  | Configuration file for target temperature, wait time, tolerance  |
| run_memmert_control.bat| Batch file for convenient script execution/EXTAPP usage          |

## Configuration File

Example (`IPP30_TEMP_CNTRL.yaml`):

```yaml
# Target temperature (°C), Wait time (minutes), Tolerance (°C)
target_temperature: 37.5
wait_time: 15
tolerance: 0.5
```

The file must be located in the same folder as the script.

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

Script output shows real-time status with progress bar and ETA:

```text
[INFO] Target 37.5 °C | Range 0–70 °C | Current 21.34 °C | Tol ±0.5 °C
[INFO] Set 37.5 °C
[INFO] Monitoring with 1-minute updates …
[INFO] [#####_______________] 25.80 °C (Δ-11.70 °C) | ETA ~18.3 min
[INFO] [##########__________] 31.20 °C (Δ-6.30 °C) | ETA ~10.1 min
[INFO] [##################__] 36.90 °C (Δ-0.60 °C) | ETA ~1.2 min
[INFO] Target reached in 19.4 minutes. Waiting 15 min …
[INFO] Complete.
```

Each `#` in the progress bar represents 5% completion from start to target temperature.

### Multi-setpoint behavior

- After completing a run, the script increments `current_set_index` and rewrites the YAML marking the new active entry.
- When the last entry is reached, the index wraps back to `0` on the next run.

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

## Notes & Troubleshooting

- **Device not found**: Script performs preflight connectivity check. Verify IP address, network connection, power, and firewall settings.
- **Not in Manual mode**: Device must be in Manual mode for setpoints to be applied (per AtmoWEB manual section 4.3). Script exits with code 2.
- **Range validation**: Target temperature is validated against device-provided `TempSet_Range`. If unavailable, script exits with code 3.
- **ETA accuracy**: Linear regression uses a rolling window of last 10 readings. More accurate for steady heating/cooling rates; less accurate during initial transients or near setpoint.
- **Temperature ramps**: For complex multi-step profiles, create programs in AtmoCONTROL and trigger via REST (`ProgStart`).

---
