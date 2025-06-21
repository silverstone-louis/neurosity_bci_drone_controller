#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tello_video.py - Tello video stream handling module
Simplified video handling extracted from Tello examples
For Python 2.7
"""

import socket
import threading
import time
import numpy as np
import cv2
import logging

logger = logging.getLogger(__name__)

try:
    import libh264decoder
    H264_AVAILABLE = True
except ImportError:
    logger.warning("libh264decoder not found - video decoding disabled")
    H264_AVAILABLE = False

class TelloVideo(object):
    """Handles Tello video stream reception and decoding"""
    
    def __init__(self, local_ip='', local_video_port=11111, tello_ip='192.168.10.1', tello_port=8889):
        """
        Initialize video handler
        
        Args:
            local_ip: Local IP to bind for video reception
            local_video_port: Local port for video stream (default 11111)
            tello_ip: Tello IP address
            tello_port: Tello command port
        """
        self.local_ip = local_ip
        self.local_video_port = local_video_port
        self.tello_ip = tello_ip
        self.tello_port = tello_port
        self.tello_address = (tello_ip, tello_port)
        
        # Video state
        self.frame = None
        self.last_frame = None
        self.is_running = False
        self.stream_on = False
        
        # H264 decoder
        self.decoder = None
        if H264_AVAILABLE:
            try:
                self.decoder = libh264decoder.H264Decoder()
                logger.info("H264 decoder initialized")
            except Exception as e:
                logger.error("Failed to initialize H264 decoder: %s", e)
                self.decoder = None
        
        # Sockets
        self.socket_video = None
        self.command_socket = None
        
        # Thread
        self.receive_thread = None
        
        # Stats
        self.frame_count = 0
        self.last_frame_time = 0
        self.fps = 0
        
    def start_video(self, command_socket=None):
        """
        Start video stream
        
        Args:
            command_socket: Optional command socket to send streamon command
        """
        if self.is_running:
            logger.warning("Video already running")
            return False
            
        try:
            # Create video socket
            self.socket_video = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket_video.bind((self.local_ip, self.local_video_port))
            self.socket_video.settimeout(2.0)
            logger.info("Video socket bound to port %d", self.local_video_port)
            
            # Send streamon command if we have a command socket
            if command_socket:
                self.command_socket = command_socket
                try:
                    command_socket.sendto(b'streamon', self.tello_address)
                    logger.info("Sent 'streamon' command")
                    self.stream_on = True
                except Exception as e:
                    logger.error("Failed to send streamon: %s", e)
            
            # Start receiver thread
            self.is_running = True
            self.receive_thread = threading.Thread(target=self._receive_video_thread)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            logger.info("Video reception started")
            return True
            
        except Exception as e:
            logger.error("Failed to start video: %s", e)
            self.cleanup()
            return False
    
    def stop_video(self):
        """Stop video stream"""
        logger.info("Stopping video...")
        
        # Send streamoff if we have command socket
        if self.command_socket and self.stream_on:
            try:
                self.command_socket.sendto(b'streamoff', self.tello_address)
                logger.info("Sent 'streamoff' command")
            except:
                pass
        
        self.is_running = False
        self.stream_on = False
        
        # Wait for thread to stop
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)
        
        self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        if self.socket_video:
            try:
                self.socket_video.close()
            except:
                pass
            self.socket_video = None
    
    def _receive_video_thread(self):
        """
        Thread that receives and decodes video packets
        """
        packet_data = ""
        
        while self.is_running:
            try:
                # Receive video data
                data, addr = self.socket_video.recvfrom(2048)
                packet_data += data
                
                # Check if end of frame (packet size != 1460)
                if len(data) != 1460:
                    # Decode the frame
                    for frame in self._h264_decode(packet_data):
                        if frame is not None:
                            self.frame = frame
                            self.last_frame = frame
                            self._update_stats()
                    packet_data = ""
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    logger.error("Video receive error: %s", e)
                time.sleep(0.1)
    
    def _h264_decode(self, packet_data):
        """
        Decode H264 packet data
        
        Args:
            packet_data: Raw H264 data
            
        Returns:
            List of decoded frames (numpy arrays)
        """
        frames = []
        
        if not self.decoder or not H264_AVAILABLE:
            return frames
            
        try:
            # Decode the data
            decoded_frames = self.decoder.decode(packet_data)
            
            for framedata in decoded_frames:
                (frame, w, h, ls) = framedata
                if frame is not None:
                    # Convert to numpy array
                    frame = np.fromstring(frame, dtype=np.ubyte, count=len(frame), sep='')
                    frame = frame.reshape((h, ls / 3, 3))
                    frame = frame[:, :w, :]
                    frames.append(frame)
                    
        except Exception as e:
            logger.error("H264 decode error: %s", e)
            
        return frames
    
    def _update_stats(self):
        """Update video statistics"""
        self.frame_count += 1
        
        # Calculate FPS
        current_time = time.time()
        if self.last_frame_time > 0:
            time_diff = current_time - self.last_frame_time
            if time_diff > 0:
                self.fps = 1.0 / time_diff
        self.last_frame_time = current_time
    
    def get_frame(self):
        """
        Get the latest video frame
        
        Returns:
            numpy array: Latest frame or None
        """
        return self.frame
    
    def get_frame_with_stats(self):
        """
        Get frame with statistics
        
        Returns:
            dict: Frame data and stats
        """
        return {
            'frame': self.frame,
            'frame_count': self.frame_count,
            'fps': self.fps,
            'timestamp': time.time()
        }
    
    def wait_for_frame(self, timeout=5.0):
        """
        Wait for first frame to arrive
        
        Args:
            timeout: Maximum wait time
            
        Returns:
            bool: True if frame received
        """
        start_time = time.time()
        
        while self.frame is None and (time.time() - start_time) < timeout:
            time.sleep(0.1)
            
        return self.frame is not None
    
    def apply_filter(self, frame):
        """
        Apply smoothing filter to frame (optional enhancement)
        
        Args:
            frame: Input frame
            
        Returns:
            Filtered frame
        """
        if frame is None:
            return None
            
        try:
            # Bilateral filter for smoothing while preserving edges
            return cv2.bilateralFilter(frame, 5, 50, 100)
        except:
            return frame
    
    def convert_to_jpeg(self, frame=None, quality=80):
        """
        Convert frame to JPEG bytes
        
        Args:
            frame: Frame to convert (uses latest if None)
            quality: JPEG quality (1-100)
            
        Returns:
            JPEG bytes or None
        """
        if frame is None:
            frame = self.frame
            
        if frame is None:
            return None
            
        try:
            # Convert to BGR for OpenCV
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            
            # Encode as JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            result, encoded = cv2.imencode('.jpg', frame_bgr, encode_param)
            
            if result:
                return encoded.tobytes()
            else:
                return None
                
        except Exception as e:
            logger.error("JPEG conversion error: %s", e)
            return None
    
    def save_frame(self, filename, frame=None):
        """
        Save frame to file
        
        Args:
            filename: Output filename
            frame: Frame to save (uses latest if None)
        """
        if frame is None:
            frame = self.frame
            
        if frame is None:
            logger.warning("No frame to save")
            return False
            
        try:
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            cv2.imwrite(filename, frame_bgr)
            logger.info("Saved frame to %s", filename)
            return True
        except Exception as e:
            logger.error("Failed to save frame: %s", e)
            return False
