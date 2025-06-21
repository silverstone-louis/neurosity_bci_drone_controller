#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tello.py - Minimal Tello drone control module for Python 2.7
Based on official DJI Tello SDK
"""

import socket
import threading
import time
import logging

logger = logging.getLogger(__name__)

class Tello(object):
    """
    Minimal Tello interface for sending commands
    """
    def __init__(self):
        # Tello IP and ports
        self.tello_ip = '192.168.10.1'
        self.tello_port = 8889
        self.local_ip = ''
        self.local_port = 9000
        self.tello_address = (self.tello_ip, self.tello_port)
        
        # Socket for sending commands
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.local_ip, self.local_port))
        
        # Response handling
        self.response = None
        self.response_received = False
        
        # Start response receiver thread
        self.receive_thread = threading.Thread(target=self.receive_response)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        
        logger.info("Tello object created. Bound to port %d", self.local_port)
        
    def receive_response(self):
        """Background thread to receive responses from Tello"""
        while True:
            try:
                response, ip = self.socket.recvfrom(3000)
                self.response = response.decode('utf-8')
                self.response_received = True
                logger.info("Received response: %s", self.response)
            except socket.error as exc:
                logger.error("Socket error: %s", exc)
            except Exception as e:
                logger.error("Error receiving response: %s", e)
    
    def send_command(self, command, wait_for_response=True, timeout=10):
        """
        Send command to Tello
        Args:
            command: String command to send
            wait_for_response: Whether to wait for response
            timeout: Response timeout in seconds
        Returns:
            Response string if wait_for_response=True, else None
        """
        logger.info("Sending command: %s", command)
        
        # Reset response flag
        self.response_received = False
        self.response = None
        
        # Send command
        try:
            self.socket.sendto(command.encode('utf-8'), self.tello_address)
        except Exception as e:
            logger.error("Error sending command: %s", e)
            return "error"
        
        # Wait for response if requested
        if wait_for_response:
            start_time = time.time()
            while not self.response_received:
                if time.time() - start_time > timeout:
                    logger.warning("Command timeout: %s", command)
                    return "timeout"
                time.sleep(0.1)
            
            return self.response
        
        return None
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            self.socket.close()
        except:
            pass
