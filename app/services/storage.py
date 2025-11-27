from typing import List, Optional
from datetime import datetime
from app.domain.models.detection import DetectionResponse
from app.infrastructure.database.repository import DetectionRepository
from app.services.database import get_collection
import json
from bson import ObjectId

class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return json.JSONEncoder.default(self, o)

def detection_to_dict(detection: DetectionResponse) -> dict:
    """Convert DetectionResponse to dictionary for MongoDB"""
    detection_dict = detection.model_dump()
    detection_dict["detection_results"] = detection.detection_results.model_dump()
    if "faces" in detection_dict["detection_results"]:
        faces = []
        for face in detection_dict["detection_results"]["faces"]:
            if hasattr(face, "box") and hasattr(face, "emotions"):
                faces.append({
                    "box": face.box,
                    "emotions": [emotion.model_dump() if hasattr(emotion, "model_dump") else emotion for emotion in face.emotions]
                })
            elif isinstance(face, dict):
                faces.append(face)
        detection_dict["detection_results"]["faces"] = faces
    detection_dict["detection_results"].pop("emotions", None)
    return detection_dict

def dict_to_detection(detection_dict: dict) -> DetectionResponse:
    """Convert dictionary from MongoDB to DetectionResponse"""
    if "_id" in detection_dict and "detection_id" not in detection_dict:
        detection_dict["detection_id"] = str(detection_dict.pop("_id"))
    if "timestamp" in detection_dict and isinstance(detection_dict["timestamp"], str):
        detection_dict["timestamp"] = datetime.fromisoformat(detection_dict["timestamp"])
    dr = detection_dict["detection_results"]
    if "faces" in dr:
        from app.domain.models.detection import FaceDetection, EmotionScore
        dr["faces"] = [
            FaceDetection(
                box=face["box"],
                emotions=[EmotionScore(**emo) for emo in face["emotions"]]
            ) for face in dr["faces"]
        ]
    dr.pop("emotions", None)
    detection_dict["detection_results"] = dr
    return DetectionResponse(**detection_dict)

async def save_detection(detection: DetectionResponse) -> str:
    """
    Save a detection to storage.
    """
    try:
        repo = DetectionRepository(get_collection("detections"))
        detection_dict = detection_to_dict(detection)
        detection_dict["_id"] = detection_dict.pop("detection_id")
        await repo.create(detection_dict)
    except Exception as e:
        print(f"Error saving detection to MongoDB: {e}")
    return detection.detection_id

async def get_detection(detection_id: str) -> Optional[DetectionResponse]:
    """
    Get a detection by ID using DetectionRepository.
    """
    try:
        repo = DetectionRepository(get_collection("detections"))
        detection_dict = await repo.get_by_id(detection_id)
        if detection_dict:
            return dict_to_detection(detection_dict)
    except Exception as e:
        print(f"Error retrieving detection from MongoDB: {e}")
    return None

async def get_detections_by_user(user_id: str, skip: int = 0, limit: int = 10) -> List[DetectionResponse]:
    """
    Get detections for a specific user using DetectionRepository.
    """
    detections = []
    try:
        collection = get_collection("detections")
        cursor = collection.find({"user_id": user_id})
        cursor = cursor.sort("timestamp", -1).skip(skip).limit(limit)
        async for doc in cursor:
            detections.append(dict_to_detection(doc))
    except Exception as e:
        print(f"Error retrieving detections from MongoDB: {e}")
    return detections

async def delete_detection(detection_id: str) -> bool:
    """
    Delete a detection by ID using DetectionRepository.
    """
    try:
        repo = DetectionRepository(get_collection("detections"))
        return await repo.delete(detection_id)
    except Exception as e:
        print(f"Error deleting detection from MongoDB: {e}")
    return False