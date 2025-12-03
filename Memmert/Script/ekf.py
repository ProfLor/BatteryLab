"""
Extended Kalman Filter implementation
Generic EKF that works with any model providing f, F, h, H methods

For 3-state thermal model [T_current, tau, Tinf]:
- State includes temperature, which evolves according to thermal dynamics
- Parameters tau and Tinf evolve by process noise
- Measurements are temperature readings that directly observe T_current
"""
import numpy as np


class ExtendedKalmanFilter:
    """Generic Extended Kalman Filter for state and parameter estimation"""
    
    def __init__(self, x0, P0, Q, R):
        """
        Initialize EKF
        
        Args:
            x0: Initial state vector
            P0: Initial state covariance matrix
            Q: Process noise covariance matrix
            R: Measurement noise covariance (scalar or matrix)
        """
        self.x = np.array(x0, dtype=float)
        self.P = np.array(P0, dtype=float)
        self.Q = np.array(Q, dtype=float)
        self.R = float(R) if np.isscalar(R) else np.array(R, dtype=float)
        
        # Diagnostics
        self.residuals = []
    
    def predict(self, model, dt):
        """
        Prediction step: propagate state and covariance
        
        State evolves according to thermal dynamics model
        
        Args:
            model: Model with f(x, dt) and F(x, dt) methods
            dt: Time step
        """
        # Predict state
        self.x = model.f(self.x, dt)
        
        # Predict covariance
        F = model.F(self.x, dt)
        self.P = F @ self.P @ F.T + self.Q
        
        # Enforce symmetry and positivity
        self.P = 0.5 * (self.P + self.P.T)
        self.P[self.P < 1e-6] = 1e-6
    
    def update(self, model, measurement):
        """
        Update step: correct state with measurement
        
        Args:
            model: Model with h(x) and H(x) methods
            measurement: Current measured temperature (°C)
        """
        # Compute measurement prediction and Jacobian
        h = model.h(self.x)
        H = model.H(self.x)
        
        # Innovation (difference between measured and predicted temperature)
        innovation = measurement - h
        
        # Innovation covariance
        S = H @ self.P @ H + self.R
        
        # Kalman gain
        K = (self.P @ H) / S
        
        # Update state
        self.x = self.x + K * innovation
        
        # Update covariance
        self.P = self.P - np.outer(K, K) * S
        
        # Enforce symmetry and positivity
        self.P = 0.5 * (self.P + self.P.T)
        self.P[self.P < 1e-6] = 1e-6
        
        # Store diagnostics
        self.residuals.append({
            'innovation': float(innovation),
            'S': float(S),
            'R': float(self.R)
        })
    
    def get_state(self):
        """Return current state estimate"""
        return self.x.copy()
    
    def get_covariance(self):
        """Return current state covariance"""
        return self.P.copy()
    
    def get_residuals(self):
        """Return residual history"""
        return self.residuals.copy()
    
    def clear_residuals(self):
        """Clear residual history"""
        self.residuals = []
