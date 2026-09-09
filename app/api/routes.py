from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, BackgroundTasks
from typing import List
from app.domain.models.detection import DetectionResponse
from app.domain.models.user import User
from app.auth.router import get_current_user
from app.services.providers import (
    get_emotion_detection_service,
    get_detection_history_service,
    get_single_detection_service,
    get_delete_detection_service
)
from fastapi.responses import StreamingResponse
import asyncio
import json
import io
from datetime import datetime

router = APIRouter()

def jsonable_encoder(obj):
    """
    Recursively convert obj to something JSON serializable (handle datetime, pydantic models, etc).
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, 'model_dump'):
        return jsonable_encoder(obj.model_dump())
    if isinstance(obj, dict):
        return {k: jsonable_encoder(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable_encoder(v) for v in obj]
    return obj

@router.post("/detect", response_model=DetectionResponse)
async def detect_emotion(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    detect_emotions=Depends(get_emotion_detection_service)
):
    """
    Detect emotion from image uploaded by user.
    """
    
    try:
        # Split detection (light) and upload/save DB (heavy) into two steps
        detection_result, bg_args = await detect_emotions(file, current_user, background=True)
        # Push task upload/save DB into background
        background_tasks.add_task(bg_args["background_func"], *bg_args["args"], **bg_args["kwargs"])
        return detection_result
    except HTTPException as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/history", response_model=List[DetectionResponse])
async def get_detection_history(
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 10,
    get_detections_by_user=Depends(get_detection_history_service)
):
    """
    Get detection history of user.
    """
    if current_user.is_guest:
        raise HTTPException(status_code=401, detail="Authentication required for batch detection.")
    
    return await get_detections_by_user(current_user.user_id, skip, limit)

@router.get("/history/{detection_id}", response_model=DetectionResponse)
async def get_detection_detail(
    detection_id: str,
    current_user: User = Depends(get_current_user),
    get_detection=Depends(get_single_detection_service)
):
    """
    Get detail of a detection by ID.
    """
    if current_user.is_guest:
        raise HTTPException(status_code=401, detail="Authentication required for batch detection.")
    
    detection = await get_detection(detection_id)
    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Detection with ID {detection_id} not found"
        )
    
    # Check if the detection belongs to the current user
    if detection.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this detection"
        )
        
    return detection

@router.delete("/history/{detection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection_endpoint(
    detection_id: str,
    current_user: User = Depends(get_current_user),
    get_detection=Depends(get_single_detection_service),
    delete_detection=Depends(get_delete_detection_service)
):
    """
    Xóa một detection theo ID.
    """
    if current_user.is_guest:
        raise HTTPException(status_code=401, detail="Authentication required for batch detection.")
    detection = await get_detection(detection_id)
    if not detection:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete detection"
        )
    
    # Check if the detection belongs to the current user
    if detection.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this detection"
        )
    
    success = await delete_detection(detection_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete detection"
        )
    
    return None

@router.get("/detect/status/{detection_id}")
def get_detection_status(detection_id: str):
    """
    Kiểm tra trạng thái xử lý detection (pending/done/failed).
    """
    from app.services.notification import get_notification
    status = get_notification(detection_id)
    return {"detection_id": detection_id, "status": status}

@router.post("/detect/batch")
async def detect_emotion_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    detect_emotions=Depends(get_emotion_detection_service),
):
    """
    Nhận nhiều file ảnh, trả về kết quả từng phần (streaming, SSE-style).
    Chỉ cho phép người dùng đã đăng nhập (không cho guest).
    """
    if current_user.is_guest:
        raise HTTPException(status_code=401, detail="Authentication required for batch detection.")

    file_contents = []
    for file in files:
        content = await file.read()
        file_contents.append({
            "filename": file.filename,
            "content_type": file.content_type,
            "content": content
        })

    async def event_stream():
        for file_data in file_contents:
            try:
                file_like = io.BytesIO(file_data["content"])
                upload_file = UploadFile(
                    file=file_like,
                    filename=file_data["filename"],
                )
                detection_result, bg_args = await detect_emotions(
                    image=upload_file,
                    user=current_user,
                    background=True,
                    is_BytesIO=True
                )
                background_tasks.add_task(bg_args["background_func"], *bg_args["args"], **bg_args["kwargs"])

                yield f"data: {json.dumps(jsonable_encoder(detection_result))}\n\n"
                await asyncio.sleep(0)
            except Exception as e:
                error = {"error": str(e), "filename": file_data["filename"]}
                yield f"data: {json.dumps(error)}\n\n"
                await asyncio.sleep(0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
