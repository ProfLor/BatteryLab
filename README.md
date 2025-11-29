# BatteryLab

Automation scripts for laboratory battery testing with integrated temperature control. Enables coordinated operation of **BioLogic SP-50E** potentiostats (via EC-Lab EXTAPP) and **Memmert IPP30** cooled incubators for temperature-controlled electrochemical experiments.

## Components

### Memmert IPP30 Control

Remote temperature control via AtmoWEB REST interface. Features include:

- YAML-driven configuration (target temp, wait time, tolerance)
- Real-time monitoring with ETA estimation (linear regression)
- Progress bar visualization
- Robust network handling (retries, timeouts, preflight checks)
- BioLogic's EC-Lab$ \circledR $, EXTAPP compatible batch launcher with auto-detection of Python environments

📄 **[Detailed documentation](Memmert/Script/README.md)** | **[Script](Memmert/Script/memmert_control.py)**


## Quick Start

```powershell
# Install dependencies
pip install requests pyyaml

# Configure target temperature
cd Memmert/Script
# Edit IPP30_TEMP_CNTRL.yaml

# Run
./run_memmert_control.bat
```

## Repository Structure

```text
BatteryLab/
├── LICENSE
├── README.md
└── Memmert/
    └── Script/
        ├── README.md      # Detailed usage instructions
        ├── memmert_control.py
        ├── run_memmert_control.bat
        └── IPP30_TEMP_CNTRL.yaml
```

## License / Attribution

Licensed under the MIT License (see `LICENSE`).

### Disclaimer

This repository and its scripts are provided "AS IS" without any warranty. You assume all responsibility for:

- Safe operation of laboratory equipment (Memmert IPP30, BioLogic testers)
- Correct configuration (temperature targets, tolerances, wait times)
- Compliance with safety, regulatory, and quality procedures in your lab

The author is not liable for damage to equipment, samples, data loss, downtime, or any consequential losses.

Before using automation:

- Verify manual mode and a safe initial temperature
- Confirm network/IP settings correspond to the intended device
- Supervise first runs and validate stabilization criteria

---

Feel free to open issues or extend scripts for additional hardware integration (e.g., automated SOC conditioning, multi-step temperature profiles).
