# continuous_control.py
# Implements a triadic controller to convert 4-class BCI predictions 
# into smooth, continuous drone control signals.

import numpy as np
import time
import logging
from collections import deque

# Get a logger instance
logger = logging.getLogger(__name__)

class TriadicController:
    """
    Manages the conversion of discrete BCI predictions (Left, Right, Both Fists)
    into continuous rotation and forward/backward velocity commands for a drone.
    """
    
    def __init__(self, config):
        """
        Initializes the controller with configuration parameters.
        
        Args:
            config (dict): A dictionary containing configuration values, 
                           typically from the CONTINUOUS_CONTROL section of config.py.
        """
        # --- Control Parameters ---
        self.enabled = config.get("enabled", False)
        self.update_rate_hz = config.get("update_rate_hz", 10)
        self.smoothing_factor = config.get("smoothing_factor", 0.8)
        self.dead_zone = config.get("dead_zone", 0.25)
        self.max_rotation_speed = config.get("max_rotation_speed", 100)  # Max value for Tello RC command
        self.max_forward_speed = config.get("max_forward_speed", 60)    # Max value for Tello RC command
        self.scale_exponent = config.get("scale_exponent", 1.5) # For non-linear response

        # --- State Tracking ---
        self.last_prediction_time = 0
        self.last_update_time = 0
        
        # --- Smoothed Velocity Values ---
        # These values represent the current "intended" state, smoothed over time.
        self.smoothed_rotation_velocity = 0.0
        self.smoothed_forward_velocity = 0.0
        
        # --- Prediction History ---
        # Stores the last few predictions to allow for interpolation, though not used in this version.
        self.prediction_history = deque(maxlen=5)

        logger.info("TriadicController initialized.")
        logger.info(f"  - Dead Zone: {self.dead_zone}")
        logger.info(f"  - Smoothing Factor: {self.smoothing_factor}")
        logger.info(f"  - Max Speeds (Fwd/Rot): {self.max_forward_speed} / {self.max_rotation_speed}")

    def update_prediction(self, prediction_4class):
        """
        Accepts a new 4-class model prediction and stores its probabilities.
        This method should be called every time the model generates a new prediction (e.g., at 2Hz).
        
        Args:
            prediction_4class (dict): A dictionary containing the prediction result,
                                      including a 'probabilities' dictionary.
        """
        if not self.enabled:
            return

        current_time = time.time()
        
        # Extract the necessary probabilities from the prediction result
        probs = prediction_4class.get("probabilities", {})
        prediction_data = {
            "left": probs.get("Left_Fist", 0.0),
            "right": probs.get("Right_Fist", 0.0),
            "both": probs.get("Both_Fists", 0.0),
            "timestamp": current_time,
            "confidence": prediction_4class.get("confidence", 0.0)
        }
        
        self.prediction_history.append(prediction_data)
        self.last_prediction_time = current_time
        
        logger.debug(f"Updated prediction: L={prediction_data['left']:.2f}, R={prediction_data['right']:.2f}, B={prediction_data['both']:.2f}")

    def _apply_dead_zone_and_scaling(self, value):
        """
        Applies a dead zone to an input value and scales the result non-linearly.
        If the value is within the dead zone, it returns 0. Otherwise, it scales
        the remaining range to make the control feel more natural.
        """
        if abs(value) < self.dead_zone:
            return 0.0
        
        # Scale the value to the range outside the dead zone
        sign = np.sign(value)
        scaled_value = (abs(value) - self.dead_zone) / (1.0 - self.dead_zone)
        
        # Apply an exponential scaling for a more responsive feel
        return sign * (scaled_value ** self.scale_exponent)

    def calculate_control_signals(self):
        """
        Calculates the continuous control signals based on the latest prediction.
        This method should be called at a high frequency (e.g., 10Hz) to generate
        smooth commands.
        
        Returns:
            dict or None: A dictionary with the calculated velocity signals, or None if disabled
                          or no predictions are available.
        """
        if not self.enabled or not self.prediction_history:
            return None

        # Get the most recent prediction from our history
        latest_prediction = self.prediction_history[-1]
        left_prob = latest_prediction["left"]
        right_prob = latest_prediction["right"]
        both_prob = latest_prediction["both"]

        # --- Calculate Raw Control Intents ---
        # Rotation is determined by the difference between right and left fist probabilities.
        rotation_intent = right_prob - left_prob  # Range: [-1, 1]
        
        # Forward movement is determined by the 'both fists' probability.
        forward_intent = both_prob # Range: [0, 1]

        # --- Apply Dead Zone and Scaling ---
        # This prevents small, unintentional fluctuations from causing drone movement.
        rotation_intent_scaled = self._apply_dead_zone_and_scaling(rotation_intent)
        forward_intent_scaled = self._apply_dead_zone_and_scaling(forward_intent)

        # --- Apply Smoothing (Exponential Moving Average) ---
        # This prevents jerky movements by blending the new intent with the previous state.
        self.smoothed_rotation_velocity = (self.smoothing_factor * self.smoothed_rotation_velocity) + \
                                          (1 - self.smoothing_factor) * rotation_intent_scaled
                                          
        self.smoothed_forward_velocity = (self.smoothing_factor * self.smoothed_forward_velocity) + \
                                         (1 - self.smoothing_factor) * forward_intent_scaled

        return {
            "rotation_velocity": self.smoothed_rotation_velocity, # Final smoothed value [-1, 1]
            "forward_velocity": self.smoothed_forward_velocity,   # Final smoothed value [0, 1]
            "timestamp": int(time.time() * 1000)
        }

    def get_rc_command(self):
        """
        Converts the current smoothed velocities into a Tello-compatible RC command string.
        The Tello drone's RC command takes four values: left/right, forward/back, up/down, and yaw.
        
        Returns:
            str or None: The formatted RC command string (e.g., "rc 0 50 0 -75") or None.
        """
        signals = self.calculate_control_signals()
        if not signals:
            return "rc 0 0 0 0" # Return a hover command if no signals

        # Map our smoothed velocities to the Tello's expected integer range [-100, 100].
        # a: left/right tilt (roll) - We are not using this axis.
        # b: forward/backward (pitch)
        # c: up/down (throttle) - We are not using this axis.
        # d: yaw/rotation
        
        # Forward/Backward control (Pitch)
        # Our forward_velocity is [0, 1], so we map it directly.
        b = int(signals["forward_velocity"] * self.max_forward_speed)
        
        # Yaw/Rotation control
        # Our rotation_velocity is [-1, 1].
        d = int(signals["rotation_velocity"] * self.max_rotation_speed)

        # Ensure values are within the Tello's accepted range.
        b = np.clip(b, -100, 100)
        d = np.clip(d, -100, 100)

        # Assemble the final command string.
        rc_command = f"rc 0 {b} 0 {d}"
        logger.debug(f"Generated RC Command: {rc_command}")
        
        return rc_command

    def reset(self):
        """Resets the controller's internal state."""
        self.smoothed_rotation_velocity = 0.0
        self.smoothed_forward_velocity = 0.0
        self.prediction_history.clear()
        logger.info("Continuous controller has been reset.")

    def get_state(self):
        """Returns the current internal state for debugging or dashboard display."""
        return {
            "enabled": self.enabled,
            "rotation_velocity": self.smoothed_rotation_velocity,
            "forward_velocity": self.smoothed_forward_velocity,
            "update_rate_hz": self.update_rate_hz
        }
