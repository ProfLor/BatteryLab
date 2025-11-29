# Memmert IPP30 AtmoWEB Control

This package provides remote temperature control for a Memmert IPP30 cooled incubator via the AtmoWEB REST interface using Python. The script is compatible with EC-LAB EXTAPP.

## Prerequisites

- **Memmert IPP30** with active AtmoWEB REST interface (IP address known, access available)
- **Network connection** (Ethernet) between control PC and device
- **Python 3.7+** recommended  
- **Installed Python modules**:
  - `requests` (for REST communication)
  - `pyyaml` (for YAML configurations)

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

1. **Set IP Address:**  
   Enter the correct IP address of the Memmert IPP30 at the top of `memmert_control.py`.

2. **Configure Parameters:**  
   Edit the YAML file as needed.

3. **Execution:**  
   - Direct:  
     ```bash
     python memmert_control.py
     ```
   - Via Batch (e.g., from EC-LAB EXTAPP):  
     Double-click `run_memmert_control.bat` or set an external program trigger in EC-LAB

4. **Typical Workflow:**  
   - Script reads target values from YAML, checks range, and sets temperature
   - Starts the temperature control program
   - Waits until temperature is reached (±tolerance)
   - Counts down wait time, then terminates automatically

## Exit Codes

| Code | Meaning                                                           |
|------|-------------------------------------------------------------------|
| 0    | Success                                                           |
| 1    | General error (config, HTTP, communication failure)               |
| 2    | Device not in Manual mode                                         |
| 3    | Device did not provide TempSet_Range                              |

## Notes & Troubleshooting

- The script validates the target temperature against the **device-provided range** (`TempSet_Range`). If the device does not return this parameter, the script exits with code 3.
- The device must be in **Manual mode** for setpoints to be applied (per AtmoWEB manual section 4.3).
- Tolerance is implemented in software for practical control logic, not as a device parameter.
- For temperature ramps, create complete programs in AtmoCONTROL and start them via REST (`ProgStart`).

---
