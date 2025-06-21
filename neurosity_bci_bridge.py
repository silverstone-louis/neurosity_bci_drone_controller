# neurosity_bci_bridge.py
# Simplified BCI bridge with heading-based rotation control
# REVISED: Added proper state handling and manual override

import os
import sys
import time
import numpy as np
if not hasattr(np,'_core'):
    np.core = np.core
import socket
import json
from dotenv import load_dotenv
from neurosity import NeurositySDK
import logging
from threading import Thread, Lock
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from collections import deque
from datetime import datetime

# Import the heading controller
from heading_controller import HeadingController

# Import existing modules
from config import EEG_CONFIG, UDP_CONFIG, WEB_CONFIG, LOGGING_CONFIG, PUSH_COMMAND_COOLDOWN, CONFIDENCE_THRESHOLDS, HEADING_CONTROL
from model_manager import ModelManager
from command_mapper import CommandMapper
from prediction_buffer import PredictionBuffer

try:
    from filterer import Filterer, RingBufferSignal
except ImportError:
    print("ERROR: Could not import Filterer. Please ensure 'filterer.py' is accessible.")
    sys.exit(1)

# Configuration
ENV_PATH = r"X:\clean_copy\.env"

# Logging Setup
logging.basicConfig(
    level=getattr(logging, LOGGING_CONFIG["level"]),
    format=LOGGING_CONFIG["format"]
)
logger = logging.getLogger(__name__)

# Flask & SocketIO Setup
app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'neurosity_drone_bridge_secret'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Global Variables
neurosity = None
model_manager = None
command_mapper = None
prediction_buffer = None
filterer = None
raw_unsubscribe = None
cov_counter = 0
data_processing_lock = Lock()

# Heading controller
heading_controller = None

# UDP Socket for drone commands
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Command timing
last_push_command_time = 0
last_rotation_command_time = 0

# Manual override flag
manual_override_active = False

def load_dotenv_config():
    logger.info(f"Loading .env from: {ENV_PATH}")
    if not os.path.exists(ENV_PATH):
        logger.error(f".env file not found at {ENV_PATH}")
        sys.exit(1)
    load_dotenv(dotenv_path=ENV_PATH)

def initialize_models():
    """Initialize the model manager and load models"""
    global model_manager
    logger.info("Initializing model manager...")
    model_manager = ModelManager()
    if not model_manager.load_models():
        logger.error("Failed to load models")
        sys.exit(1)
    if not model_manager.validate_models():
        logger.warning("Model validation showed potential issues")
    model_info = model_manager.get_model_info()
    for model_name, info in model_info.items():
        logger.info(f"{model_name}: {info}")

def initialize_components():
    """Initialize all components"""
    global command_mapper, prediction_buffer, heading_controller
    
    logger.info("Initializing command mapper...")
    command_mapper = CommandMapper()
    
    logger.info("Initializing prediction buffer...")
    prediction_buffer = PredictionBuffer()

    logger.info("Initializing heading controller...")
    heading_controller = HeadingController(HEADING_CONTROL)
    
    logger.info(">>> SIMPLIFIED HEADING CONTROL ACTIVE <<<")

def initialize_filterer():
    global filterer
    logger.info("Initializing Filterer...")
    try:
        filterer = Filterer(
            filter_high=EEG_CONFIG["filter_high"],
            filter_low=EEG_CONFIG["filter_low"],
            nb_chan=EEG_CONFIG["channels"],
            sample_rate=EEG_CONFIG["sample_rate"],
            signal_buffer_length=int(EEG_CONFIG["sample_rate"] * EEG_CONFIG["buffer_length_secs"])
        )
        logger.info(f"Filterer initialized: {EEG_CONFIG['filter_low']}-{EEG_CONFIG['filter_high']}Hz")
    except Exception as e:
        logger.error(f"Filterer initialization failed: {e}")
        sys.exit(1)

def connect_neurosity():
    global neurosity
    device_id = os.getenv("NEUROSITY_DEVICE_ID")
    email = os.getenv("NEUROSITY_EMAIL")
    password = os.getenv("NEUROSITY_PASSWORD")
    if not all([device_id, email, password]):
        logger.error("Neurosity credentials not found in .env")
        return False
    try:
        neurosity = NeurositySDK({"device_id": device_id})
        logger.info(f"Neurosity SDK initialized for device: {device_id}")
        neurosity.login({"email": email, "password": password})
        time.sleep(2)
        logger.info("Neurosity login successful")
        return True
    except Exception as e:
        logger.error(f"Neurosity connection failed: {e}")
        return False

def send_drone_command(command_data):
    """Send command to drone controller via UDP"""
    try:
        message = json.dumps(command_data).encode('utf-8')
        udp_socket.sendto(message, (UDP_CONFIG["drone_ip"], UDP_CONFIG["drone_port"]))
        
        logger.info(f"Sent: {command_data.get('command', 'unknown')} "
                   f"{command_data.get('degrees', '')}° "
                   f"(control: {command_data.get('control_value', 0):.2f})")
        
        socketio.emit('drone_command_sent', command_data)
        return True
    except Exception as e:
        logger.error(f"Failed to send drone command: {e}")
        return False

