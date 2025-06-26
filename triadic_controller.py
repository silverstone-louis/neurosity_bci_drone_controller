# triadic_controller.py
# Implements spike-based triadic control for smooth drone movement.
# This version is optimized to generate stable, continuous RC commands.

import numpy as np
import time
import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

@dataclass
class SpikeEvent:
    """Represents a detected spike in probability"""
    timestamp: float
    magnitude: float
    class_name: str
    
class TriadicController:
    """
    Manages spike-based conversion of BCI predictions into smooth RC control signals.
    """
    
    def __init__(self, triadic_config: dict, spike_config: dict):
        # Control parameters from config.py
        self.enabled = triadic_config.get("enabled", True)
        self.update_rate_hz = triadic_config.get("update_rate_hz", 15)
        self.smoothing_factor = triadic_config.get("smoothing_factor", 0.7)
        self.dead_zone = triadic_config.get("dead_zone", 0.1)
        self.max_rotation_speed = triadic_config.get("max_rotation_speed", 45)
        self.max_forward_speed = triadic_config.get("max_forward_speed", 50)
        self.scale_exponent = triadic_config.get("scale_exponent", 1.3)
        
        # Spike detection parameters from config.py
        self.spike_enabled = spike_config.get("enabled", True)
        self.buffer_size = spike_config.get("buffer_size", 30)
        self.spike_threshold_std = spike_config.get("spike_threshold_std", 1.5)
        self.min_spike_magnitude = spike_config.get("min_spike_magnitude", 0.1)
        self.spike_decay_rate = spike_config.get("spike_decay_rate", 0.95)
        self.spike_cooldown = spike_config.get("spike_cooldown", 0.5)
        
        # Probability buffers for each class
        self.prob_buffers = { c: deque(maxlen=self.buffer_size) for c in ["Left_Fist", "Right_Fist", "Both_Fists", "Rest"] }
        
        # Spike tracking
        self.active_spikes = { c: [] for c in ["Left_Fist", "Right_Fist", "Both_Fists"] }
        self.last_spike_time = { c: 0 for c in ["Left_Fist", "Right_Fist", "Both_Fists"] }
        
        # Control state
        self.smoothed_rotation_velocity = 0.0
        self.smoothed_forward_velocity = 0.0
        self.last_update_time = time.time()
        
        logger.info("TriadicController (RC Mode) initialized")
        logger.info(f"  Spike detection: {'ENABLED' if self.spike_enabled else 'DISABLED'}")
    
    def update_prediction(self, prediction_4class: dict):
        """Process new prediction, detect spikes, and update control signals."""
        if not self.enabled: return
            
        current_time = time.time()
        probs = prediction_4class.get("probabilities", {})
        
        # Update probability buffers
        for class_name, buffer in self.prob_buffers.items():
            buffer.append(probs.get(class_name, 0.0))
        
        # Detect spikes if enabled
        if self.spike_enabled and len(self.prob_buffers["Left_Fist"]) >= 10:
            self._detect_spikes(current_time)
        
        # Update control signals based on spikes and current probabilities
        self._update_control_signals()
    
    def _detect_spikes(self, current_time: float):
        """Detect probability spikes using rolling statistics."""
        for class_name, buffer in self.prob_buffers.items():
            if class_name == "Rest" or len(buffer) < 10: continue

            buffer_array = np.array(buffer)
            mean, std = np.mean(buffer_array), np.std(buffer_array)
            current_prob = buffer[-1]

            if std > 0.01 and (current_prob - mean) / std > self.spike_threshold_std and \
               current_prob > self.min_spike_magnitude and \
               (current_time - self.last_spike_time[class_name]) > self.spike_cooldown:
                
                spike = SpikeEvent(current_time, current_prob - mean, class_name)
                self.active_spikes[class_name].append(spike)
                self.last_spike_time[class_name] = current_time
        
        self._decay_spikes(current_time)

    def _decay_spikes(self, current_time: float):
        """Apply decay to active spikes and remove expired ones."""
        for class_name, spikes in self.active_spikes.items():
            # List comprehension to filter out old spikes and decay current ones
            self.active_spikes[class_name] = [
                s for s in spikes 
                if (current_time - s.timestamp) < 2.0 and s.magnitude * (self.spike_decay_rate ** (current_time - s.timestamp)) > 0.01
            ]

    def _update_control_signals(self):
        """Convert active spikes into smoothed control signals."""
        left_spike_sum = sum(s.magnitude for s in self.active_spikes["Left_Fist"])
        right_spike_sum = sum(s.magnitude for s in self.active_spikes["Right_Fist"])
        
        # Calculate final control values
        rotation_intent = right_spike_sum - left_spike_sum
        
        # Forward movement is currently disabled for stability testing. Can be enabled later.
        forward_intent = 0.0 # sum(s.magnitude for s in self.active_spikes["Both_Fists"])
        
        # Apply dead zone and non-linear scaling
        rotation_scaled = self._apply_dead_zone_and_scaling(rotation_intent)
        forward_scaled = self._apply_dead_zone_and_scaling(forward_intent)
        
        # Apply smoothing (Exponential Moving Average)
        self.smoothed_rotation_velocity = self._smooth(self.smoothed_rotation_velocity, rotation_scaled)
        self.smoothed_forward_velocity = self._smooth(self.smoothed_forward_velocity, forward_scaled)
    
    def _apply_dead_zone_and_scaling(self, value: float) -> float:
        """Apply dead zone and non-linear scaling to a control value."""
        if abs(value) < self.dead_zone: return 0.0
        sign = np.sign(value)
        scaled_val = (abs(value) - self.dead_zone) / (1.0 - self.dead_zone)
        return sign * (scaled_val ** self.scale_exponent)

    def _smooth(self, old_value, new_value):
        """Helper for exponential moving average."""
        return (self.smoothing_factor * old_value) + (1 - self.smoothing_factor) * new_value

    def get_rc_command(self) -> str:
        """
        Get the current RC command string for the drone.
        This now uses the correct format for Tello.
        """
        if not self.enabled: return "rc 0 0 0 0"
        
        # Map velocities to drone command range [-100, 100]
        # Roll (a), Pitch (b), Throttle (c), Yaw (d)
        roll = 0
        pitch = int(self.smoothed_forward_velocity * self.max_forward_speed)
        throttle = 0
        yaw = int(self.smoothed_rotation_velocity * self.max_rotation_speed)
        
        # Clamp values to ensure they are within the accepted range
        pitch = np.clip(pitch, -100, 100)
        yaw = np.clip(yaw, -100, 100)
        
        # CRITICAL FIX: The RC command format is (roll, pitch, throttle, yaw).
        # We place the rotation value (yaw) in the 4th position.
        return "rc {} {} {} {}".format(roll, pitch, throttle, yaw)
    
    def reset(self):
        """Reset controller state to zero out all velocities and buffers."""
        for buffer in self.prob_buffers.values(): buffer.clear()
        for spike_list in self.active_spikes.values(): spike_list.clear()
        self.smoothed_rotation_velocity = 0.0
        self.smoothed_forward_velocity = 0.0
        logger.info("TriadicController has been reset.")

