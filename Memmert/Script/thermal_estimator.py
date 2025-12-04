"""
Thermal Estimator for Memmert IPP30
Combines ThermalModel and ExtendedKalmanFilter with application-specific logic

3-state EKF: x = [T_current, tau, T_infty]
Estimates temperature in state vector to absorb model mismatch
"""
import numpy as np
from thermal_model import ThermalModel
from ekf import ExtendedKalmanFilter

# ========== CONSTANTS ==========
MIN_SAMPLES_FOR_OUTLIER_DETECTION = 5
MAD_EPSILON = 1e-6  # Minimum MAD to prevent division by zero
ROBUST_ZSCORE_CONSTANT = 0.6745  # Median absolute deviation to standard deviation conversion factor


class ThermalEstimator:
    """
    High-level estimator for thermal chamber dynamics
    Handles outlier detection and adaptive processing
    
    State vector: x = [T_current, tau, T_infty] (3 states)
    """
    
    def __init__(self, ekf_params: dict) -> None:
        """
        Initialize thermal estimator
        
        Args:
            ekf_params: Dictionary with configuration:
                - window_size: Number of samples for rolling window
                - outlier_threshold: Robust z-score threshold
                - P_init: Initial state covariance [T, tau, Tinf]
                - Q_process: Process noise [T, tau, Tinf]
                - R_measurement: Measurement noise
                - tolerance: Temperature tolerance for ETA calculation
                
        Raises:
            ValueError: If numeric parameters cannot be converted to float/int
        """
        self.model = ThermalModel()
        self.ekf_params = ekf_params
        
        # Configuration
        self.window_size = int(ekf_params.get('window_size', 20))
        self.outlier_threshold = float(ekf_params.get('outlier_threshold', 4.0))
        self.tolerance = float(ekf_params.get('tolerance', 0.5))
        
        # Measurement noise
        self.R = float(ekf_params.get('R_measurement', 0.01))
        
        # EKF state (initialized on first call)
        self.ekf = None
    
    def _is_outlier(self, temps: np.ndarray, current_temp: float) -> bool:
        """
        Robust outlier detection using MAD (Median Absolute Deviation)
        
        The constant 0.6745 converts MAD to standard deviation equivalent,
        making the robust z-score comparable to traditional z-scores.
        
        Args:
            temps: Array of recent temperatures
            current_temp: Latest temperature to check
            
        Returns:
            True if current_temp is an outlier based on robust z-score
        """
        # Only apply after we have enough samples
        if len(temps) < MIN_SAMPLES_FOR_OUTLIER_DETECTION:
            return False
        
        # Robust z-score using MAD
        median_temp = np.median(temps)
        mad = np.median(np.abs(temps - median_temp))
        
        if mad < MAD_EPSILON:
            mad = MAD_EPSILON  # Avoid division by zero
        
        robust_zscore = ROBUST_ZSCORE_CONSTANT * (current_temp - median_temp) / mad
        return abs(robust_zscore) > self.outlier_threshold
    
    def update(
        self, 
        readings: list[tuple[float, float]], 
        tau_init: float, 
        target: float, 
        dt: float
    ) -> dict:
        """
        Update estimator with new temperature readings
        
        Processes readings through rolling window, detects outliers,
        initializes EKF on first call, and returns parameter estimates.
        
        Args:
            readings: List of (timestamp, temperature) tuples
            tau_init: Initial tau guess (seconds) for heating/cooling
            target: Target temperature (°C)
            dt: Time step between samples (seconds)
            
        Returns:
            Dictionary with estimation results:
                - tau: Estimated time constant (seconds)
                - Tinf: Estimated asymptotic temperature (°C)
                - T0: Window's first temperature (°C)
                - residuals: Diagnostic information
            Empty dict if insufficient data or outlier detected
        """
        if len(readings) < 2:
            return {}
        
        # Use rolling window for estimation
        window_readings = readings[-self.window_size:]
        temps = np.array([temp for _, temp in window_readings])
        initial_temp = temps[0]
        current_temp = temps[-1]
        
        # Outlier detection on latest sample
        if self._is_outlier(temps, current_temp):
            return {}  # Skip this update
        
        # Initialize EKF on first call
        if self.ekf is None:
            # 3-state: [T_current, tau, Tinf]
            x0 = np.array([initial_temp, tau_init, target])
            P0 = np.diag(self.ekf_params.get('P_init', [10.0, 2.0, 5.0]))
            Q = np.diag(self.ekf_params.get('Q_process', [0.0025, 0.001, 0.004]))
            
            self.ekf = ExtendedKalmanFilter(x0, P0, Q, self.R)
        
        # Process all samples in window
        for i in range(1, len(temps)):
            T_measured = temps[i]
            
            # Predict
            self.ekf.predict(self.model, dt)
            
            # Update
            self.ekf.update(self.model, T_measured)
        
        # Extract final estimates
        x_final = self.ekf.get_state()
        estimated_temp = float(x_final[0])  # Estimated temperature
        tau = max(float(x_final[1]), self.model.MIN_TAU)  # Estimated tau
        Tinf = float(x_final[2])  # Estimated Tinf
        
        return {
            'tau': tau,
            'Tinf': Tinf,
            'T0': initial_temp,
            'residuals': self.ekf.get_residuals()
        }
    
    def estimate_eta(self, T_current: float, Tinf: float, tau: float) -> float:
        """
        Estimate time to reach target temperature
        
        Uses exponential decay model to predict time until temperature
        reaches within tolerance of asymptotic temperature.
        
        Args:
            T_current: Current temperature (°C)
            Tinf: Asymptotic temperature (°C)
            tau: Time constant (seconds)
            
        Returns:
            ETA in seconds, or 0.0 if already within tolerance
        """
        err = abs(T_current - Tinf)
        
        if err < self.tolerance:
            return 0.0
        
        # Solve: tolerance = err * exp(-eta/tau)
        # eta = -tau * ln(tolerance / err)
        eta = max(0.0, -tau * np.log(self.tolerance / err))
        return eta
