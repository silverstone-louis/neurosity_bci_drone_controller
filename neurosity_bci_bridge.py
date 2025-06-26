# neurosity_bci_bridge.py
# Main orchestrator with fixed data flow and spike-based triadic control.
# This version re-enables the high-frequency RC command thread.

import os
import sys
import time
import numpy as np
import socket
import json
from dotenv import load_dotenv
from neurosity import NeurositySDK
import logging
from threading import Thread, Lock, Event
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from collections import deque
from datetime import datetime

# Import modules
from config import (
    EEG_CONFIG, UDP_CONFIG, WEB_CONFIG, LOGGING_CONFIG, 
    PUSH_COMMAND_COOLDOWN, CONFIDENCE_THRESHOLDS, 
    TRIADIC_CONTROL, SPIKE_DETECTION, SAFETY_CONFIG
)
from model_manager import ModelManager
from command_mapper import CommandMapper
from triadic_controller import TriadicController
from filterer import Filterer

# Configuration
ENV_PATH = r"X:\clean_copy\.env"

# Logging Setup
logging.basicConfig(level=getattr(logging, LOGGING_CONFIG["level"]), format=LOGGING_CONFIG["format"])
logger = logging.getLogger(__name__)

# Flask & SocketIO Setup
app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'neurosity_drone_bridge_secret_rc'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# --- Global Variables ---
neurosity, model_manager, command_mapper, triadic_controller, filterer = None, None, None, None, None
raw_unsubscribe = None
data_processing_lock = Lock()
cov_counter, data_received_count, last_data_time, last_push_command_time, state_change_lockout_time = 0, 0, 0, 0, 0
push_command_in_progress, push_was_released, manual_override_active = False, True, False
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
shutdown_flag = Event()


def initialize_system():
    """Load config and initialize all components."""
    global model_manager, command_mapper, triadic_controller, filterer
    load_dotenv(dotenv_path=ENV_PATH)
    model_manager = ModelManager()
    model_manager.load_models()
    command_mapper = CommandMapper()
    triadic_controller = TriadicController(TRIADIC_CONTROL, SPIKE_DETECTION)
    
    # FIX 1: Using keyword arguments for the Filterer to prevent the ValueError.
    filterer = Filterer(
        filter_high=EEG_CONFIG["filter_high"],
        filter_low=EEG_CONFIG["filter_low"],
        nb_chan=EEG_CONFIG["channels"],
        sample_rate=EEG_CONFIG["sample_rate"]
    )

def connect_neurosity():
    """Connect to Neurosity device."""
    global neurosity
    device_id = os.getenv("NEUROSITY_DEVICE_ID")
    email = os.getenv("NEUROSITY_EMAIL")
    password = os.getenv("NEUROSITY_PASSWORD")
    
    if not all([device_id, email, password]):
        logger.error("Neurosity credentials not found.")
        return False
    try:
        # FIX 2: Reverting to the explicit .login() method for authentication.
        # This resolves the "'NeurositySDK' object has no attribute 'client_id'" error.
        neurosity = NeurositySDK({"device_id": device_id})
        neurosity.login({"email": email, "password": password})
        time.sleep(2) # Give time for login to complete
        logger.info("Neurosity login successful.")
        return True
    except Exception as e:
        logger.error(f"Neurosity connection failed: {e}")
        return False

def send_drone_command(command_data):
    """Send command to drone via UDP."""
    try:
        message = json.dumps(command_data).encode('utf-8')
        udp_socket.sendto(message, (UDP_CONFIG["drone_ip"], UDP_CONFIG["drone_port"]))
        return True
    except Exception as e:
        logger.error(f"Failed to send command: {e}")
        return False

