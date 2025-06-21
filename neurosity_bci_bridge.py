# neurosity_bci_bridge.py
# Updated BCI bridge with dual-model and continuous control support

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

# --- MODIFICATION: Import TriadicController ---
from continuous_control import TriadicController
# --- END MODIFICATION ---

# Import existing modules
from config import EEG_CONFIG, UDP_CONFIG, WEB_CONFIG, LOGGING_CONFIG, PUSH_COMMAND_COOLDOWN, CONFIDENCE_THRESHOLDS, CONTINUOUS_CONTROL
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

# --- MODIFICATION: Add TriadicController global ---
triadic_controller = None
# --- END MODIFICATION ---

# UDP Socket for drone commands
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

#push cooldown counter
last_push_command_time = 0

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
    """Initialize command mapper, prediction buffer, and continuous controller"""
    global command_mapper, prediction_buffer, triadic_controller
    
    logger.info("Initializing command mapper...")
    command_mapper = CommandMapper()
    
    logger.info("Initializing prediction buffer...")
    prediction_buffer = PredictionBuffer()

    # --- MODIFICATION: Initialize TriadicController ---
    logger.info("Initializing Triadic Controller...")
    triadic_controller = TriadicController(CONTINUOUS_CONTROL)
    if CONTINUOUS_CONTROL["enabled"]:
        logger.info(">>> Continuous Control Mode is ACTIVE <<<")
    else:
        logger.info(">>> Discrete Control Mode is ACTIVE <<<")
    # --- END MODIFICATION ---

    active_mappings = command_mapper.get_active_mappings()
    logger.info(f"Active discrete command mappings: {len(active_mappings)}")
    for mapping in active_mappings:
        logger.info(f"  {mapping['class']} → {mapping['command']} (threshold: {mapping['threshold']})")

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
        logger.info(f"Filterer initialized: {EEG_CONFIG['filter_low']}-{EEG_CONFIG['filter_high']}Hz, {EEG_CONFIG['channels']} channels")
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

def send_drone_command(command_data, is_rc_command=False):
    """Send command to drone controller via UDP"""
    try:
        if is_rc_command:
            # For RC commands, the data is already a formatted string
            message = command_data.encode('utf-8')
            log_message = command_data
        else:
            # For discrete commands, data is a dict that needs to be JSON encoded
            message = json.dumps(command_data).encode('utf-8')
            log_message = f"{command_data['command']} (source: {command_data.get('source_class', 'Unknown')})"

        udp_socket.sendto(message, (UDP_CONFIG["drone_ip"], UDP_CONFIG["drone_port"]))
        
        # Log command, but avoid spamming for RC commands
        if not is_rc_command:
            logger.info(f"Sent drone command: {log_message}")
            socketio.emit('drone_command_sent', command_data)
        else:
            logger.debug(f"Sent RC command: {log_message}")
            
        return True
    except Exception as e:
        logger.error(f"Failed to send drone command: {e}")
        return False

def process_eeg_data(brainwave_data):
    """Process raw EEG data and make predictions"""
    global cov_counter, filterer, model_manager, command_mapper, prediction_buffer, triadic_controller, last_push_command_time

    if not all([filterer, model_manager, command_mapper, prediction_buffer, triadic_controller]):
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
                
                dual_predictions = model_manager.predict_dual(cov_matrix)
                socketio.emit('dual_predictions', dual_predictions)
                
                # --- Push command logic (works in both discrete and continuous modes) ---
                push_prediction = dual_predictions.get('8_class')
                if push_prediction and push_prediction['predicted_class'] == 'Push' and \
                   push_prediction['confidence'] >= CONFIDENCE_THRESHOLDS['Push'] and \
                   (current_time - last_push_command_time) >= PUSH_COMMAND_COOLDOWN:
                    
                    drone_state = command_mapper.get_state_info()['drone_state']
                    command_to_send = 'takeoff' if drone_state == 'grounded' else 'land'
                    drone_command = {
                        "command": command_to_send, "confidence": push_prediction['confidence'],
                        "source_class": "Push", "source_model": "8_class", "timestamp": int(current_time * 1000)
                    }
                    send_drone_command(drone_command)
                    last_push_command_time = current_time
                    logger.info(f"Instant '{command_to_send}' triggered by Push.")
                    # Prevent this 'Push' from being processed by other systems
                    if 'Push' in push_prediction['probabilities']:
                        push_prediction['probabilities']['Push'] = 0.0
                    push_prediction['predicted_class'] = 'Rest'

                # --- MODIFICATION: Mode-dependent processing ---
                if CONTINUOUS_CONTROL["enabled"]:
                    # --- CONTINUOUS MODE ---
                    prediction_4_class = dual_predictions.get('3_class') # Backend sends 4-class as '3_class' key
                    if prediction_4_class:
                        triadic_controller.update_prediction(prediction_4_class)
                else:
                    # --- DISCRETE MODE ---
                    sustained_commands = prediction_buffer.add_predictions(dual_predictions)
                    for sustained in sustained_commands:
                        prediction_buffer.reset_sustained_command(sustained["class"])
                        command_result = command_mapper.map_predictions_to_commands(
                            {sustained["model"]: {
                                "predicted_class": sustained["class"], "confidence": sustained["average_confidence"]
                            }}, current_time
                        )
                        if command_result:
                            drone_command = {
                                "command": command_result["command"], "confidence": command_result["confidence"],
                                "source_class": command_result["source_class"], "source_model": command_result["source_model"],
                                "timestamp": int(current_time * 1000), "sustained_duration": sustained["duration"]
                            }
                            send_drone_command(drone_command)
                # --- END MODIFICATION ---

                buffer_stats = prediction_buffer.get_buffer_stats()
                sustained_info = prediction_buffer.get_sustained_info()
                mapper_state = command_mapper.get_state_info()
                socketio.emit('system_update', {
                    "buffer_stats": buffer_stats, "sustained_info": sustained_info, "mapper_state": mapper_state
                })
                
        except Exception as e:
            logger.error(f"Error processing EEG data: {e}", exc_info=True)

