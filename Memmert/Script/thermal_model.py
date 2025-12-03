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


class ThermalModel:
    """Thermal dynamics model using Newton's law of cooling (3-state)"""
    
    def __init__(self):
        # Constants
        self.MIN_TAU = 1e-3  # Minimum tau to prevent division by zero (seconds)
        self.JACOBIAN_CLAMP_THRESHOLD = 0.05  # °C - clamp Jacobian when near equilibrium
    
    def f(self, x, dt):
        """
        State evolution function: x(k+1) = f(x(k), dt)
        
        Temperature evolves according to Newton's law
        Parameters [tau, Tinf] evolve by process noise only
        
        Args:
            x: State vector [T_current, tau, T_infty]
            dt: Time step (seconds)
            
        Returns:
            x_next: Next state vector [T_current, tau, T_infty]
        """
        T_current, tau, Tinf = x
        tau = max(tau, self.MIN_TAU)
        
        # Temperature evolves: T(t+dt) = Tinf + (T - Tinf) * exp(-dt/tau)
        a = np.exp(-dt / tau)
        T_next = Tinf + (T_current - Tinf) * a
        
        # Parameters stay constant (evolve only by process noise in EKF)
        return np.array([T_next, tau, Tinf])
    
    def F(self, x, dt):
        """
        Jacobian of state evolution: ∂f/∂x
        
        Args:
            x: State vector [T_current, tau, T_infty]
            dt: Time step (seconds)
            
        Returns:
            F: 3x3 Jacobian matrix
        """
        T_current, tau, Tinf = x
        tau = max(tau, self.MIN_TAU)
        
        a = np.exp(-dt / tau)
        dT = T_current - Tinf
        
        # ∂T_next/∂T_current = exp(-dt/tau)
        # ∂T_next/∂tau = (dt/tau²)(T - Tinf) * exp(-dt/tau)
        # ∂T_next/∂Tinf = 1 - exp(-dt/tau)
        F = np.array([
            [a, (dt / tau**2) * dT * a, 1 - a],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0]
        ])
        
        return F
    
    def h(self, x):
        """
        Measurement prediction function: z_predicted = h(x)
        
        We measure temperature directly, so h(x) = T_current
        
        Args:
            x: State vector [T_current, tau, T_infty]
            
        Returns:
            z_predicted: Predicted temperature measurement (scalar)
        """
        T_current = x[0]
        return T_current
    
    def H(self, x):
        """
        Jacobian of measurement function: ∂h/∂x
        
        Since h(x) = T_current (first element of state), H = [1, 0, 0]
        
        Args:
            x: State vector [T_current, tau, T_infty]
            
        Returns:
            H: 1x3 measurement Jacobian [∂z/∂T, ∂z/∂tau, ∂z/∂Tinf]
        """
        H = np.array([1.0, 0.0, 0.0])
        return H
