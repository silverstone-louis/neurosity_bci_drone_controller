#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
drone_controller.py - Tello Drone Controller with Video Support
Updated to handle heading-based rotation commands, completion feedback, and video streaming.
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
import base64

# Import video module
try:
    from tello_video import TelloVideo
    VIDEO_AVAILABLE = True
except ImportError:
    print("Warning: tello_video module not found - video disabled")
    VIDEO_AVAILABLE = False

# Configuration
UDP_IP = "127.0.0.1"
UDP_PORT = 9999
COMMAND_INTERVAL = 0.5 # For discrete commands
BUFFER_SIZE = 1024
TEST_MODE = False

# BCI Bridge URLs
BCI_BRIDGE_URL = "http://127.0.0.1:5001/update_drone_state"
VIDEO_FRAME_URL = "http://127.0.0.1:5001/video_frame"

# Video Configuration
VIDEO_ENABLED = True
VIDEO_FPS_LIMIT = 15  # Max FPS to send to bridge
VIDEO_QUALITY = 70    # JPEG quality (1-100)

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
        self.video_handler = None
        self.is_flying = False
        self.last_command_time = 0
        self.running = True
        self.udp_socket = None
        self.command_count = 0
        self.start_time = time.time()
        self.rotation_angle = 0
        
        # Video state
        self.video_enabled = VIDEO_ENABLED and VIDEO_AVAILABLE and not test_mode
        self.video_thread = None
        self.last_video_frame_time = 0
        self.video_frame_interval = 1.0 / VIDEO_FPS_LIMIT

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
                
                # Initialize video if enabled
                if self.video_enabled:
                    self.initialize_video()
            else:
                logger.info("TEST MODE: Skipping SDK initialization")
            
            return True
            
        except Exception as e:
            logger.error("Failed to initialize Tello: %s", str(e))
            return False
    
    def initialize_video(self):
        """Initialize video handler"""
        if not self.video_enabled:
            return
            
        try:
            logger.info("Initializing video handler...")
            self.video_handler = TelloVideo()
            
            # Start video with Tello's command socket
            if self.video_handler.start_video(self.tello.socket):
                logger.info("Video handler started")
                
                # Wait for first frame
                if self.video_handler.wait_for_frame(timeout=5.0):
                    logger.info("Video stream active!")
                    
                    # Start video forwarding thread
                    self.video_thread = threading.Thread(target=self._video_forward_thread)
                    self.video_thread.daemon = True
                    self.video_thread.start()
                else:
                    logger.warning("No video frames received")
                    self.video_enabled = False
            else:
                logger.error("Failed to start video handler")
                self.video_enabled = False
                
        except Exception as e:
            logger.error("Video initialization error: %s", e)
            self.video_enabled = False
    
    def _video_forward_thread(self):
        """Thread that forwards video frames to BCI bridge"""
        logger.info("Video forwarding thread started")
        frame_count = 0
        
        while self.running and self.video_enabled:
            try:
                current_time = time.time()
                
                # Rate limit video frames
                if (current_time - self.last_video_frame_time) < self.video_frame_interval:
                    time.sleep(0.01)
                    continue
                
                # Get frame data
                frame_data = self.video_handler.get_frame_with_stats()
                if frame_data['frame'] is None:
                    time.sleep(0.1)
                    continue
                
                # Convert to JPEG
                jpeg_data = self.video_handler.convert_to_jpeg(
                    frame_data['frame'], 
                    quality=VIDEO_QUALITY
                )
                
                if jpeg_data:
                    # Send to BCI bridge
                    self.send_video_frame(jpeg_data, frame_data)
                    frame_count += 1
                    self.last_video_frame_time = current_time
                    
                    if frame_count % 100 == 0:
                        logger.info("Sent %d video frames (FPS: %.1f)", 
                                   frame_count, frame_data['fps'])
                
            except Exception as e:
                logger.error("Video forward error: %s", e)
                time.sleep(1)
        
        logger.info("Video forwarding thread stopped")
    
    def send_video_frame(self, jpeg_data, frame_info):
        """Send video frame to BCI bridge"""
        try:
            # Prepare frame data
            data = json.dumps({
                'frame': base64.b64encode(jpeg_data),
                'timestamp': int(time.time() * 1000),
                'fps': frame_info['fps'],
                'frame_count': frame_info['frame_count']
            })
            
            # Send via HTTP POST
            req = urllib2.Request(VIDEO_FRAME_URL,
                                data=data,
                                headers={'Content-Type': 'application/json'})
            
            # Quick timeout to avoid blocking
            response = urllib2.urlopen(req, timeout=0.5)
            
        except Exception as e:
            # Don't log every frame error to avoid spam
            if self.command_count % 100 == 0:
                logger.warning("Failed to send video frame: %s", e)
    
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
                
        elif command == "ccw" and self.is_flying:
            # Counter-clockwise rotation with specified degrees
            rotation_degrees = degrees if degrees else 45
            result = "ok" if self.test_mode else self.tello.send_command("ccw %d" % rotation_degrees)
            if result == "ok":
                success = True
                self.rotation_angle = (self.rotation_angle - rotation_degrees) % 360
                logger.info("Rotated LEFT %d degrees (heading control)", rotation_degrees)

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
        logger.info("Video enabled: %s", self.video_enabled)
        
        if self.video_handler and self.video_enabled:
            stats = self.video_handler.get_frame_with_stats()
            logger.info("Video frames: %d (FPS: %.1f)", 
                       stats['frame_count'], stats['fps'])
        
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
                command_string = data.strip()

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
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up...")
        
        # Stop video
        if self.video_handler:
            try:
                self.video_handler.stop_video()
            except:
                pass
        
        # Close sockets
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
    
    def run(self):
        """Main run method"""
        print("=" * 60)
        print("DRONE CONTROLLER - WITH VIDEO SUPPORT")
        print("=" * 60)
        print("Video enabled: %s" % self.video_enabled)
        print("")
        
        if not self.initialize_drone() or not self.setup_udp_receiver():
            return 1
        
        self.receive_thread = threading.Thread(target=self.receive_commands)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        
        print("\nDrone controller ready!")
        print("Waiting for commands on %s:%d" % (UDP_IP, UDP_PORT))
        print("Accepts heading-based rotation commands (cw/ccw with degrees)")
        print("Sends completion callbacks to %s" % BCI_BRIDGE_URL)
        if self.video_enabled:
            print("Streaming video to %s" % VIDEO_FRAME_URL)
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
            self.cleanup()
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
