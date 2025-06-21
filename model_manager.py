# model_manager.py
# Manages loading and inference for both 4-class and 8-class models

import os
import numpy as np
import xgboost as xgb
import pickle
import logging
from threading import Lock
import time
from config import MODELS, EEG_CONFIG

logger = logging.getLogger(__name__)

class ModelManager:
    """Manages multiple XGBoost models for BCI prediction"""
    
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.model_configs = MODELS
        self.inference_lock = Lock()
        self.last_predictions = {}
        self.inference_times = {}
        
    def load_models(self):
        """Load all configured models and their scalers"""
        success_count = 0
        
        for model_name, config in self.model_configs.items():
            try:
                logger.info(f"Loading {model_name} model...")
                
                # Load XGBoost model
                if not os.path.exists(config["model_path"]):
                    logger.error(f"Model file not found: {config['model_path']}")
                    continue
                    
                model = xgb.Booster()
                model.load_model(config["model_path"])
                self.models[model_name] = model
                
                # Load scaler
                if not os.path.exists(config["scaler_path"]):
                    logger.error(f"Scaler file not found: {config['scaler_path']}")
                    continue
                    
                with open(config["scaler_path"], 'rb') as f:
                    scaler = pickle.load(f)
                self.scalers[model_name] = scaler
                
                logger.info(f"Successfully loaded {model_name} model and scaler")
                success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to load {model_name}: {str(e)}")
                
        logger.info(f"Loaded {success_count}/{len(self.model_configs)} models")
        return success_count > 0
    
    def prepare_features(self, cov_matrix, model_name):
        """Prepare features based on model requirements"""
        config = self.model_configs[model_name]
        
        if config["features"] == "covariance":
            # Use covariance matrix features (current approach)
            features = cov_matrix.flatten().reshape(1, -1)
        elif config["features"] == "raw":
            # For models that might use raw features
            # This is a placeholder - adjust based on actual 8-class model needs
            features = cov_matrix.flatten().reshape(1, -1)
        else:
            raise ValueError(f"Unknown feature type: {config['features']}")
            
        # Validate feature dimensions
        expected_features = EEG_CONFIG["channels"] * EEG_CONFIG["channels"]
        if features.shape[1] != expected_features:
            logger.warning(f"Feature dimension mismatch for {model_name}: "
                         f"got {features.shape[1]}, expected {expected_features}")
            # Pad or truncate if necessary
            if features.shape[1] < expected_features:
                features = np.pad(features, ((0, 0), (0, expected_features - features.shape[1])))
            else:
                features = features[:, :expected_features]
                
        return features
    
    def predict_single(self, model_name, cov_matrix):
        """Run prediction for a single model"""
        if model_name not in self.models:
            logger.error(f"Model {model_name} not loaded")
            return None
            
        try:
            start_time = time.time()
            
            # Prepare features
            features = self.prepare_features(cov_matrix, model_name)
            
            # Scale features
            if model_name in self.scalers:
                features_scaled = self.scalers[model_name].transform(features)
            else:
                features_scaled = features
                logger.warning(f"No scaler found for {model_name}, using raw features")
            
            # Make prediction
            dmatrix = xgb.DMatrix(features_scaled)
            probabilities = self.models[model_name].predict(dmatrix)
            
            # Handle different output shapes
            if probabilities.ndim == 1:
                probs = probabilities
            elif probabilities.ndim == 2:
                probs = probabilities[0]
            else:
                logger.error(f"Unexpected probability shape: {probabilities.shape}")
                return None
            
            # Get prediction details
            config = self.model_configs[model_name]
            predicted_idx = int(np.argmax(probs))
            predicted_class = config["class_names"][predicted_idx]
            confidence = float(probs[predicted_idx])
            
            # Create prediction result
            result = {
                "model": model_name,
                "predicted_class": predicted_class,
                "predicted_idx": predicted_idx,
                "confidence": confidence,
                "probabilities": {
                    config["class_names"][i]: float(probs[i])
                    for i in range(len(config["class_names"]))
                },
                "inference_time": time.time() - start_time
            }
            
            # Store for debugging
            self.inference_times[model_name] = result["inference_time"]
            
            return result
            
        except Exception as e:
            logger.error(f"Prediction error for {model_name}: {str(e)}")
            return None
    
    def predict_dual(self, cov_matrix):
        """Run predictions on both models and return combined results"""
        with self.inference_lock:
            results = {}
            
            # Run predictions for each loaded model
            for model_name in self.models.keys():
                prediction = self.predict_single(model_name, cov_matrix)
                if prediction:
                    results[model_name] = prediction
                    self.last_predictions[model_name] = prediction
            
            # Add metadata
            results["timestamp"] = int(time.time() * 1000)
            results["total_inference_time"] = sum(self.inference_times.values())
            
            return results
    
    def get_model_info(self):
        """Get information about loaded models"""
        info = {}
        for model_name, config in self.model_configs.items():
            info[model_name] = {
                "loaded": model_name in self.models,
                "num_classes": config["num_classes"],
                "class_names": config["class_names"],
                "feature_type": config["features"],
                "last_inference_time": self.inference_times.get(model_name, 0)
            }
        return info
    
    def validate_models(self):
        """Validate that models are working correctly"""
        logger.info("Validating models with dummy data...")
        
        # Create dummy covariance matrix
        dummy_cov = np.random.randn(EEG_CONFIG["channels"], EEG_CONFIG["channels"])
        dummy_cov = (dummy_cov + dummy_cov.T) / 2  # Make symmetric
        
        results = self.predict_dual(dummy_cov)
        
        for model_name, result in results.items():
            if model_name in ["timestamp", "total_inference_time"]:
                continue
                
            logger.info(f"{model_name} validation:")
            logger.info(f"  Predicted: {result['predicted_class']} "
                       f"(confidence: {result['confidence']:.3f})")
            logger.info(f"  Inference time: {result['inference_time']*1000:.1f}ms")
            
            # Check if probabilities sum to ~1
            prob_sum = sum(result['probabilities'].values())
            if abs(prob_sum - 1.0) > 0.01:
                logger.warning(f"  Probabilities sum to {prob_sum}, not 1.0")
        
        return len(results) > 2  # At least one model + metadata
