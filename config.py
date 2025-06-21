# config.py
# Simplified configuration for heading-based control

import os

# Model paths
MODELS = {
    "4_class": {  # Actually 4 classes but keeping the key for compatibility
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

# Confidence thresholds - SIMPLIFIED
CONFIDENCE_THRESHOLDS = {
    # For heading control (not used directly anymore)
    "Left_Fist": 0.3,
    "Right_Fist": 0.3,
    "Both_Fists": 0.3,
    
    # For Push command
    "Push": 0.6,  # Takeoff/land threshold
}

# Push command cooldown
PUSH_COMMAND_COOLDOWN = 3.0

# SIMPLIFIED Command mappings (most handled by heading controller now)
COMMAND_MAPPINGS = {
    # Push is the only discrete command we use
    "Push": {
        "drone_command": "toggle_flight",
        "enabled": True,
        "description": "Takeoff if grounded, Land if flying"
    },
    
    # These are disabled - handled by heading controller
    "Left_Fist": {"drone_command": "rotate_left", "enabled": False, "description": "Handled by heading control"},
    "Right_Fist": {"drone_command": "rotate_right", "enabled": False, "description": "Handled by heading control"},
    
    # Future commands (all disabled)
    "Pull": {"drone_command": "back", "enabled": False, "description": "Move backward 50cm"},
    "Lift": {"drone_command": "up", "enabled": False, "description": "Ascend 50cm"},
    "Drop": {"drone_command": "down", "enabled": False, "description": "Descend 50cm"},
}

# Command restrictions by drone state
COMMAND_RESTRICTIONS = {
    "grounded": ["forward", "back", "left", "right", "up", "down", "rotate_left", "rotate_right", "cw", "ccw"],
    "taking_off": ["forward", "back", "left", "right", "up", "down", "rotate_left", "rotate_right", "land", "cw", "ccw"],
    "landing": ["forward", "back", "left", "right", "up", "down", "rotate_left", "rotate_right", "takeoff", "cw", "ccw"],
    "flying": []  # All commands allowed
}

# Command cooldowns
COMMAND_COOLDOWNS = {
    "takeoff": 3.0,
    "land": 2.0,
    "default": 0.5
}

# Command priority (for conflict resolution)
COMMAND_PRIORITY = {
    "emergency": 100,
    "land": 90,
    "toggle_flight": 80,
    "cw": 40,
    "ccw": 40,
    "rotate_left": 40,
    "rotate_right": 40,
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

# Prediction Buffer (not really used with heading control)
BUFFER_CONFIG = {
    "history_size": 50,
    "smoothing_window": 5,
    "jitter_threshold": 0.2,
    "min_consistent_predictions": 3
}

# Sustained durations (not used with heading control)
SUSTAINED_DURATIONS = {
    "Push": 1.0,  # Only Push uses sustained detection now
}

# Safety Settings
SAFETY_CONFIG = {
    "max_flight_time": 600,
    "low_battery_threshold": 20,
    "command_timeout": 30,
    "enable_auto_land": True
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
    "prediction_logging": True,
    "command_logging": True
}

# SIMPLIFIED Heading Control Configuration
HEADING_CONTROL = {
    "enabled": True,
    "command_interval": 0.5,    # Send rotation commands every 500ms
    "dead_zone": 0.25,          # Ignore control values below this
    "smoothing_factor": 0.3,    # Lower = more responsive
    "rotation_speeds": {
        "fast": 20,             # Degrees for strong signal
        "slow": 10              # Degrees for weak signal
    }
}

# DEPRECATED - Continuous control not used
CONTINUOUS_CONTROL = {
    "enabled": False
}
