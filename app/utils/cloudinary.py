import cloudinary
import cloudinary.uploader
from app.core.config import settings
import uuid
from PIL import Image
import io

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET
)

def preprocess_image_for_upload(image_data: bytes, max_size: int = 800) -> bytes:
    """
    Resize and compress image before uploading to Cloudinary.
    """
    try:
        img = Image.open(io.BytesIO(image_data)).convert("RGB")
        w, h = img.size
        scale = min(max_size / max(w, h), 1.0)
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception as e:
        print(f"Error preprocessing image for Cloudinary: {e}")
        return image_data

async def upload_image_to_cloudinary(image_data: bytes) -> str:
    """
    Upload an image to Cloudinary and return the URL.
    """
    processed_data = preprocess_image_for_upload(image_data)
    public_id = f"emotion_detection/{uuid.uuid4()}"
    try:
        upload_result = cloudinary.uploader.upload(
            processed_data,
            public_id=public_id,
            folder="emotion_detection",
            resource_type="image"
        )
        return upload_result.get('secure_url') or ""
    except Exception as e:
        print(f"Error uploading to Cloudinary: {e}")
        return ""
