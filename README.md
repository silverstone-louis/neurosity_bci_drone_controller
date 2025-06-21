# neurosity_bci_drone_controller

{
  "project_name": "Dual-Model BCI Drone Control System",
  "project_description": "A Brain-Computer Interface system that translates EEG signals from a Neurosity device into drone commands using dual XGBoost models",
  "last_updated": "2025-01-19",
  "primary_goal": "Improve responsiveness of drone controls",
  
  "system_architecture": {
    "data_flow": [
      "Neurosity EEG Device (256Hz, 8 channels)",
      "neurosity_bci_bridge.py (data reception)",
      "filterer.py (bandpass 7-30Hz)",
      "Covariance matrix computation",
      "model_manager.py (dual model inference)",
      "prediction_buffer.py (temporal smoothing)",
      "command_mapper.py (command generation)",
      "UDP to drone_controller.py",
      "Tello drone execution"
    ],
    "update_rate": "2 Hz (configurable)",
    "primary_latency_sources": [
      "Covariance matrix computation",
      "Sustained command detection (1.5-2s)",
      "Model inference time",
      "Network communication"
    ]
  },
  
  "files": {
    "neurosity_bci_bridge.py": {
      "type": "main_orchestrator",
      "language": "Python 3",
      "responsibilities": [
        "Neurosity SDK connection",
        "Raw EEG data streaming",
        "Signal processing coordination",
        "Flask/SocketIO web server",
        "Real-time dashboard updates",
        "UDP command transmission"
      ],
      "key_features": [
        "Instant 'Push' command with 3s cooldown",
        "Dual model prediction handling",
        "WebSocket real-time updates"
      ],
      "dependencies": ["neurosity", "flask", "flask-socketio", "numpy", "xgboost"]
    },
    
    "config.py": {
      "type": "configuration",
      "language": "Python 3",
      "contains": [
        "Model paths and parameters",
        "Confidence thresholds per class",
        "Sustained duration requirements",
        "Command mappings",
        "Network settings",
        "EEG processing parameters"
      ],
      "important_values": {
        "update_rate": 2,
        "sample_rate": 256.0,
        "filter_range": [7.0, 30.0],
        "buffer_length_secs": 8,
        "push_cooldown": 3.0
      }
    },
    
    "model_manager.py": {
      "type": "ml_inference",
      "language": "Python 3",
      "models": {
        "3_class": {
          "classes": ["Rest", "Left_Fist", "Right_Fist"],
          "purpose": "Rotation control",
          "features": "covariance"
        },
        "8_class": {
          "classes": ["Unknown_Disappear34", "Left_Foot", "Left_Arm", "Push", "Tongue", "Disappear22", "Rest", "Jumping_Jacks"],
          "purpose": "Action control (currently only Push active)",
          "features": "covariance"
        }
      },
      "responsibilities": [
        "Load XGBoost models",
        "Feature preparation",
        "Dual model inference",
        "Probability calculation"
      ]
    },
    
    "command_mapper.py": {
      "type": "command_logic",
      "language": "Python 3",
      "features": [
        "State-based command restrictions",
        "Priority-based conflict resolution",
        "Command cooldowns",
        "Drone state tracking"
      ],
      "active_mappings": {
        "Left_Fist": "rotate_left",
        "Right_Fist": "rotate_right",
        "Push": "toggle_flight (takeoff/land)"
      },
      "drone_states": ["grounded", "taking_off", "flying", "landing"]
    },
    
    "prediction_buffer.py": {
      "type": "temporal_processing",
      "language": "Python 3",
      "features": [
        "Prediction history management",
        "Sustained command detection",
        "Per-class thresholds",
        "Jitter prevention",
        "Progress tracking"
      ],
      "parameters": {
        "history_size": 50,
        "smoothing_window": 5,
        "min_consistent_predictions": 3
      }
    },
    
    "filterer.py": {
      "type": "signal_processing",
      "language": "Python 3",
      "features": [
        "Bandpass filtering (Butterworth)",
        "Ring buffer implementation",
        "Covariance matrix computation",
        "Real-time processing"
      ],
      "technical_details": {
        "filter_order": 5,
        "channels": 8,
        "dummy_channels": 2
      }
    },
    
    "drone_controller.py": {
      "type": "drone_interface",
      "language": "Python 2.7",
      "features": [
        "UDP command receiver (port 9999)",
        "Tello SDK integration",
        "State management",
        "Safety features",
        "Test mode support"
      ],
      "commands_supported": [
        "takeoff", "land", "rotate_left", "rotate_right",
        "forward", "back", "left", "right", "up", "down",
        "emergency", "status"
      ]
    },
    
    "drone_control_dashboard.html": {
      "type": "web_interface",
      "technologies": ["HTML5", "CSS3", "JavaScript", "SocketIO"],
      "features": [
        "Real-time prediction visualization",
        "Sustained command progress bars",
        "System status indicators",
        "Command history log",
        "Manual control buttons"
      ],
      "update_mechanism": "WebSocket (SocketIO)"
    }
  },
  
  "current_active_commands": {
    "3_class_model": {
      "Left_Fist": {
        "command": "rotate_left",
        "duration_required": 1.5,
        "confidence_threshold": 0.7,
        "description": "Rotate counter-clockwise 45 degrees"
      },
      "Right_Fist": {
        "command": "rotate_right",
        "duration_required": 1.5,
        "confidence_threshold": 0.7,
        "description": "Rotate clockwise 45 degrees"
      }
    },
    "8_class_model": {
      "Push": {
        "command": "toggle_flight",
        "duration_required": 0,
        "confidence_threshold": 0.75,
        "cooldown": 3.0,
        "description": "Instant takeoff/land toggle",
        "special": "Bypasses sustained detection"
      }
    }
  },
  
  "disabled_commands": [
    "Pull (back)", "Lift (up)", "Drop (down)",
    "Left (strafe left)", "Right (strafe right)",
    "Tongue (forward)", "Feet (emergency)"
  ],
  
  "responsiveness_considerations": {
    "current_latencies": {
      "eeg_to_prediction": "~500ms (2Hz update rate)",
      "sustained_detection": "1500-2000ms (by design)",
      "instant_push": "~500ms + network",
      "total_typical": "2000-2500ms for sustained commands"
    },
    "bottlenecks": [
      "2Hz update rate limits minimum response time",
      "Covariance matrix computation overhead",
      "Sustained detection requirements",
      "Buffer-based smoothing adds delay"
    ],
    "improvement_opportunities": [
      "Increase update rate (currently 2Hz)",
      "Optimize covariance computation",
      "Implement sliding window predictions",
      "Add predictive command initiation",
      "Reduce sustained durations for experienced users",
      "Implement adaptive thresholds",
      "Add command pre-activation feedback"
    ]
  },
  
  "technical_requirements": {
    "python_environments": {
      "bci_bridge": "Python 3.x with numpy, xgboost, flask, neurosity SDK",
      "drone_controller": "Python 2.7 (Tello SDK compatibility)"
    },
    "hardware": {
      "eeg_device": "Neurosity (8 channels, 256Hz)",
      "drone": "DJI Tello",
      "network": "Local network for UDP communication"
    }
  },
  
  "testing_and_safety": {
    "test_mode": "Available in drone_controller.py",
    "safety_features": [
      "State-based command restrictions",
      "Emergency stop command",
      "Command cooldowns",
      "Automatic timeout landing"
    ]
  },
  
  "key_algorithms": {
    "signal_processing": "Butterworth bandpass filter (7-30Hz)",
    "feature_extraction": "Covariance matrix of filtered EEG",
    "classification": "Dual XGBoost models",
    "temporal_smoothing": "Rolling average over 5 predictions",
    "sustained_detection": "Cumulative confidence over time threshold"
  }
}