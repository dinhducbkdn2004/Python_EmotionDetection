import time
import cv2
import numpy as np
import base64
import torch
from typing import Dict, Optional, Any
from collections import deque
import os

from app.services.face_detection import detect_faces, crop_faces
from app.services.preprocessing import preprocess_face
from app.services.model_loader import EmotionModelCache
from app.domain.models.detection import DetectionResult, EmotionScore, FaceDetection
from app.core.metrics import realtime_fps_gauge

DEFAULT_VIDEO_CONFIG = {
    "detection_interval": 1,
    "min_face_": 64,
    "processing_resolution": (480, 360),
    "detection_confidence": 1.1,
    "min_neighbors": 6,
    "return_bounding_boxes": True,
    "prioritize_realtime": True
}
class VideoEmotionDetector:

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = DEFAULT_VIDEO_CONFIG.copy()
        if config:
            self.config.update(config)
        
        self.frame_count = 0
        self.last_detection_time = 0
        self.processing_times = deque(maxlen=30)
        self.processing_fps = 0
        
        self.face_ids = {}
        self.next_face_id = 0
        
    async def process_frame(self, frame_data: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        
        frame_id = frame_data.get("frame_id")
        timestamp = frame_data.get("timestamp", time.time())
        base64_data = frame_data.get("data")
        
        try:
            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]

            img_bytes = base64.b64decode(base64_data)
            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                raise ValueError("Invalid frame data after decoding")
                
        except Exception as e:
            raise ValueError(f"Failed to decode frame: {str(e)}")
            
        try:
            processing_width, processing_height = self.config["processing_resolution"]
            original_height, original_width = frame.shape[:2]
            
            if processing_width < 320:
                processing_width = 320
            if processing_height < 240:
                processing_height = 240
                
            scale_factor = min(processing_width / original_width, 
                              processing_height / original_height)
            
            if scale_factor < 1.0:
                new_width = int(original_width * scale_factor)
                new_height = int(original_height * scale_factor)
                processing_frame = cv2.resize(frame, (new_width, new_height))
                resize_scale = 1.0 / scale_factor
            else:
                processing_frame = frame
                resize_scale = 1.0
                
        except Exception as e:
            processing_frame = frame
            resize_scale = 1.0
        
        self.frame_count += 1
        
        face_boxes = []
        face_ids = []
        
        try:
            face_boxes = detect_faces(
                processing_frame,
                scale_factor=self.config["detection_confidence"],
                min_neighbors=self.config["min_neighbors"]
            )
            
            original_boxes = []
            for idx, (x, y, w, h) in enumerate(face_boxes):
                orig_x = int(x * resize_scale)
                orig_y = int(y * resize_scale)
                orig_w = int(w * resize_scale)
                orig_h = int(h * resize_scale)
                original_boxes.append((orig_x, orig_y, orig_w, orig_h))
                
            current_faces = []
            for idx, (x, y, w, h) in enumerate(original_boxes):
                center_x = x + w // 2
                center_y = y + h // 2
                current_faces.append((idx, (center_x, center_y)))
            
            prev_faces = list(self.face_ids.items())
            assigned_ids = []
            

            for idx, (center_x, center_y) in current_faces:
                if prev_faces:

                    best_match = None
                    min_distance = float('inf')
                    
                    for face_id, (prev_x, prev_y) in prev_faces:
                        if face_id in assigned_ids:
                            continue
                            
                        dist = ((center_x - prev_x)**2 + (center_y - prev_y)**2)**0.5
                        if dist < min_distance:
                            min_distance = dist
                            best_match = face_id
                    

                    if best_match is not None and min_distance < 100: 
                        face_ids.append(best_match)
                        assigned_ids.append(best_match)
                    else:
                        new_id = f"face_{self.next_face_id}"
                        face_ids.append(new_id)
                        self.next_face_id += 1
                else:
                    new_id = f"face_{self.next_face_id}"
                    face_ids.append(new_id)
                    self.next_face_id += 1
            
            self.face_ids = {}
            for idx, face_id in enumerate(face_ids):
                if idx < len(original_boxes):
                    x, y, w, h = original_boxes[idx]
                    center_x = x + w // 2
                    center_y = y + h // 2
                    self.face_ids[face_id] = (center_x, center_y)
                
        except Exception as e:
            face_boxes = []
            face_ids = []
            original_boxes = []
        
        face_detected = len(face_boxes) > 0
        face_detections = []
        
        if face_detected:
            try:
                image_processor, model = EmotionModelCache.get_model_and_processor()
                
                faces = crop_faces(processing_frame, face_boxes)
                
                preprocessed_faces = [preprocess_face(face) for face in faces]
                
                if preprocessed_faces:
                    inputs = image_processor(images=preprocessed_faces, return_tensors="pt")
                    
                    with torch.no_grad():
                        outputs = model(**inputs)
                        logits = outputs.logits
                        probabilities = torch.nn.functional.softmax(logits, dim=-1)
                    
                    # Lấy labels từ model config
                    if hasattr(model.config, "id2label"):
                        labels = model.config.id2label
                    else:
                        labels = {
                            0: "angry", 1: "disgust", 2: "fear", 
                            3: "happy", 4: "sad", 5: "surprise", 6: "neutral"
                        }
                    
                    for i, (probs, box, face_id) in enumerate(zip(probabilities, original_boxes, face_ids)):
                        emotion_scores = []
                        for idx, prob in enumerate(probs.tolist()):
                            if idx in labels:
                                label = labels[idx]
                                emotion_scores.append(EmotionScore(
                                    emotion=label,
                                    score=prob,
                                    percentage=prob * 100
                                ))
                        
                        emotion_scores.sort(key=lambda x: x.score, reverse=True)
                        
                        face_detections.append(FaceDetection(
                            box=box if self.config["return_bounding_boxes"] else None,
                            emotions=emotion_scores,
                            face_id=face_id
                        ))
            except Exception as e:
                face_detected = len(face_detections) > 0
        
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        
        if len(self.processing_times) > 0:
            avg_processing_time = sum(self.processing_times) / len(self.processing_times)
            self.processing_fps = 1.0 / avg_processing_time if avg_processing_time > 0 else 0
            realtime_fps_gauge.set(self.processing_fps)
        
        if face_detected:
            self.last_detection_time = time.time()
        
        latency = time.time() - timestamp if timestamp else processing_time
        
        result = {
            "frame_id": frame_id,
            "timestamp": time.time(),
            "processing_time": processing_time,
            "latency": latency,
            "fps": self.processing_fps,
            "faces": [face.dict() for face in face_detections],
            "face_detected": len(face_detections) > 0,
            "detection_used": True
        }
        
        return result
    
    def update_config(self, new_config: Dict[str, Any]) -> None:
        self.config.update(new_config)
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        return {
            "processed_frames": self.frame_count,
            "current_fps": self.processing_fps,
            "average_processing_time": sum(self.processing_times) / len(self.processing_times) 
                                      if self.processing_times else 0,
            "last_detection_time": self.last_detection_time,
            "tracking_faces": len(self.face_ids)
        } 