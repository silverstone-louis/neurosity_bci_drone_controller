# command_mapper.py
# Maps model predictions to drone commands with conflict resolution

import logging
import time
from config import (
    COMMAND_MAPPINGS, CONFIDENCE_THRESHOLDS, 
    COMMAND_PRIORITY, COMMAND_RESTRICTIONS, COMMAND_COOLDOWNS
)

logger = logging.getLogger(__name__)

class CommandMapper:
    """Maps BCI predictions to drone commands with safety and priority handling"""
    
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
        # Continuous control bypasses cooldowns
        if command == "continuous_control":
            return self.drone_state == "flying"
        
        # Check cooldown
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
    
    def map_predictions_to_commands(self, dual_predictions, current_time):
        """Map dual model predictions to drone commands"""
        candidates = []
        
        # Process each model's predictions
        for model_name, prediction in dual_predictions.items():
            if model_name in ["timestamp", "total_inference_time"]:
                continue
                
            predicted_class = prediction["predicted_class"]
            confidence = prediction["confidence"]
            
            # Skip Rest predictions
            if predicted_class == "Rest":
                continue
                
            # Check confidence threshold for this specific class
            threshold = CONFIDENCE_THRESHOLDS.get(predicted_class, 0.7)
            if confidence < threshold:
                logger.debug(f"{predicted_class} confidence {confidence:.3f} "
                           f"below threshold {threshold}")
                continue
            
            # Check if this class has a mapping
            if predicted_class not in COMMAND_MAPPINGS:
                logger.warning(f"No command mapping for class {predicted_class}")
                continue
                
            mapping = COMMAND_MAPPINGS[predicted_class]
            
            # Check if this command is enabled
            if not mapping.get("enabled", False):
                logger.debug(f"Command for {predicted_class} is disabled")
                continue
            
            # Get the drone command
            drone_command = mapping["drone_command"]
            
            # Special handling for toggle_flight
            if drone_command == "toggle_flight":
                if self.drone_state == "grounded":
                    drone_command = "takeoff"
                elif self.drone_state == "flying":
                    drone_command = "land"
                else:
                    logger.debug(f"Cannot toggle flight in state {self.drone_state}")
                    continue
            
            # Check if command is allowed
            if not self.is_command_allowed(drone_command, current_time):
                continue
            
            # Add to candidates with priority
            priority = COMMAND_PRIORITY.get(drone_command, 50)
            candidates.append({
                "command": drone_command,
                "source_model": model_name,
                "source_class": predicted_class,
                "confidence": confidence,
                "priority": priority,
                "description": mapping["description"]
            })
        
        # Select best command based on priority and confidence
        if not candidates:
            return None
            
        # Sort by priority (descending) then confidence (descending)
        candidates.sort(key=lambda x: (x["priority"], x["confidence"]), reverse=True)
        selected = candidates[0]
        
        # Log decision
        logger.info(f"Selected command: {selected['command']} "
                   f"from {selected['source_model']}/{selected['source_class']} "
                   f"(conf: {selected['confidence']:.3f}, pri: {selected['priority']})")
        
        if len(candidates) > 1:
            logger.debug(f"Other candidates: {[c['command'] for c in candidates[1:]]}")
        
        # Update state and apply cooldown
        self.last_command = selected["command"]
        self.last_command_time = current_time
        self.apply_cooldown(selected["command"], current_time)
        
        # Update drone state based on command
        if selected["command"] == "takeoff":
            self.update_drone_state("taking_off")
        elif selected["command"] == "land":
            self.update_drone_state("landing")
        
        # Add to history
        self.command_history.append({
            "command": selected,
            "timestamp": current_time
        })
        
        return selected
    
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
    
    def get_active_mappings(self):
        """Get list of currently active command mappings"""
        active = []
        for class_name, mapping in COMMAND_MAPPINGS.items():
            if mapping.get("enabled", False):
                active.append({
                    "class": class_name,
                    "command": mapping["drone_command"],
                    "description": mapping["description"],
                    "threshold": CONFIDENCE_THRESHOLDS.get(class_name, 0.7)
                })
        return active
    
    def get_state_info(self):
        """Get current mapper state information"""
        current_time = time.time()
        return {
            "drone_state": self.drone_state,
            "last_command": self.last_command,
            "cooldown_active": current_time < self.cooldown_until,
            "cooldown_remaining": max(0, self.cooldown_until - current_time),
            "active_mappings": len([m for m in COMMAND_MAPPINGS.values() 
                                   if m.get("enabled", False)]),
            "command_count": len(self.command_history)
        }