def process_eeg_data(brainwave_data):
    """Main callback from Neurosity to process EEG data."""
    global cov_counter, last_data_time, data_received_count, push_was_released, push_command_in_progress, last_push_command_time
    with data_processing_lock:
        last_data_time, data_received_count = time.time(), data_received_count + 1
        raw_data = np.array([ch_data for ch_data in brainwave_data.get('data', []) if ch_data])
        if raw_data.ndim != 2 or raw_data.shape[1] == 0: return

        # EEG data processing pipeline
        filterer.partial_transform(np.vstack((raw_data, np.zeros((2, raw_data.shape[1])))))
        cov_counter += raw_data.shape[1]
        
        # Check if enough samples have been collected to form a new prediction
        if cov_counter < (EEG_CONFIG["sample_rate"] / EEG_CONFIG["update_rate"]): return
        cov_counter = 0
        
        cov_matrix = filterer.get_cov()
        if cov_matrix is None: return
        
        dual_predictions = model_manager.predict_dual(cov_matrix)
        socketio.emit('dual_predictions', dual_predictions)

        # Handle Push command for takeoff/land
        push_pred = dual_predictions.get('8_class')
        if push_pred:
            push_prob = push_pred.get('probabilities', {}).get('Push', 0.0)
            if push_prob < CONFIDENCE_THRESHOLDS['Push'] * 0.7: push_was_released = True
            
            drone_state = command_mapper.get_state_info()['drone_state']
            if push_pred['predicted_class'] == 'Push' and push_prob >= CONFIDENCE_THRESHOLDS['Push'] and \
               push_was_released and not push_command_in_progress and drone_state in ['grounded', 'flying']:
                cmd = 'takeoff' if drone_state == 'grounded' else 'land'
                if send_drone_command({"command": cmd}):
                    push_command_in_progress, push_was_released = True, False
                    command_mapper.update_drone_state('taking_off' if cmd == 'takeoff' else 'landing')

        # Update triadic controller with rotation data
        if dual_predictions.get('4_class') and triadic_controller:
            triadic_controller.update_prediction(dual_predictions['4_class'])

def continuous_command_thread():
    """High-frequency thread to send RC commands for smooth control."""
    logger.info(f"RC command thread started ({TRIADIC_CONTROL['update_rate_hz']} Hz).")
    update_interval = 1.0 / TRIADIC_CONTROL["update_rate_hz"]
    while not shutdown_flag.is_set():
        start_time = time.time()
        drone_state = command_mapper.get_state_info()['drone_state']
        
        # Only send RC commands when flying or in manual override mode
        if (drone_state == 'flying' or manual_override_active) and triadic_controller:
            rc_command = triadic_controller.get_rc_command()
            send_drone_command({"command": "rc", "params": rc_command})
        
        # Sleep to maintain the update rate
        time.sleep(max(0, update_interval - (time.time() - start_time)))

def neurosity_stream_runner():
    """Background thread for Neurosity data streaming."""
    global raw_unsubscribe
    if not neurosity: return
    while not shutdown_flag.is_set():
        try:
            raw_unsubscribe = neurosity.brainwaves_raw(process_eeg_data)
            shutdown_flag.wait()
        except Exception as e:
            logger.error(f"Neurosity stream error: {e}")
            if raw_unsubscribe: raw_unsubscribe()
            if not shutdown_flag.is_set(): time.sleep(5)

# --- Flask & WebSocket Routes ---
@app.route('/')
def index(): return render_template('drone_control_dashboard.html')

@app.route('/update_drone_state', methods=['POST'])
def update_drone_state_route():
    global push_command_in_progress
    data = request.json
    command, success = data.get('command'), data.get('success', True)
    if command:
        if command in ['takeoff', 'land']: push_command_in_progress = False
        if command == 'takeoff' and success and triadic_controller:
            logger.info("Takeoff successful, resetting triadic controller for stable hover.")
            triadic_controller.reset()
        command_mapper.handle_command_completion(command, success)
    return jsonify({"success": True})

# --- Main Execution ---
if __name__ == "__main__":
    initialize_system()
    if not connect_neurosity(): sys.exit(1)
    
    Thread(target=neurosity_stream_runner, daemon=True).start()
    Thread(target=continuous_command_thread, daemon=True).start()

    logger.info("System Ready for RC Mode.")
    try:
        socketio.run(app, host=WEB_CONFIG['host'], port=WEB_CONFIG['port'], use_reloader=False)
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    finally:
        shutdown_flag.set()
        if raw_unsubscribe: raw_unsubscribe()
        udp_socket.close()