def process_eeg_data(brainwave_data):
    """Process raw EEG data and make predictions"""
    global cov_counter, last_push_command_time
    
    if not all([filterer, model_manager, command_mapper, prediction_buffer, heading_controller]):
        return

    with data_processing_lock:
        try:
            raw_data = brainwave_data.get('data')
            if not raw_data or not isinstance(raw_data, list) or not raw_data[0]:
                return
            
            num_samples = len(raw_data[0])
            eeg_data = np.zeros((EEG_CONFIG["channels"], num_samples))
            for i in range(min(EEG_CONFIG["channels"], len(raw_data))):
                if len(raw_data[i]) == num_samples:
                    eeg_data[i, :] = raw_data[i]
            
            dummy_data = np.zeros((2, num_samples))
            data_for_filter = np.vstack((eeg_data, dummy_data))
            
            filterer.partial_transform(data_for_filter)
            cov_counter += 1

            if cov_counter >= EEG_CONFIG["update_rate"]:
                cov_counter = 0
                current_time = time.time()

                cov_matrix = filterer.get_cov()
                if cov_matrix is None or cov_matrix.size == 0:
                    return
                
                # Get predictions from both models
                dual_predictions = model_manager.predict_dual(cov_matrix)
                
                # Log what keys we got
                logger.debug(f"Prediction keys: {[k for k in dual_predictions.keys() if k not in ['timestamp', 'total_inference_time']]}")
                
                socketio.emit('dual_predictions', dual_predictions)
                
                # Handle Push command (8-class model)
                push_prediction = dual_predictions.get('8_class')
                if push_prediction and push_prediction['predicted_class'] == 'Push' and \
                   push_prediction['confidence'] >= CONFIDENCE_THRESHOLDS['Push'] and \
                   (current_time - last_push_command_time) >= PUSH_COMMAND_COOLDOWN:
                    
                    drone_state = command_mapper.get_state_info()['drone_state']
                    command_to_send = 'takeoff' if drone_state == 'grounded' else 'land'
                    drone_command = {
                        "command": command_to_send,
                        "confidence": push_prediction['confidence'],
                        "source_class": "Push",
                        "source_model": "8_class",
                        "timestamp": int(current_time * 1000)
                    }
                    send_drone_command(drone_command)
                    last_push_command_time = current_time
                    logger.info(f">>> {command_to_send.upper()} triggered by Push thought <<<")
                
                # Update heading controller with 4-class predictions
                prediction_4_class = dual_predictions.get('4_class')
                if prediction_4_class and heading_controller:
                    heading_controller.update_prediction(prediction_4_class)
                    logger.debug(f"Updated heading controller with {prediction_4_class.get('predicted_class')} "
                               f"(conf: {prediction_4_class.get('confidence', 0):.2f})")
                
                # Send status update
                mapper_state = command_mapper.get_state_info()
                if heading_controller:
                    mapper_state['heading_control'] = heading_controller.get_state()
                
                socketio.emit('system_update', {
                    "mapper_state": mapper_state,
                    "timestamp": int(current_time * 1000)
                })
                
        except Exception as e:
            logger.error(f"Error processing EEG data: {e}", exc_info=True)

def rotation_command_thread():
    """
    Thread that sends rotation commands at regular intervals.
    Only sends commands when drone is flying.
    """
    global heading_controller, command_mapper, last_rotation_command_time, manual_override_active
    
    # Wait for initialization
    while not all([heading_controller, command_mapper]):
        time.sleep(0.5)
    
    logger.info("Rotation command thread started")
    last_log_time = 0
    
    while True:
        try:
            current_time = time.time()
            
            # Check if drone is flying
            drone_state = command_mapper.get_state_info()['drone_state']
            is_flying = drone_state == 'flying'
            
            # Also check manual override
            if manual_override_active:
                is_flying = True
                
            # Log state periodically for debugging
            if current_time - last_log_time > 5.0:
                logger.info(f"Rotation thread: drone_state={drone_state}, is_flying={is_flying}, "
                           f"manual_override={manual_override_active}")
                last_log_time = current_time
            
            # Check if it's time to potentially send a command
            if heading_controller.should_send_command(current_time, last_rotation_command_time):
                if is_flying and heading_controller.enabled:
                    # Get rotation command (might be None if in dead zone)
                    command = heading_controller.get_rotation_command()
                    
                    if command:
                        # Send the command
                        send_drone_command(command)
                        last_rotation_command_time = current_time
                    else:
                        # In dead zone - no command sent
                        last_rotation_command_time = current_time
                else:
                    # Not flying - don't send commands but update timer
                    last_rotation_command_time = current_time
            
            # Check frequently for smooth operation
            time.sleep(0.05)  # 50ms
            
        except Exception as e:
            logger.error(f"Error in rotation command thread: {e}")
            time.sleep(1)

