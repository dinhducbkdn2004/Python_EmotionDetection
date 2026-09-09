# app/services/providers.py
"""
Service provider module for dependency injection.
"""
from app.services.emotion_detection import detect_emotions
from app.services.storage import (
    get_detections_by_user,
    get_detection,
    delete_detection
)

def get_emotion_detection_service():
    return detect_emotions

def get_detection_history_service():
    return get_detections_by_user

def get_single_detection_service():
    return get_detection

def get_delete_detection_service():
    return delete_detection
