# config.py
# Centralized configuration for dual-model BCI drone control

import os

# Model paths
MODELS = {
    "3_class": {
        "model_path": r"C:\Users\silve\Tello-Python\neurosity_tello\optuna_hyperparameter_xgboost2\4_class_eeg_xgb_model_optuna_20250619_190434.json",
        "scaler_path": r"C:\Users\silve\Tello-Python\neurosity_tello\optuna_hyperparameter_xgboost2\4_class_eeg_scaler_optuna_20250619_190434.pkl",
        "num_classes": 4,
        "class_names": ["Rest", "Left_Fist", "Right_Fist", "Both_Fists"],
        "features": "covariance"  # Type of features this model expects
    },
    "8_class": {
        "model_path": r"F:\neurosity_final\training_pipeline\kinesis_xgboost_model_softprob.json",
        "scaler_path": r"F:\neurosity_final\training_pipeline\kinesis_scaler.pkl",
        "num_classes": 8,
        # Update class names to match the model trained for Pong
        "class_names": ["Unknown_Disappear34", "Left_Foot", "Left_Arm", "Push", "Tongue", "Disappear22", "Rest", "Jumping_Jacks"],
        "features": "covariance" # Change from "raw" to "covariance"
    }
}

# Per-class confidence thresholds
# These can be tuned based on model performance for each specific class
CONFIDENCE_THRESHOLDS = {
    # 3-class model thresholds
    "Rest": 0.35,          # Lower threshold for rest state
    "Left_Fist": 0.4,     # Higher threshold for active commands
    "Right_Fist": 0.4,
    "Both_Fists": 0.4,   # Threshold for continuous control
    
    # 8-class model thresholds
    "Push": 0.6,         # High threshold for takeoff/land
    "Pull": 0.7,          # Future commands
    "Lift": 0.7,
    "Drop": 0.7,
    "Left": 0.65,         # Slightly lower for directional
    "Right": 0.65,
    "Tongue": 0.7,
    "Feet": 0.8           # Highest threshold for emergency
}

# Sustained command durations (seconds)
# Different commands need different hold times
SUSTAINED_DURATIONS = {
    # 3-class model
    "Left_Fist": 0.5,     # Rotation commands need less hold time
    "Right_Fist": 0.5,
    "Both_Fists": 0.0,    # No sustained duration needed for continuous mode
    
    # 8-class model
    "Push": 1.0,          # Takeoff/land need longer confirmation
    "Pull": 1.0,          # Future movement commands
    "Lift": 1.0,
    "Drop": 1.0,
    "Left": 1.0,
    "Right": 1.0,
    "Tongue": 1.0,
    "Feet": 0.5           # Emergency should be fast
}
PUSH_COMMAND_COOLDOWN = 3.0  # Special cooldown for Push command

# Command mappings
COMMAND_MAPPINGS = {
    # 3-class model - Active mappings
    "Left_Fist": {
        "drone_command": "rotate_left",
        "enabled": True,
        "description": "Rotate counter-clockwise 45 degrees"
    },
    "Right_Fist": {
        "drone_command": "rotate_right", 
        "enabled": True,
        "description": "Rotate clockwise 45 degrees"
    },
    
    # 8-class model - Active mappings
    "Push": {
        "drone_command": "toggle_flight",  # Special: takeoff or land
        "enabled": True,
        "description": "Takeoff if grounded, Land if flying"
    },
    
    # 8-class model - Future mappings (disabled for now)
    "Pull": {
        "drone_command": "back",
        "enabled": False,
        "description": "Move backward 50cm"
    },
    "Lift": {
        "drone_command": "up",
        "enabled": False,
        "description": "Ascend 50cm"
    },
    "Drop": {
        "drone_command": "down",
        "enabled": False,
        "description": "Descend 50cm"
    },
    "Left": {
        "drone_command": "left",
        "enabled": False,
        "description": "Strafe left 50cm"
    },
    "Right": {
        "drone_command": "right",
        "enabled": False,
        "description": "Strafe right 50cm"
    },
    "Tongue": {
        "drone_command": "forward",
        "enabled": False,
        "description": "Move forward 50cm"
    },
    "Feet": {
        "drone_command": "emergency",
        "enabled": False,
        "description": "Emergency stop"
    }
}

# Command priority (higher number = higher priority)
# Used for conflict resolution when multiple commands are detected
COMMAND_PRIORITY = {
    "emergency": 100,      # Always highest priority
    "land": 90,           # Safety commands high priority
    "toggle_flight": 80,  # Takeoff/land
    "forward": 50,        # Movement commands medium priority
    "back": 50,
    "up": 50,
    "down": 50,
    "left": 50,
    "right": 50,
    "rotate_left": 40,    # Rotation lower priority
    "rotate_right": 40,
    "status": 10          # Info commands lowest
}

# State-based command restrictions
# Commands that cannot be executed in certain states
COMMAND_RESTRICTIONS = {
    "grounded": [
        "forward", "back", "left", "right", "up", "down", 
        "rotate_left", "rotate_right"
    ],
    "flying": [
        # All commands allowed when flying
    ],
    "taking_off": [
        # Block all commands during takeoff
        "forward", "back", "left", "right", "up", "down",
        "rotate_left", "rotate_right", "land"
    ],
    "landing": [
        # Block all commands during landing
        "forward", "back", "left", "right", "up", "down",
        "rotate_left", "rotate_right", "takeoff"
    ]
}

# Cooldown periods (seconds)
# Time to wait after certain commands before allowing others
COMMAND_COOLDOWNS = {
    "takeoff": 3.0,       # Wait 3s after takeoff before other commands
    "land": 2.0,          # Wait 2s after landing
    "emergency": 1.0,     # Brief cooldown after emergency
    "default": 0.5        # Default cooldown between commands
}

# EEG Processing Settings
EEG_CONFIG = {
    "channels": 8,
    "sample_rate": 256.0,
    "buffer_length_secs": 8,
    "filter_low": 7.0,
    "filter_high": 30.0,
    "update_rate": 2  # Hz - how often to make predictions
}

# Prediction Buffer Settings
BUFFER_CONFIG = {
    "history_size": 50,           # Number of predictions to keep
    "smoothing_window": 5,        # Window for rolling average
    "jitter_threshold": 0.2,      # Threshold for detecting prediction jitter
    "min_consistent_predictions": 3  # Minimum consistent predictions before command
}

# Safety Settings
SAFETY_CONFIG = {
    "max_flight_time": 600,       # Maximum flight time in seconds (10 min)
    "low_battery_threshold": 20,  # Battery percentage for auto-land
    "command_timeout": 30,        # Timeout for no commands (seconds)
    "enable_auto_land": True      # Auto-land on timeout or low battery
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
    "prediction_logging": True,   # Log all predictions
    "command_logging": True       # Log all commands sent
}

# Continuous Control Configuration
CONTINUOUS_CONTROL = {
    "enabled": True,  # Start with discrete mode by default
    "update_rate_hz": 10,  # 10Hz interpolation rate
    "smoothing_factor": 0.8,  # Higher = more smoothing
    "dead_zone": 0.3,  # Ignore small signals
    "max_rotation_speed": 90,  # degrees per second
    "max_forward_speed": 50,  # cm per second
    "mode_switch_cooldown": 2.0  # Seconds between mode switches
}