#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
drone_controller.py - Tello Drone Controller
Updated to handle heading-based rotation commands and send completion feedback.
NOTE: This script is intended for Python 2.7.
"""

from __future__ import print_function, division
import socket
import json
import time
import logging
import threading
import sys
import os
import urllib2
import urllib

# Configuration
UDP_IP = "127.0.0.1"
UDP_PORT = 9999
COMMAND_INTERVAL = 0.5 # For discrete commands
BUFFER_SIZE = 1024
TEST_MODE = False

# BCI Bridge callback URL
BCI_BRIDGE_URL = "http://127.0.0.1:5001/update_drone_state"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Tello SDK import
try:
    from tello import Tello
    TELLO_AVAILABLE = True
except ImportError:
    logger.warning("Tello module not found - running in simulation mode")
    TELLO_AVAILABLE = False
    
    # Mock Tello class for testing
    class Tello(object):
        def send_command(self, cmd, wait_for_response=True):
            logger.info("[SIMULATED] Tello command: %s", cmd)
            return "ok"

class DroneController(object):
    def __init__(self, test_mode=True):
        self.test_mode = test_mode
        self.tello = None
        self.is_flying = False
        self.last_command_time = 0
        self.running = True
        self.udp_socket = None
        self.command_count = 0
        self.start_time = time.time()
        self.rotation_angle = 0

    def initialize_drone(self):
        """Initialize Tello drone"""
        try:
            if not TELLO_AVAILABLE and not self.test_mode:
                logger.error("Tello module not available and not in test mode")
                return False
                
            self.tello = Tello()
            logger.info("Tello initialized (test_mode=%s)", self.test_mode)
            
            if not self.test_mode:
                logger.info("Entering SDK mode...")
                self.tello.send_command("command")
                time.sleep(2)
                
                logger.info("Checking battery...")
                battery = self.tello.send_command("battery?")
                logger.info("Battery level: %s", battery)
            else:
                logger.info("TEST MODE: Skipping SDK initialization")
            
            return True
            
        except Exception as e:
            logger.error("Failed to initialize Tello: %s", str(e))
            return False
    
    def setup_udp_receiver(self):
        """Setup UDP socket to receive commands"""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.bind((UDP_IP, UDP_PORT))
            self.udp_socket.settimeout(1.0)
            logger.info("UDP receiver listening on %s:%d", UDP_IP, UDP_PORT)
            return True
        except Exception as e:
            logger.error("Failed to setup UDP: %s", str(e))
            return False

    def send_completion_callback(self, command, success):
        """Send completion notification back to BCI bridge"""
        try:
            data = json.dumps({
                "command": command,
                "success": success,
                "timestamp": int(time.time() * 1000)
            })
            
            req = urllib2.Request(BCI_BRIDGE_URL, 
                                data=data,
                                headers={'Content-Type': 'application/json'})
            
            response = urllib2.urlopen(req, timeout=2)
            result = json.loads(response.read())
            
            if result.get("success"):
                logger.info("Sent completion callback for %s (success=%s)", command, success)
            else:
                logger.warning("Completion callback failed for %s", command)
                
        except Exception as e:
            logger.error("Failed to send completion callback: %s", str(e))

    def can_send_command(self):
        """Check if enough time has passed for discrete commands"""
        return (time.time() - self.last_command_time) >= COMMAND_INTERVAL

    def execute_discrete_command(self, command, source_class="", source_model="", confidence=0.0, degrees=None, **kwargs):
        """Execute a discrete drone command safely"""
        if not self.can_send_command():
            logger.debug("Discrete command rate limited, skipping: %s", command)
            return False
        
        self.command_count += 1
        success = False
        logger.info("[CMD #%d] %s from %s/%s (conf: %.2f)", 
                   self.command_count, command, source_model, source_class, confidence)
        
        # Command execution logic...
        if command == "takeoff":
            if not self.is_flying:
                result = "ok" if self.test_mode else self.tello.send_command("takeoff")
                if result == "ok":
                    self.is_flying = True
                    success = True
                    logger.info(">>> DRONE STATUS: TAKING OFF <<<")
                    
                    # Send completion callback after a delay (simulate takeoff time)
                    def delayed_callback():
                        time.sleep(3.0 if not self.test_mode else 0.5)
                        self.send_completion_callback("takeoff", True)
                    
                    threading.Thread(target=delayed_callback).start()
            else:
                logger.warning("Already flying, ignoring takeoff")
                
        elif command == "land":
            if self.is_flying:
                result = "ok" if self.test_mode else self.tello.send_command("land")
                if result == "ok":
                    self.is_flying = False
                    success = True
                    logger.info(">>> DRONE STATUS: LANDING <<<")
                    
                    # Send completion callback after a delay
                    def delayed_callback():
                        time.sleep(2.0 if not self.test_mode else 0.5)
                        self.send_completion_callback("land", True)
                    
                    threading.Thread(target=delayed_callback).start()
            else:
                logger.warning("Not flying, ignoring land")

        # Handle new heading-based rotation commands
        elif command == "cw" and self.is_flying:
            # Clockwise rotation with specified degrees
            rotation_degrees = degrees if degrees else 45
            result = "ok" if self.test_mode else self.tello.send_command("cw %d" % rotation_degrees)
            if result == "ok":
                success = True
                self.rotation_angle = (self.rotation_angle + rotation_degrees) % 360
                logger.info("Rotated RIGHT %d degrees (heading control)", rotation_degrees)
                # No completion callback for rotation commands - they're immediate
                
        elif command == "ccw" and self.is_flying:
            # Counter-clockwise rotation with specified degrees
            rotation_degrees = degrees if degrees else 45
            result = "ok" if self.test_mode else self.tello.send_command("ccw %d" % rotation_degrees)
            if result == "ok":
                success = True
                self.rotation_angle = (self.rotation_angle - rotation_degrees) % 360
                logger.info("Rotated LEFT %d degrees (heading control)", rotation_degrees)
                # No completion callback for rotation commands - they're immediate

        # Legacy rotation commands (for manual control)
        elif command == "rotate_left" and self.is_flying:
            result = "ok" if self.test_mode else self.tello.send_command("ccw 45")
            if result == "ok":
                success = True
                self.rotation_angle = (self.rotation_angle - 45) % 360
                logger.info("Rotated LEFT 45 degrees (manual)")

        elif command == "rotate_right" and self.is_flying:
            result = "ok" if self.test_mode else self.tello.send_command("cw 45")
            if result == "ok":
                success = True
                self.rotation_angle = (self.rotation_angle + 45) % 360
                logger.info("Rotated RIGHT 45 degrees (manual)")
        
        elif command == "emergency":
            logger.warning("EMERGENCY STOP")
            if not self.test_mode and self.tello: self.tello.send_command("emergency")
            self.is_flying = False
            success = True
            
        elif command == "shutdown":
            logger.info("Shutdown command received")
            self.running = False
            success = True
        
        elif command == "status":
            self.print_status()
            success = True
            
        else:
            if command in ["forward", "back", "left", "right", "up", "down", "cw", "ccw"] and not self.is_flying:
                logger.warning("Cannot execute movement command - drone not flying")
            else:
                logger.warning("Unknown discrete command: %s", command)
        
        # Update command time for discrete commands
        if success:
            self.last_command_time = time.time()
            
        return success
    
    def print_status(self):
        """Print current status"""
        uptime = time.time() - self.start_time
        logger.info("=== DRONE STATUS ===")
        logger.info("Uptime: %.1f seconds", uptime)
        logger.info("Flying: %s", self.is_flying)
        logger.info("Rotation: %d degrees", self.rotation_angle)
        logger.info("Commands received: %d", self.command_count)
        logger.info("Test mode: %s", self.test_mode)
        if not self.test_mode and self.tello:
            try:
                battery = self.tello.send_command("battery?")
                logger.info("Battery: %s%%", battery)
            except Exception as e:
                logger.error("Could not get battery: %s", e)
        logger.info("==================")
    
    def receive_commands(self):
        """Thread to receive UDP commands"""
        logger.info("Command receiver thread started")
        
        while self.running:
            try:
                data, addr = self.udp_socket.recvfrom(BUFFER_SIZE)
                command_string = data.strip() # Remove leading/trailing whitespace

                # Parse JSON command
                try:
                    command_data = json.loads(command_string)
                    command = command_data.get("command")
                    if command:
                        self.execute_discrete_command(**command_data)
                        
                except ValueError:
                    logger.error("Invalid JSON received: %s", command_string[:60])
                        
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error("Receive error: %s", str(e))
    
    def emergency_land(self):
        """Emergency landing procedure"""
        if self.is_flying:
            logger.warning("Performing emergency landing...")
            if not self.test_mode and self.tello:
                try: self.tello.send_command("land")
                except: pass
            self.is_flying = False
    
    def run(self):
        """Main run method"""
        print("=" * 60)
        print("DRONE CONTROLLER - HEADING CONTROL MODE WITH FEEDBACK")
        print("=" * 60)
        
        if not self.initialize_drone() or not self.setup_udp_receiver():
            return 1
        
        self.receive_thread = threading.Thread(target=self.receive_commands)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        
        print("\nDrone controller ready!")
        print("Waiting for commands on %s:%d" % (UDP_IP, UDP_PORT))
        print("Accepts heading-based rotation commands (cw/ccw with degrees)")
        print("Sends completion callbacks to %s" % BCI_BRIDGE_URL)
        print("\nPress Ctrl+C to stop\n")
        
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            logger.info("Shutting down...")
            self.running = False
            self.emergency_land()
            if self.udp_socket:
                self.udp_socket.close()
            if hasattr(self, 'receive_thread') and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=1)
            self.print_status()
            logger.info("Shutdown complete")
        
        return 0

def main():
    test_mode_arg = '--live' not in sys.argv
    if not test_mode_arg:
        print("WARNING: Live mode enabled - drone will actually fly!")
        response = raw_input("Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return 0
    
    controller = DroneController(test_mode=test_mode_arg)
    return controller.run()

if __name__ == "__main__":
    sys.exit(main())
