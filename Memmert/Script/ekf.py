"""
Extended Kalman Filter implementation
Generic EKF that works with any model providing f, F, h, H methods

For 3-state thermal model [T_current, tau, Tinf]:
- State includes temperature, which evolves according to thermal dynamics
- Parameters tau and Tinf evolve by process noise
- Measurements are temperature readings that directly observe T_current
"""
import numpy as np

# ========== CONSTANTS ==========
COVARIANCE_SYMMETRY_WEIGHT = 0.5  # Weight for enforcing matrix symmetry
MIN_COVARIANCE = 1e-6  # Minimum covariance value to prevent singularity


class ExtendedKalmanFilter:
    """Generic Extended Kalman Filter for state and parameter estimation"""
    
    def __init__(
        self, 
        x0: np.ndarray | list, 
        P0: np.ndarray | list, 
        Q: np.ndarray | list, 
        R: float | np.ndarray
    ) -> None:
        """
        Initialize EKF
        
        Args:
            x0: Initial state vector (will be converted to numpy array)
            P0: Initial state covariance matrix (will be converted to numpy array)
            Q: Process noise covariance matrix (will be converted to numpy array)
            R: Measurement noise covariance (scalar or matrix, will be converted appropriately)
        """
        self.x = np.array(x0, dtype=float)
        self.P = np.array(P0, dtype=float)
        self.Q = np.array(Q, dtype=float)
        self.R = float(R) if np.isscalar(R) else np.array(R, dtype=float)
        
        # Diagnostics
        self.residuals = []
    
    def predict(self, model, dt: float) -> None:
        """
        Prediction step: propagate state and covariance
        
        State evolves according to thermal dynamics model.
        Applies process noise and enforces covariance matrix properties.
        
        Args:
            model: Model with f(x, dt) and F(x, dt) methods
            dt: Time step (seconds)
        """
        # Predict state
        self.x = model.f(self.x, dt)
        
        # Predict covariance
        jacobian = model.F(self.x, dt)
        self.P = jacobian @ self.P @ jacobian.T + self.Q
        
        # Enforce symmetry and positivity
        self._enforce_covariance_properties()
    
    def update(self, model, measurement: float) -> None:
        """
        Update step: correct state with measurement
        
        Computes innovation (residual) between measurement and prediction,
        calculates Kalman gain, and updates state and covariance.
        
        Args:
            model: Model with h(x) and H(x) methods
            measurement: Current measured temperature (°C)
        """
        # Compute measurement prediction and Jacobian
        predicted_measurement = model.h(self.x)
        measurement_jacobian = model.H(self.x)
        
        # Innovation (difference between measured and predicted temperature)
        innovation = measurement - predicted_measurement
        
        # Innovation covariance (uncertainty in innovation)
        innovation_covariance = measurement_jacobian @ self.P @ measurement_jacobian + self.R
        
        # Kalman gain (optimal weighting between prediction and measurement)
        kalman_gain = (self.P @ measurement_jacobian) / innovation_covariance
        
        # Update state
        self.x = self.x + kalman_gain * innovation
        
        # Update covariance
        self.P = self.P - np.outer(kalman_gain, kalman_gain) * innovation_covariance
        
        # Enforce symmetry and positivity
        self._enforce_covariance_properties()
        
        # Store diagnostics
        self.residuals.append({
            'innovation': float(innovation),
            'S': float(innovation_covariance),
            'R': float(self.R)
        })
    
    def _enforce_covariance_properties(self) -> None:
        """
        Enforce covariance matrix properties: symmetry and positive definiteness
        
        Symmetrizes the covariance matrix by averaging with its transpose,
        then clamps small values to prevent numerical singularity.
        """
        self.P = COVARIANCE_SYMMETRY_WEIGHT * (self.P + self.P.T)
        self.P[self.P < MIN_COVARIANCE] = MIN_COVARIANCE
    
    def get_state(self) -> np.ndarray:
        """Return current state estimate"""
        return self.x.copy()
    
    def get_covariance(self) -> np.ndarray:
        """Return current state covariance"""
        return self.P.copy()
    
    def get_residuals(self) -> list[dict]:
        """Return residual history"""
        return self.residuals.copy()
    
    def clear_residuals(self) -> None:
        """Clear residual history"""
        self.residuals = []