# --- MODIFICATION: New thread for sending continuous commands ---
def continuous_control_sender_thread():
    """
    A high-frequency thread that continuously sends RC commands to the drone
    when continuous control mode is active.
    """
    global triadic_controller, command_mapper
    
    # Wait for components to be initialized
    while not all([triadic_controller, command_mapper]):
        time.sleep(0.5)

    if not triadic_controller.enabled:
        logger.info("Continuous control sender thread exiting (mode is disabled).")
        return

    logger.info("Continuous control sender thread started.")
    
    while True:
        try:
            # Only send commands if the controller is enabled AND the drone is flying
            is_flying = command_mapper.get_state_info()['drone_state'] == 'flying'
            if triadic_controller.enabled and is_flying:
                rc_command = triadic_controller.get_rc_command()
                if rc_command:
                    send_drone_command(rc_command, is_rc_command=True)
            
            # Sleep to maintain the target update rate
            time.sleep(1.0 / triadic_controller.update_rate_hz)
            
        except Exception as e:
            logger.error(f"Error in continuous control sender: {e}")
            time.sleep(1) # Prevent rapid-fire errors
# --- END MODIFICATION ---

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
        drone_command = {
            "command": command, "confidence": 1.0, "source_class": "Manual",
            "source_model": "User", "timestamp": int(time.time() * 1000)
        }
        success = send_drone_command(drone_command)
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "No command provided"})

@app.route('/update_drone_state', methods=['POST'])
def update_drone_state():
    data = request.json
    command = data.get('command')
    success = data.get('success', True)
    if command and command_mapper:
        command_mapper.handle_command_completion(command, success)
        return jsonify({"success": True})
    return jsonify({"success": False})

# WebSocket Events
@socketio.on('connect')
def handle_connect():
    logger.info(f"Dashboard connected: {request.sid}")
    if all([neurosity, model_manager, command_mapper]):
        emit('connection_status', {
            'neurosity': True, 'models_loaded': True, 'model_info': model_manager.get_model_info(),
            'active_mappings': command_mapper.get_active_mappings(), 'mapper_state': command_mapper.get_state_info()
        })

@socketio.on('request_status')
def handle_status_request():
    status = {
        'neurosity_connected': neurosity is not None, 'models_loaded': model_manager is not None,
        'components_ready': all([command_mapper, prediction_buffer]),
    }
    if model_manager: status['model_info'] = model_manager.get_model_info()
    if command_mapper: status['mapper_state'] = command_mapper.get_state_info()
    if prediction_buffer: status['buffer_stats'] = prediction_buffer.get_buffer_stats()
    emit('system_status', status)

# Main execution
if __name__ == "__main__":
    print("\n" + "="*60)
    print("NEUROSITY DUAL-MODEL BCI -> DRONE CONTROL BRIDGE")
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
        "command": "status", "confidence": 1.0, "source_class": "System",
        "source_model": "Startup", "timestamp": int(time.time() * 1000)
    }
    if send_drone_command(test_command):
        print("✓ Successfully sent test command to drone controller")
    else:
        print("✗ Failed to send test command - check if drone_controller.py is running")
    
    Thread(target=neurosity_stream_runner, daemon=True).start()
    
    # --- MODIFICATION: Start the continuous control sender thread ---
    if CONTINUOUS_CONTROL["enabled"]:
        Thread(target=continuous_control_sender_thread, daemon=True).start()
    # --- END MODIFICATION ---
    
    print(f"\n>>> Dashboard URL: http://{WEB_CONFIG['host']}:{WEB_CONFIG['port']}/ <<<\n")
    
    try:
        socketio.run(app, host=WEB_CONFIG['host'], port=WEB_CONFIG['port'], debug=WEB_CONFIG['debug'])
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        if raw_unsubscribe:
            raw_unsubscribe()
        udp_socket.close()
