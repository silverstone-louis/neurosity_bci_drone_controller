#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
drone_controller.py - Tello Drone Controller for RC Mode
Handles discrete commands and a high-frequency stream of RC commands.
NOTE: This script is for Python 2.7.
"""

from __future__ import print_function, division
import socket
import json
import time
import logging
import threading
import sys
import urllib2

# Configuration
UDP_IP, UDP_PORT, BUFFER_SIZE = "127.0.0.1", 9999, 1024
BCI_BRIDGE_URL = "http://127.0.0.1:5001/update_drone_state"

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Tello SDK import
try:
    from tello import Tello
    TELLO_AVAILABLE = True
except ImportError:
    logger.warning("Tello module not found - running in simulation mode.")
    TELLO_AVAILABLE = False
    class Tello(object):
        def send_command(self, cmd, wait_for_response=True):
            logger.info("[SIMULATED] Tello command: %s", cmd)
            return "ok"

class DroneController(object):
    def __init__(self, test_mode=True):
        self.test_mode = test_mode
        self.tello, self.is_flying, self.running = None, False, True
        self.udp_socket = None
        self.last_rc_command_time = 0

    def initialize_drone(self):
        if not TELLO_AVAILABLE and not self.test_mode:
            logger.error("Tello module missing and not in test mode.")
            return False
        try:
            self.tello = Tello()
            if not self.test_mode:
                self.tello.send_command("command")
                time.sleep(2)
                logger.info("Battery: %s%%", self.tello.send_command("battery?"))
            return True
        except Exception as e:
            logger.error("Failed to initialize Tello: %s", e)
            return False

    def setup_udp_receiver(self):
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.bind((UDP_IP, UDP_PORT))
            self.udp_socket.settimeout(1.0)
            return True
        except Exception as e:
            logger.error("Failed to setup UDP listener: %s", e)
            return False

    def send_completion_callback(self, command, success):
        try:
            data = json.dumps({"command": command, "success": success})
            req = urllib2.Request(BCI_BRIDGE_URL, data, {'Content-Type': 'application/json'})
            urllib2.urlopen(req, timeout=2)
        except Exception as e:
            logger.error("Callback failed for %s: %s", command, e)

    def execute_command(self, command_data):
        """Processes incoming commands from the BCI bridge."""
        command = command_data.get("command")
        
        # --- RC Command Handling ---
        if command == "rc":
            if self.is_flying or self.test_mode:
                params = command_data.get("params", "rc 0 0 0 0")
                # Send RC command without waiting for a response for max throughput
                self.tello.send_command(params, wait_for_response=False)
            return

        # --- Discrete Command Handling ---
        logger.info("Executing discrete command: %s", command)
        
        if command == "takeoff" and not self.is_flying:
            if "ok" in self.tello.send_command("takeoff"):
                self.is_flying = True
                threading.Timer(4.0, self.send_completion_callback, args=["takeoff", True]).start()
        
        elif command == "land" and self.is_flying:
            if "ok" in self.tello.send_command("land"):
                self.is_flying = False
                threading.Timer(3.0, self.send_completion_callback, args=["land", True]).start()

        elif command == "emergency":
            self.tello.send_command("emergency")
            self.is_flying = False

    def receive_commands_thread(self):
        """Main loop to listen for and execute commands."""
        while self.running:
            try:
                data, _ = self.udp_socket.recvfrom(BUFFER_SIZE)
                self.execute_command(json.loads(data.strip()))
            except socket.timeout:
                # If no commands are received for 1 second and we are flying, send a hover command
                # to keep the connection alive and stable.
                if self.is_flying:
                    self.tello.send_command("rc 0 0 0 0", wait_for_response=False)
                continue
            except Exception as e:
                logger.error("Receiver error: %s", e)

    def run(self):
        if not self.initialize_drone() or not self.setup_udp_receiver(): return 1
        threading.Thread(target=self.receive_commands_thread).start()
        print("Drone controller (RC Mode) ready.")
        try:
            while self.running: time.sleep(1)
        except KeyboardInterrupt: pass
        finally:
            self.running = False
            if self.is_flying: self.tello.send_command("land")
            self.udp_socket.close()
            print("Shutdown complete.")

def main():
    test_mode = '--live' not in sys.argv
    if not test_mode:
        if raw_input("Run in LIVE mode? (yes/no): ").lower().strip() != "yes":
            return 0
    DroneController(test_mode=test_mode).run()

if __name__ == "__main__":
    main()
