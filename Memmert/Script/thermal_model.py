"""
Thermal Model for Memmert IPP30 Temperature Chamber
Implements Newton's law of cooling with adaptive time constant

State vector: x = [T_current, tau, T_infty]
  T_current: Current temperature (°C)
  tau: Time constant (seconds)
  T_infty: Asymptotic/ambient temperature (°C)

Dynamics: dT/dt = (T_infty - T) / tau
"""
import numpy as np

# ========== CONSTANTS ==========
MIN_TAU_SECONDS = 1e-3  # Minimum tau to prevent division by zero (seconds)
JACOBIAN_ZERO = 0.0  # Zero elements in Jacobian for constant parameters


class ThermalModel:
    """Thermal dynamics model using Newton's law of cooling (3-state)"""
    
    def __init__(self) -> None:
        """Initialize thermal model with Newton's law of cooling dynamics"""
        pass
    
    def f(self, x: np.ndarray, dt: float) -> np.ndarray:
        """
        State evolution function: x(k+1) = f(x(k), dt)
        
        Temperature evolves according to Newton's law of cooling.
        Parameters [tau, Tinf] remain constant (evolution by process noise in EKF).
        
        Args:
            x: State vector [T_current, tau, T_infty]
            dt: Time step (seconds)
            
        Returns:
            Next state vector [T_next, tau, T_infty]
        """
        current_temp, tau, asymptotic_temp = x
        tau = max(tau, MIN_TAU_SECONDS)
        
        # Temperature evolves: T(t+dt) = Tinf + (T - Tinf) * exp(-dt/tau)
        decay_factor = np.exp(-dt / tau)
        next_temp = asymptotic_temp + (current_temp - asymptotic_temp) * decay_factor
        
        # Parameters stay constant (evolve only by process noise in EKF)
        return np.array([next_temp, tau, asymptotic_temp])
    
    def F(self, x: np.ndarray, dt: float) -> np.ndarray:
        """
        Jacobian of state evolution: ∂f/∂x
        
        Computes partial derivatives of next state with respect to current state.
        Used by EKF to propagate covariance matrix.
        
        Args:
            x: State vector [T_current, tau, T_infty]
            dt: Time step (seconds)
            
        Returns:
            3x3 Jacobian matrix of partial derivatives
        """
        current_temp, tau, asymptotic_temp = x
        tau = max(tau, MIN_TAU_SECONDS)
        
        decay_factor = np.exp(-dt / tau)
        temp_difference = current_temp - asymptotic_temp
        
        # Partial derivatives:
        # ∂T_next/∂T_current = exp(-dt/tau)
        # ∂T_next/∂tau = (dt/tau²)(T - Tinf) * exp(-dt/tau)
        # ∂T_next/∂Tinf = 1 - exp(-dt/tau)
        jacobian = np.array([
            [decay_factor, (dt / tau**2) * temp_difference * decay_factor, 1 - decay_factor],
            [JACOBIAN_ZERO, 1.0, JACOBIAN_ZERO],
            [JACOBIAN_ZERO, JACOBIAN_ZERO, 1.0]
        ])
        
        return jacobian
    
    def h(self, x: np.ndarray) -> float:
        """
        Measurement prediction function: z_predicted = h(x)
        
        We measure temperature directly, so measurement equals first state component.
        
        Args:
            x: State vector [T_current, tau, T_infty]
            
        Returns:
            Predicted temperature measurement (scalar)
        """
        current_temp = x[0]
        return float(current_temp)
    
    def H(self, x: np.ndarray) -> np.ndarray:
        """
        Jacobian of measurement function: ∂h/∂x
        
        Since measurement equals T_current (first state), the Jacobian is [1, 0, 0].
        Used by EKF to compute innovation covariance and Kalman gain.
        
        Args:
            x: State vector [T_current, tau, T_infty]
            
        Returns:
            1x3 measurement Jacobian [∂z/∂T, ∂z/∂tau, ∂z/∂Tinf]
        """
        measurement_jacobian = np.array([1.0, JACOBIAN_ZERO, JACOBIAN_ZERO])
        return measurement_jacobian
