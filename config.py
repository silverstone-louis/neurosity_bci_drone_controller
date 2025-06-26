# config.py
# Simplified configuration with spike-based control

import os

# Model paths - 4-class model
MODELS = {
    "4_class": {
        "model_path": r"C:\Users\silve\Tello-Python\neurosity_tello\optuna_hyperparameter_xgboost2\4_class_eeg_xgb_model_optuna_20250619_190434.json",
        "scaler_path": r"C:\Users\silve\Tello-Python\neurosity_tello\optuna_hyperparameter_xgboost2\4_class_eeg_scaler_optuna_20250619_190434.pkl",
        "num_classes": 4,
        "class_names": ["Rest", "Left_Fist", "Right_Fist", "Both_Fists"],
        "features": "covariance"
    },
    "8_class": {
        "model_path": r"F:\neurosity_final\training_pipeline\kinesis_xgboost_model_softprob.json",
        "scaler_path": r"F:\neurosity_final\training_pipeline\kinesis_scaler.pkl",
        "num_classes": 8,
        "class_names": ["Unknown_Disappear34", "Left_Foot", "Left_Arm", "Push", "Tongue", "Disappear22", "Rest", "Jumping_Jacks"],
        "features": "covariance"
    }
}

# Confidence thresholds
CONFIDENCE_THRESHOLDS = {
    # These are base thresholds - spike detection will be primary mechanism
    "Left_Fist": 0.3,
    "Right_Fist": 0.3,
    "Both_Fists": 0.3,
    "Push": 0.6,  # For takeoff/land
}

# Spike Detection Configuration
SPIKE_DETECTION = {
    "enabled": True,
    "buffer_size": 30,  # Number of samples for rolling statistics
    "spike_threshold_std": 1.5,  # Spike when probability > mean + (threshold * std_dev)
    "min_spike_magnitude": 0.1,  # Minimum probability to consider
    # MODIFICATION: Increased decay rate for smoother, less abrupt control changes.
    # A higher value means the spike's influence fades more slowly.
    "spike_decay_rate": 0.95,  # Original: 0.85
    "spike_cooldown": 0.5,  # Seconds between spikes for same class
}

# Triadic Control Configuration
TRIADIC_CONTROL = {
    "enabled": True,
    "update_rate_hz": 15,  # Command update frequency
    "smoothing_factor": 0.7,  # For output smoothing
    "dead_zone": 0.1,  # Minimum control signal to act on
    # MODIFICATION: Reduced max rotation speed for more manageable control.
    "max_rotation_speed": 45,  # Original: 90
    # NOTE: max_forward_speed is currently disabled in triadic_controller.py for stability testing.
    "max_forward_speed": 50,  # Maximum forward speed
    "scale_exponent": 1.3,  # Non-linear scaling
}

# Push command cooldown
PUSH_COMMAND_COOLDOWN = 3.0

# Command mappings (simplified)
COMMAND_MAPPINGS = {
    "Push": {
        "drone_command": "toggle_flight",
        "enabled": True,
        "description": "Takeoff if grounded, Land if flying"
    }
}

# Command restrictions by drone state
COMMAND_RESTRICTIONS = {
    "grounded": ["rc", "forward", "back", "left", "right", "up", "down"],
    "taking_off": ["rc", "takeoff", "land"],
    "landing": ["rc", "takeoff", "land"],
    "flying": []
}

# Command cooldowns
COMMAND_COOLDOWNS = {
    "takeoff": 3.0,
    "land": 2.0,
    "default": 0.5
}

# Command priority
COMMAND_PRIORITY = {
    "emergency": 100,
    "land": 90,
    "takeoff": 80,
}

# EEG Processing
EEG_CONFIG = {
    "channels": 8,
    "sample_rate": 256.0,
    "buffer_length_secs": 8,
    "filter_low": 7.0,
    "filter_high": 30.0,
    "update_rate": 2  # Hz - predictions per second
}

# Feature Buffer
FEATURE_BUFFER_CONFIG = {
    "max_length": 50,  # Maximum number of predictions to keep
    "required_for_stats": 10  # Minimum predictions needed for statistics
}

# Safety Settings
SAFETY_CONFIG = {
    "max_flight_time": 600,
    "low_battery_threshold": 20,
    "command_timeout": 30,
    "enable_auto_land": True,
    "data_timeout": 5.0  # Seconds without data before safety shutdown
}

# UDP Communication
UDP_CONFIG = {
    "drone_ip": "127.0.0.1",
    "drone_port": 9999,
    "buffer_size": 1024
}

# Web Server
WEB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5001,
    "debug": False
}

# Logging
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    "detailed_timing": False  # Set True for detailed timing logs
}
