import numpy as np
from PIL import Image
from typing import Tuple

def preprocess_face(face_img, size: Tuple[int, int] = (224, 224)):
    """
    Resize and normalize a face image for model input.
    """
    from app.services.face_detection import cv2_to_pil
    if isinstance(face_img, np.ndarray):
        pil_img = cv2_to_pil(face_img) if face_img.shape[-1] == 3 else Image.fromarray(face_img)
    else:
        pil_img = face_img
    face_resized = pil_img.resize(size, resample=Image.Resampling.BILINEAR)
    arr = np.array(face_resized).astype(np.float32) / 255.0
    if isinstance(face_img, np.ndarray):
        return arr
    else:
        face_normalized = Image.fromarray((arr * 255).astype(np.uint8))
        return face_normalized
