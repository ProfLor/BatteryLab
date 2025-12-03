"""
Thermal Estimator for Memmert IPP30
Combines ThermalModel and ExtendedKalmanFilter with application-specific logic

3-state EKF: x = [T_current, tau, T_infty]
Estimates temperature in state vector to absorb model mismatch
"""
import numpy as np
from thermal_model import ThermalModel
from ekf import ExtendedKalmanFilter


class ThermalEstimator:
    """
    High-level estimator for thermal chamber dynamics
    Handles outlier detection and adaptive processing
    
    State vector: x = [T_current, tau, T_infty] (3 states)
    """
    
    def __init__(self, ekf_params):
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
    
    def _is_outlier(self, temps, current_temp):
        """
        Robust outlier detection using MAD (Median Absolute Deviation)
        
        Args:
            temps: Array of recent temperatures
            current_temp: Latest temperature to check
            
        Returns:
            bool: True if current_temp is an outlier
        """
        # Only apply after we have enough samples
        if len(temps) < 5:
            return False
        
        # Robust z-score using MAD
        med = np.median(temps)
        mad = np.median(np.abs(temps - med))
        
        if mad < 1e-6:
            mad = 1e-6  # Avoid division by zero
        
        z = 0.6745 * (current_temp - med) / mad
        return abs(z) > self.outlier_threshold
    
    def update(self, readings, tau_init, target, dt):
        """
        Update estimator with new temperature readings
        
        Args:
            readings: List of (timestamp, temperature) tuples
            tau_init: Initial tau guess (seconds) for heating/cooling
            target: Target temperature (°C)
            dt: Time step between samples (seconds)
            
        Returns:
            dict: Estimation results with keys:
                - tau: Estimated time constant (seconds)
                - Tinf: Estimated asymptotic temperature (°C)
                - T0: Window's first temperature (°C)
                - residuals: Diagnostic information
        """
        if len(readings) < 2:
            return {}
        
        # Use rolling window for estimation
        w = readings[-self.window_size:]
        temps = np.array([x for _, x in w])
        T0 = temps[0]
        T_current = temps[-1]
        
        # Outlier detection on latest sample
        if self._is_outlier(temps, T_current):
            return {}  # Skip this update
        
        # Initialize EKF on first call
        if self.ekf is None:
            # 3-state: [T_current, tau, Tinf]
            x0 = np.array([T0, tau_init, target])
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
        T_est = float(x_final[0])  # Estimated temperature
        tau = max(float(x_final[1]), self.model.MIN_TAU)  # Estimated tau
        Tinf = float(x_final[2])  # Estimated Tinf
        
        return {
            'tau': tau,
            'Tinf': Tinf,
            'T0': T0,
            'residuals': self.ekf.get_residuals()
        }
    
    def estimate_eta(self, T_current, Tinf, tau):
        """
        Estimate time to reach target temperature
        
        Args:
            T_current: Current temperature (°C)
            Tinf: Asymptotic temperature (°C)
            tau: Time constant (seconds)
            
        Returns:
            float: ETA in seconds, or 0.0 if within tolerance
        """
        err = abs(T_current - Tinf)
        
        if err < self.tolerance:
            return 0.0
        
        # Solve: tolerance = err * exp(-eta/tau)
        # eta = -tau * ln(tolerance / err)
        eta = max(0.0, -tau * np.log(self.tolerance / err))
        return eta