def neurosity_stream_runner():
    """Background thread for Neurosity streaming"""
    global raw_unsubscribe, neurosity
    if not neurosity:
        logger.error("Neurosity not initialized")
        return
    logger.info("Starting Neurosity stream...")
    try:
        raw_unsubscribe = neurosity.brainwaves_raw(process_eeg_data)
        logger.info("Subscribed to raw EEG stream")
        while True:
            time.sleep(1)
    except Exception as e:
        logger.error(f"Neurosity stream error: {e}")

# Flask Routes
@app.route('/')
def index():
    return render_template('drone_control_dashboard.html')

@app.route('/send_command', methods=['POST'])
def send_command():
    data = request.json
    command = data.get('command')
    if command:
        # Map dashboard commands to drone commands
        if command == 'rotate_left':
            drone_command = {
                "command": "ccw",
                "degrees": 45,
                "confidence": 1.0,
                "source_class": "Manual",
                "source_model": "User",
                "timestamp": int(time.time() * 1000)
            }
        elif command == 'rotate_right':
            drone_command = {
                "command": "cw",
                "degrees": 45,
                "confidence": 1.0,
                "source_class": "Manual",
                "source_model": "User",
                "timestamp": int(time.time() * 1000)
            }
        else:
            drone_command = {
                "command": command,
                "confidence": 1.0,
                "source_class": "Manual",
                "source_model": "User",
                "timestamp": int(time.time() * 1000)
            }
        success = send_drone_command(drone_command)
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "No command provided"})

@app.route('/update_drone_state', methods=['POST'])
def update_drone_state():
    """Handle drone state updates from the drone controller"""
    data = request.json
    command = data.get('command')
    success = data.get('success', True)
    
    logger.info(f"Received drone state update: command={command}, success={success}")
    
    if command and command_mapper:
        command_mapper.handle_command_completion(command, success)
        
        # Emit updated state to dashboard
        mapper_state = command_mapper.get_state_info()
        socketio.emit('system_update', {
            "mapper_state": mapper_state,
            "command_completion": {
                "command": command,
                "success": success
            }
        })
        
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/toggle_manual_override', methods=['POST'])
def toggle_manual_override():
    """Toggle manual override for testing heading control without takeoff"""
    global manual_override_active
    manual_override_active = not manual_override_active
    logger.info(f"Manual override {'ENABLED' if manual_override_active else 'DISABLED'}")
    
    socketio.emit('manual_override_status', {
        "active": manual_override_active
    })
    
    return jsonify({
        "success": True,
        "manual_override": manual_override_active
    })

# WebSocket Events
@socketio.on('connect')
def handle_connect():
    logger.info(f"Dashboard connected: {request.sid}")
    emit_status()

@socketio.on('request_status')
def handle_status_request():
    emit_status()

def emit_status():
    """Emit current system status"""
    status = {
        'neurosity_connected': neurosity is not None,
        'models_loaded': model_manager is not None,
        'heading_control_enabled': HEADING_CONTROL["enabled"],
        'manual_override': manual_override_active
    }
    if model_manager:
        status['model_info'] = model_manager.get_model_info()
    if command_mapper:
        mapper_state = command_mapper.get_state_info()
        if heading_controller:
            mapper_state['heading_control'] = heading_controller.get_state()
        status['mapper_state'] = mapper_state
    socketio.emit('system_status', status)

# Main execution
if __name__ == "__main__":
    print("\n" + "="*60)
    print("NEUROSITY BCI DRONE CONTROL - SIMPLIFIED")
    print("="*60 + "\n")
    
    load_dotenv_config()
    initialize_models()
    initialize_components()
    initialize_filterer()
    
    if not connect_neurosity():
        print("ERROR: Failed to connect to Neurosity")
        sys.exit(1)
    
    print("\nTesting drone controller connection...")
    test_command = {
        "command": "status",
        "confidence": 1.0,
        "source_class": "System",
        "source_model": "Startup",
        "timestamp": int(time.time() * 1000)
    }
    if send_drone_command(test_command):
        print("✓ Successfully sent test command to drone controller")
    else:
        print("✗ Failed to send test command - check if drone_controller.py is running")
    
    # Start background threads
    Thread(target=neurosity_stream_runner, daemon=True).start()
    Thread(target=rotation_command_thread, daemon=True).start()
    
    print(f"\n>>> Dashboard URL: http://{WEB_CONFIG['host']}:{WEB_CONFIG['port']}/ <<<")
    print(">>> Commands: Push = Takeoff/Land, Left/Right Fist = Rotation <<<")
    print(f">>> Rotation commands sent every {HEADING_CONTROL['command_interval']}s when flying <<<")
    print(">>> NEW: Manual override available for testing rotation without takeoff <<<\n")
    
    try:
        socketio.run(app, host=WEB_CONFIG['host'], port=WEB_CONFIG['port'], debug=WEB_CONFIG['debug'])
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        if raw_unsubscribe:
            raw_unsubscribe()
        udp_socket.close()
