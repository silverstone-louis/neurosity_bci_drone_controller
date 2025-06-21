# heading_controller.py
# Simplified heading controller that generates rotation commands every 500ms

import numpy as np
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

class HeadingController:
    """
    Simple heading controller that converts BCI predictions to rotation commands.
    Sends commands at regular intervals when drone is flying.
    """
    
    def __init__(self, config):
        """Initialize the heading controller."""
        self.enabled = config.get("enabled", True)
        self.command_interval = config.get("command_interval", 0.5)
        self.dead_zone = config.get("dead_zone", 0.25)
        self.smoothing_factor = config.get("smoothing_factor", 0.3)
        
        # Rotation speeds in degrees
        self.rotation_speeds = config.get("rotation_speeds", {
            "fast": 20,
            "slow": 10
        })
        
        # State
        self.last_prediction_time = 0
        self.current_control_value = 0.0
        self.smoothed_control_value = 0.0
        
        # Keep last few predictions for stability
        self.recent_predictions = deque(maxlen=3)
        
        logger.info("HeadingController initialized (simplified)")
        logger.info(f"  Command interval: {self.command_interval}s")
        logger.info(f"  Dead zone: {self.dead_zone}")
        logger.info(f"  Speeds: slow={self.rotation_speeds['slow']}°, fast={self.rotation_speeds['fast']}°")

    def update_prediction(self, prediction_4class):
        """
        Update with new prediction from the model.
        Called at 2Hz when predictions arrive.
        """
        if not self.enabled:
            return
            
        # Extract probabilities
        probs = prediction_4class.get("probabilities", {})
        
        # Get individual probabilities
        left_prob = probs.get("Left_Fist", 0.0)
        right_prob = probs.get("Right_Fist", 0.0)
        both_prob = probs.get("Both_Fists", 0.0)
        confidence = prediction_4class.get("confidence", 0.0)
        
        # Store recent prediction
        self.recent_predictions.append({
            "left": left_prob,
            "right": right_prob,
            "both": both_prob,
            "confidence": confidence,
            "time": time.time()
        })
        
        # Calculate control value (-1 to +1)
        # Positive = rotate right, Negative = rotate left
        total_activation = left_prob + right_prob + 0.01
        
        if total_activation > 0.1:  # Some meaningful signal
            # Basic differential control
            raw_control = (right_prob - left_prob) / total_activation
            
            # Both fists reduces rotation (stability)
            damping = 1.0 - (both_prob * 0.5)
            raw_control *= damping
        else:
            raw_control = 0.0
        
        self.current_control_value = raw_control
        
        # Apply smoothing
        self.smoothed_control_value = (
            self.smoothing_factor * self.smoothed_control_value + 
            (1 - self.smoothing_factor) * self.current_control_value
        )
        
        self.last_prediction_time = time.time()
        
        logger.debug(f"Control update: raw={raw_control:.3f}, smoothed={self.smoothed_control_value:.3f}")

    def get_rotation_command(self):
        """
        Get the current rotation command based on the smoothed control value.
        Returns command dict or None if in dead zone.
        """
        # Check if we have recent predictions
        if not self.recent_predictions:
            return None
            
        # Get absolute control value
        abs_control = abs(self.smoothed_control_value)
        
        # Dead zone - no rotation
        if abs_control < self.dead_zone:
            return None
        
        # Determine rotation speed based on signal strength
        if abs_control > 0.6:
            degrees = self.rotation_speeds["fast"]
        else:
            degrees = self.rotation_speeds["slow"]
        
        # Determine direction
        if self.smoothed_control_value > 0:
            command = "cw"
            direction = "right"
        else:
            command = "ccw"
            direction = "left"
        
        # Create command data
        return {
            "command": command,
            "degrees": degrees,
            "direction": direction,
            "control_value": float(self.smoothed_control_value),
            "source_class": "Heading",
            "source_model": "4_class",
            "timestamp": int(time.time() * 1000)
        }

    def should_send_command(self, current_time, last_command_time):
        """Check if it's time to send a command."""
        return (current_time - last_command_time) >= self.command_interval

    def reset(self):
        """Reset controller state."""
        self.current_control_value = 0.0
        self.smoothed_control_value = 0.0
        self.recent_predictions.clear()
        logger.info("HeadingController reset")

    def get_state(self):
        """Get current state for debugging."""
        return {
            "enabled": self.enabled,
            "control_value": self.current_control_value,
            "smoothed_value": self.smoothed_control_value,
            "in_dead_zone": abs(self.smoothed_control_value) < self.dead_zone,
            "has_predictions": len(self.recent_predictions) > 0
        }
