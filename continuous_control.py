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
        # CHANGE 1: Reduced smoothing for better responsiveness
        self.smoothing_factor = config.get("smoothing_factor", 0.5)  # Was 0.8
        self.dead_zone = config.get("dead_zone", 0.25)
        self.max_rotation_speed = config.get("max_rotation_speed", 100)
        self.max_forward_speed = config.get("max_forward_speed", 60)
        self.scale_exponent = config.get("scale_exponent", 1.5)
        
        # CHANGE 2: Add adaptive dead zone parameters
        self.adaptive_dead_zone = config.get("adaptive_dead_zone", True)
        self.dead_zone_min = 0.15
        self.dead_zone_max = 0.35

        # --- State Tracking ---
        self.last_prediction_time = 0
        self.last_update_time = 0
        
        # --- Smoothed Velocity Values ---
        self.smoothed_rotation_velocity = 0.0
        self.smoothed_forward_velocity = 0.0
        
        # --- Prediction History ---
        self.prediction_history = deque(maxlen=5)
        
        # CHANGE 3: Track signal statistics for adaptive control
        self.signal_stats = {
            "left_mean": 0.0,
            "right_mean": 0.0,
            "noise_level": 0.0
        }

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
            "rest": probs.get("Rest", 0.0),
            "timestamp": current_time,
            "confidence": prediction_4class.get("confidence", 0.0)
        }
        
        self.prediction_history.append(prediction_data)
        self.last_prediction_time = current_time
        
        # CHANGE 4: Update signal statistics for adaptive control
        self._update_signal_stats()
        
        logger.debug(f"Updated prediction: L={prediction_data['left']:.2f}, R={prediction_data['right']:.2f}, B={prediction_data['both']:.2f}")

    def _update_signal_stats(self):
        """Update running statistics of the signal for adaptive control."""
        if len(self.prediction_history) < 3:
            return
            
        recent = list(self.prediction_history)[-3:]
        
        # Calculate recent averages
        left_vals = [p["left"] for p in recent]
        right_vals = [p["right"] for p in recent]
        
        self.signal_stats["left_mean"] = np.mean(left_vals)
        self.signal_stats["right_mean"] = np.mean(right_vals)
        
        # Estimate noise level from Rest probability variations
        rest_vals = [p["rest"] for p in recent]
        self.signal_stats["noise_level"] = np.std(rest_vals)

    def _get_adaptive_dead_zone(self):
        """Calculate adaptive dead zone based on signal quality."""
        if not self.adaptive_dead_zone:
            return self.dead_zone
            
        # Higher noise -> larger dead zone
        noise_factor = min(self.signal_stats["noise_level"] * 2, 1.0)
        adaptive_zone = self.dead_zone_min + (self.dead_zone_max - self.dead_zone_min) * noise_factor
        
        return adaptive_zone

    def _apply_dead_zone_and_scaling(self, value, is_rotation=False):
        """
        Applies a dead zone to an input value and scales the result non-linearly.
        If the value is within the dead zone, it returns 0. Otherwise, it scales
        the remaining range to make the control feel more natural.
        """
        # CHANGE 5: Use adaptive dead zone
        dead_zone = self._get_adaptive_dead_zone() if is_rotation else self.dead_zone
        
        if abs(value) < dead_zone:
            return 0.0
        
        # Scale the value to the range outside the dead zone
        sign = np.sign(value)
        scaled_value = (abs(value) - dead_zone) / (1.0 - dead_zone)
        
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
        confidence = latest_prediction["confidence"]

        # CHANGE 6: Improved rotation calculation using ratio-based approach
        # This preserves control authority when both signals are strong
        total_activation = left_prob + right_prob + 0.01  # epsilon to avoid division by zero
        
        # Primary rotation intent from ratio
        if total_activation > 0.1:  # Only calculate if there's meaningful signal
            rotation_intent = (right_prob - left_prob) / total_activation
        else:
            rotation_intent = 0.0
        
        # CHANGE 7: Add confidence weighting
        # Higher confidence -> more responsive control
        confidence_weight = min(confidence / 0.5, 1.0)  # Normalize to 0.5 threshold
        rotation_intent *= confidence_weight
        
        # CHANGE 8: Forward movement with Both Fists influence
        # When both fists are active, reduce rotation slightly and boost forward
        both_influence = min(both_prob * 2, 1.0)  # Amplify both_fists signal
        
        # Reduce rotation when both fists are active (helps with forward motion stability)
        rotation_damping = 1.0 - (both_influence * 0.3)  # Max 30% reduction
        rotation_intent *= rotation_damping
        
        # Forward intent increases with both_fists
        forward_intent = both_prob
        
        # CHANGE 9: Add "push both to go straight" behavior
        # If both left and right are strongly active together, boost forward
        min_lr_activation = min(left_prob, right_prob)
        if min_lr_activation > 0.4:  # Both hands strongly active
            forward_boost = min_lr_activation * 0.5
            forward_intent = max(forward_intent, forward_boost)

        # --- Apply Dead Zone and Scaling ---
        rotation_intent_scaled = self._apply_dead_zone_and_scaling(rotation_intent, is_rotation=True)
        forward_intent_scaled = self._apply_dead_zone_and_scaling(forward_intent, is_rotation=False)

        # CHANGE 10: Variable smoothing based on signal change rate
        # Less smoothing for rapid changes, more for steady signals
        if len(self.prediction_history) > 1:
            prev_prediction = self.prediction_history[-2]
            change_rate = abs(rotation_intent - self.smoothed_rotation_velocity)
            
            # Dynamic smoothing: faster response for large changes
            dynamic_smoothing = self.smoothing_factor
            if change_rate > 0.3:  # Significant change
                dynamic_smoothing = max(0.3, self.smoothing_factor - 0.2)
        else:
            dynamic_smoothing = self.smoothing_factor

        # --- Apply Smoothing (Exponential Moving Average) ---
        self.smoothed_rotation_velocity = (dynamic_smoothing * self.smoothed_rotation_velocity) + \
                                          (1 - dynamic_smoothing) * rotation_intent_scaled
                                          
        self.smoothed_forward_velocity = (self.smoothing_factor * self.smoothed_forward_velocity) + \
                                         (1 - self.smoothing_factor) * forward_intent_scaled

        return {
            "rotation_velocity": self.smoothed_rotation_velocity,
            "forward_velocity": self.smoothed_forward_velocity,
            "timestamp": int(time.time() * 1000),
            # CHANGE 11: Add debug info
            "debug": {
                "raw_rotation_intent": rotation_intent,
                "confidence_weight": confidence_weight,
                "adaptive_dead_zone": self._get_adaptive_dead_zone(),
                "both_influence": both_influence
            }
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
            return "rc 0 0 0 0"  # Return a hover command if no signals

        # Map our smoothed velocities to the Tello's expected integer range [-100, 100].
        # a: left/right tilt (roll) - We are not using this axis.
        # b: forward/backward (pitch)
        # c: up/down (throttle) - We are not using this axis.
        # d: yaw/rotation
        
        # Forward/Backward control (Pitch)
        b = int(signals["forward_velocity"] * self.max_forward_speed)
        
        # Yaw/Rotation control
        d = int(signals["rotation_velocity"] * self.max_rotation_speed)

        # Ensure values are within the Tello's accepted range.
        b = np.clip(b, -100, 100)
        d = np.clip(d, -100, 100)

        # Assemble the final command string.
        rc_command = f"rc 0 {b} 0 {d}"
        
        # CHANGE 12: Enhanced debug logging
        if abs(d) > 10 or abs(b) > 10:  # Only log significant commands
            logger.debug(f"RC: {rc_command} | Debug: {signals.get('debug', {})}")
        
        return rc_command

    def reset(self):
        """Resets the controller's internal state."""
        self.smoothed_rotation_velocity = 0.0
        self.smoothed_forward_velocity = 0.0
        self.prediction_history.clear()
        self.signal_stats = {"left_mean": 0.0, "right_mean": 0.0, "noise_level": 0.0}
        logger.info("Continuous controller has been reset.")

    def get_state(self):
        """Returns the current internal state for debugging or dashboard display."""
        return {
            "enabled": self.enabled,
            "rotation_velocity": self.smoothed_rotation_velocity,
            "forward_velocity": self.smoothed_forward_velocity,
            "update_rate_hz": self.update_rate_hz,
            "adaptive_dead_zone": self._get_adaptive_dead_zone() if self.adaptive_dead_zone else self.dead_zone,
            "signal_stats": self.signal_stats
        }
