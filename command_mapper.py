# command_mapper.py
# Simplified command mapper for drone state management

import logging
import time
from config import (
    COMMAND_MAPPINGS, CONFIDENCE_THRESHOLDS, 
    COMMAND_PRIORITY, COMMAND_RESTRICTIONS, COMMAND_COOLDOWNS
)

logger = logging.getLogger(__name__)

class CommandMapper:
    """Manages drone state and command restrictions"""
    
    def __init__(self):
        self.drone_state = "grounded"  # grounded, taking_off, flying, landing
        self.last_command_time = 0
        self.last_command = None
        self.cooldown_until = 0
        self.command_history = []
        
    def update_drone_state(self, new_state):
        """Update the drone's current state"""
        old_state = self.drone_state
        self.drone_state = new_state
        logger.info(f"Drone state changed: {old_state} → {new_state}")
        
    def is_command_allowed(self, command, current_time):
        """Check if a command is allowed based on current state and cooldowns"""
        # RC commands are always allowed when flying
        if command == "rc":
            return self.drone_state == "flying"
        
        # Check cooldown for other commands
        if current_time < self.cooldown_until:
            logger.debug(f"Command {command} blocked by cooldown "
                        f"({self.cooldown_until - current_time:.1f}s remaining)")
            return False
        
        # Check state restrictions
        if self.drone_state in COMMAND_RESTRICTIONS:
            restricted_commands = COMMAND_RESTRICTIONS[self.drone_state]
            if command in restricted_commands:
                logger.debug(f"Command {command} restricted in state {self.drone_state}")
                return False
                
        return True
    
    def apply_cooldown(self, command, current_time):
        """Apply cooldown period after a command"""
        cooldown = COMMAND_COOLDOWNS.get(command, COMMAND_COOLDOWNS["default"])
        self.cooldown_until = current_time + cooldown
        logger.debug(f"Applied {cooldown}s cooldown for command {command}")
    
    def handle_command_completion(self, command, success):
        """Handle notification that a command has completed"""
        if command == "takeoff" and success:
            self.update_drone_state("flying")
        elif command == "land" and success:
            self.update_drone_state("grounded")
        elif command in ["takeoff", "land"] and not success:
            # Failed takeoff/land, revert to previous state
            if self.drone_state == "taking_off":
                self.update_drone_state("grounded")
            elif self.drone_state == "landing":
                self.update_drone_state("flying")
    
    def get_state_info(self):
        """Get current mapper state information"""
        current_time = time.time()
        return {
            "drone_state": self.drone_state,
            "last_command": self.last_command,
            "cooldown_active": current_time < self.cooldown_until,
            "cooldown_remaining": max(0, self.cooldown_until - current_time),
            "command_count": len(self.command_history)
        }
