# prediction_buffer.py
# Manages temporal aspects of predictions with per-class sustained detection

import time
import numpy as np
from collections import deque, defaultdict
import logging
from config import SUSTAINED_DURATIONS, CONFIDENCE_THRESHOLDS, BUFFER_CONFIG

logger = logging.getLogger(__name__)

class PredictionBuffer:
    """Manages prediction history and sustained command detection"""
    
    def __init__(self):
        self.history_size = BUFFER_CONFIG["history_size"]
        self.smoothing_window = BUFFER_CONFIG["smoothing_window"]
        self.jitter_threshold = BUFFER_CONFIG["jitter_threshold"]
        self.min_consistent = BUFFER_CONFIG["min_consistent_predictions"]
        
        # Separate buffers for each model
        self.prediction_buffers = {
            "4_class": deque(maxlen=self.history_size),
            "8_class": deque(maxlen=self.history_size)
        }
        
        # Sustained command tracking per class
        self.sustained_trackers = defaultdict(lambda: {
            "start_time": None,
            "last_seen": None,
            "triggered": False,
            "confidence_sum": 0,
            "count": 0
        })
        
        # Smoothed predictions
        self.smoothed_predictions = {}
        
        # Jitter detection
        self.jitter_counts = defaultdict(int)
        
    def add_predictions(self, dual_predictions):
        """Add new predictions to buffers"""
        timestamp = time.time()
        
        # Store predictions by model
        for model_name, prediction in dual_predictions.items():
            if model_name in self.prediction_buffers:
                self.prediction_buffers[model_name].append({
                    "prediction": prediction,
                    "timestamp": timestamp
                })
        
        # Update smoothed predictions
        self._update_smoothed_predictions()
        
        # Check for sustained commands
        sustained_commands = self._check_sustained_commands(timestamp)
        
        return sustained_commands
    
    def _update_smoothed_predictions(self):
        """Calculate smoothed predictions using rolling average"""
        self.smoothed_predictions = {}
        
        for model_name, buffer in self.prediction_buffers.items():
            if len(buffer) < self.smoothing_window:
                continue
                
            # Get recent predictions
            recent = list(buffer)[-self.smoothing_window:]
            
            # Calculate average probabilities for each class
            class_probs = defaultdict(list)
            for entry in recent:
                pred = entry["prediction"]
                for class_name, prob in pred["probabilities"].items():
                    class_probs[class_name].append(prob)
            
            # Calculate smoothed probabilities
            smoothed = {}
            for class_name, probs in class_probs.items():
                smoothed[class_name] = np.mean(probs)
            
            # Find the class with highest smoothed probability
            if smoothed:
                best_class = max(smoothed, key=smoothed.get)
                self.smoothed_predictions[model_name] = {
                    "predicted_class": best_class,
                    "confidence": smoothed[best_class],
                    "probabilities": smoothed
                }
    
    def _check_sustained_commands(self, current_time):
        """Check for sustained commands with per-class thresholds and durations"""
        sustained_commands = []
        
        # Get latest predictions from both models
        latest_predictions = {}
        for model_name, buffer in self.prediction_buffers.items():
            if buffer:
                latest_predictions[model_name] = buffer[-1]["prediction"]
        
        # Track all predicted classes
        active_classes = set()
        
        for model_name, prediction in latest_predictions.items():
            predicted_class = prediction["predicted_class"]
            confidence = prediction["confidence"]
            
            # Skip Rest
            if predicted_class == "Rest":
                continue
                
            active_classes.add(predicted_class)
            
            # Check confidence threshold for this specific class
            threshold = CONFIDENCE_THRESHOLDS.get(predicted_class, 0.7)
            if confidence < threshold:
                continue
            
            # Get sustained duration for this class
            required_duration = SUSTAINED_DURATIONS.get(predicted_class, 2.0)
            
            # Update tracker for this class
            tracker = self.sustained_trackers[predicted_class]
            
            if tracker["start_time"] is None:
                # Start tracking
                tracker["start_time"] = current_time
                tracker["last_seen"] = current_time
                tracker["triggered"] = False
                tracker["confidence_sum"] = confidence
                tracker["count"] = 1
                logger.info(f"Started tracking sustained {predicted_class}")
            else:
                # Continue tracking
                time_since_last = current_time - tracker["last_seen"]
                
                # Reset if too much time has passed
                if time_since_last > 0.5:  # 500ms gap resets
                    self._reset_tracker(predicted_class)
                    tracker["start_time"] = current_time
                    tracker["confidence_sum"] = confidence
                    tracker["count"] = 1
                else:
                    tracker["last_seen"] = current_time
                    tracker["confidence_sum"] += confidence
                    tracker["count"] += 1
                    
                    # Check if sustained long enough
                    duration = current_time - tracker["start_time"]
                    avg_confidence = tracker["confidence_sum"] / tracker["count"]
                    
                    if duration >= required_duration and not tracker["triggered"]:
                        # Check if we have enough consistent predictions
                        if tracker["count"] >= self.min_consistent:
                            logger.info(f"SUSTAINED COMMAND TRIGGERED: {predicted_class} "
                                      f"(held for {duration:.1f}s, avg conf: {avg_confidence:.3f})")
                            
                            sustained_commands.append({
                                "class": predicted_class,
                                "model": model_name,
                                "duration": duration,
                                "average_confidence": avg_confidence,
                                "count": tracker["count"]
                            })
                            
                            tracker["triggered"] = True
        
        # Reset trackers for classes that are no longer active
        for class_name in list(self.sustained_trackers.keys()):
            if class_name not in active_classes:
                self._reset_tracker(class_name)
        
        return sustained_commands
    
    def _reset_tracker(self, class_name):
        """Reset sustained tracker for a class"""
        if class_name in self.sustained_trackers:
            logger.debug(f"Reset sustained tracker for {class_name}")
            self.sustained_trackers[class_name] = {
                "start_time": None,
                "last_seen": None,
                "triggered": False,
                "confidence_sum": 0,
                "count": 0
            }
    
    def reset_sustained_command(self, class_name):
        """Manually reset a sustained command (e.g., after it's been executed)"""
        self._reset_tracker(class_name)
    
    def detect_jitter(self, model_name):
        """Detect if predictions are jittering between classes"""
        if model_name not in self.prediction_buffers:
            return False
            
        buffer = self.prediction_buffers[model_name]
        if len(buffer) < 5:
            return False
            
        # Check last 5 predictions
        recent = list(buffer)[-5:]
        classes = [entry["prediction"]["predicted_class"] for entry in recent]
        
        # Count class changes
        changes = sum(1 for i in range(1, len(classes)) if classes[i] != classes[i-1])
        
        # High jitter if more than 3 changes in 5 predictions
        is_jittering = changes > 3
        
        if is_jittering:
            self.jitter_counts[model_name] += 1
            logger.warning(f"Jitter detected in {model_name} "
                         f"(count: {self.jitter_counts[model_name]})")
        else:
            self.jitter_counts[model_name] = 0
            
        return is_jittering
    
    def get_sustained_info(self):
        """Get information about current sustained commands"""
        info = {}
        current_time = time.time()
        
        for class_name, tracker in self.sustained_trackers.items():
            if tracker["start_time"] is not None:
                duration = current_time - tracker["start_time"]
                required = SUSTAINED_DURATIONS.get(class_name, 2.0)
                progress = min(duration / required, 1.0)
                
                info[class_name] = {
                    "duration": duration,
                    "required": required,
                    "progress": progress,
                    "triggered": tracker["triggered"],
                    "average_confidence": (tracker["confidence_sum"] / tracker["count"] 
                                         if tracker["count"] > 0 else 0)
                }
                
        return info
    
    def get_buffer_stats(self):
        """Get statistics about prediction buffers"""
        stats = {}
        
        for model_name, buffer in self.prediction_buffers.items():
            if not buffer:
                stats[model_name] = {"size": 0}
                continue
                
            # Get class distribution
            class_counts = defaultdict(int)
            confidence_values = []
            
            for entry in buffer:
                pred = entry["prediction"]
                class_counts[pred["predicted_class"]] += 1
                confidence_values.append(pred["confidence"])
            
            stats[model_name] = {
                "size": len(buffer),
                "class_distribution": dict(class_counts),
                "avg_confidence": np.mean(confidence_values) if confidence_values else 0,
                "jitter_count": self.jitter_counts.get(model_name, 0),
                "has_smoothed": model_name in self.smoothed_predictions
            }
            
        return stats
