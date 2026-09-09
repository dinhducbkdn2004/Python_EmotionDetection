"""
Socket.IO handler for realtime emotion detection.
"""
import socketio
import time
import numpy as np
from typing import Dict, Any,List
import logging

from app.core.config import settings
from app.auth.auth_utils import verify_token
from app.services.video_emotion_detection import VideoEmotionDetector
from app.core.metrics import realtime_connections_gauge

logger = logging.getLogger(__name__)

# Khởi tạo Socket.IO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=settings.DEBUG,
    engineio_logger=False,
)

class SocketManager:
    """Manager for Socket.IO connections and event handling."""
    
    def __init__(self):
        self.app = socketio.ASGIApp(
            socketio_server=sio,
            socketio_path='socket.io'
        )
        
        self.namespace = '/emotion-detection'
        
        self.detectors: Dict[str, VideoEmotionDetector] = {}
        
        self.connection_count = 0
        
        self.MAX_CONCURRENT_CONNECTIONS = 20
        
        self.processing_frames: Dict[str, bool] = {}
        
        self.latest_frames: Dict[str, Dict[str, Any]] = {}
        
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all Socket.IO event handlers."""
        @sio.event(namespace=self.namespace)
        async def connect(sid, environ, auth):
            """Handle new connection with authentication."""
            if self.connection_count >= self.MAX_CONCURRENT_CONNECTIONS:
                logger.warning(f"Connection limit reached ({self.connection_count}/{self.MAX_CONCURRENT_CONNECTIONS})")
                raise ConnectionRefusedError('Server is at capacity, please try again later')
                
            if not auth or 'token' not in auth:
                logger.warning(f"Authentication required for {sid}")
                raise ConnectionRefusedError('Authentication required')

            try:
                user_data = verify_token(auth['token'])
                user_id = user_data.get('sub')
                
                if not user_id:
                    logger.warning(f"Invalid token for {sid}")
                    raise ConnectionRefusedError('Invalid authentication token')

                await sio.save_session(sid, {
                    'user_id': user_id,
                    'connected_at': time.time(),
                    'is_processing': False,
                    'config': {}
                }, namespace=self.namespace)
                
                self.connection_count += 1
                realtime_connections_gauge.set(self.connection_count)
                
                logger.info(f"Client connected: {sid} (user: {user_id})")
                return True
                
            except Exception as e:
                logger.error(f"Authentication error: {str(e)}")
                raise ConnectionRefusedError('Authentication failed')
        
        @sio.event(namespace=self.namespace)
        async def disconnect(sid):
            """Handle client disconnection."""
            try:
                session = await sio.get_session(sid, namespace=self.namespace)
                user_id = session.get('user_id', 'unknown')
                
                self.connection_count -= 1
                realtime_connections_gauge.set(self.connection_count)
                
                if sid in self.detectors:
                    del self.detectors[sid]
                
                logger.info(f"Client disconnected: {sid} (user: {user_id})")
                
            except Exception as e:
                logger.error(f"Disconnect error: {str(e)}")
        
        @sio.event(namespace=self.namespace)
        async def initialize(sid, data):
            """Initialize session with configuration."""
            try:
                session = await sio.get_session(sid, namespace=self.namespace)
                client_id = data.get('client_id', sid)
                config = data.get('config', {})
                
                session['client_id'] = client_id
                session['config'] = config
                await sio.save_session(sid, session, namespace=self.namespace)
                
                self.detectors[sid] = VideoEmotionDetector(config=config)
                
                await sio.emit('initialized', {
                    'session_id': sid,
                    'timestamp': time.time(),
                    'config': {
                        'max_frame_rate': 10,
                        'max_resolution': [640, 480],
                        'supported_actions': ['start', 'stop', 'configure']
                    }
                }, room=sid, namespace=self.namespace)
                
                logger.info(f"Client initialized: {sid} (client_id: {client_id})")
                
            except Exception as e:
                logger.error(f"Initialization error: {str(e)}")
                await sio.emit('error_message', {
                    'code': 500,
                    'message': f'Failed to initialize: {str(e)}',
                    'timestamp': time.time()
                }, room=sid, namespace=self.namespace)
        
        @sio.event(namespace=self.namespace)
        async def control(sid, data):
            """Handle control commands: start, stop, configure."""
            try:
                session = await sio.get_session(sid, namespace=self.namespace)
                action = data.get('action')
                
                if action == 'start':
                    session['is_processing'] = True
                    await sio.save_session(sid, session, namespace=self.namespace)
                    
                    await sio.emit('status', {
                        'code': 200,
                        'message': 'Processing started',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                    
                elif action == 'stop':
                    session['is_processing'] = False
                    await sio.save_session(sid, session, namespace=self.namespace)
                    
                    await sio.emit('status', {
                        'code': 200,
                        'message': 'Processing stopped',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                    
                elif action == 'configure':
                    config = data.get('config', {})
                    session['config'].update(config)
                    await sio.save_session(sid, session, namespace=self.namespace)
                    
                    if sid in self.detectors:
                        self.detectors[sid].update_config(config)
                    
                    await sio.emit('status', {
                        'code': 200,
                        'message': 'Configuration updated',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                    
                else:
                    await sio.emit('error_message', {
                        'code': 400,
                        'message': f'Unknown action: {action}',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                    
            except Exception as e:
                logger.error(f"Control error: {str(e)}")
                await sio.emit('error_message', {
                    'code': 500,
                    'message': f'Control error: {str(e)}',
                    'timestamp': time.time()
                }, room=sid, namespace=self.namespace)
        
        @sio.event(namespace=self.namespace)
        async def join_room(sid, data):
            """Join a room to share detection results."""
            try:
                room = data.get('room')
                if room:
                    await sio.enter_room(sid, room, namespace=self.namespace)
                    await sio.emit('status', {
                        'code': 200,
                        'message': f'Joined room: {room}',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                else:
                    await sio.emit('error_message', {
                        'code': 400,
                        'message': 'Room name is required',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                    
            except Exception as e:
                logger.error(f"Join room error: {str(e)}")
                await sio.emit('error_message', {
                    'code': 500, 
                    'message': f'Error joining room: {str(e)}',
                    'timestamp': time.time()
                }, room=sid, namespace=self.namespace)
        
        @sio.event(namespace=self.namespace)
        async def video_frame(sid, data):
            """Process video frame and return detection results."""
            try:
                session = await sio.get_session(sid, namespace=self.namespace)
                
                if not session.get('is_processing', False):
                    await sio.emit('error_message', {
                        'code': 400,
                        'message': 'Processing not started',
                        'timestamp': time.time()
                    }, room=sid, namespace=self.namespace)
                    return
                
                if not data or 'data' not in data:
                    logger.warning(f"No frame data provided from client {sid}")
                    return
                
                frame_id = data.get('frame_id', 'unknown')
                
                self.latest_frames[sid] = data
                
                if self.processing_frames.get(sid, False):
                    logger.debug(f"Skipping frame {frame_id} for client {sid}, another frame is being processed")
                    return
                    
                self.processing_frames[sid] = True
                
                try:
                    latest_frame = self.latest_frames[sid]

                    await self._process_frame(sid, latest_frame)

                finally:
                    self.processing_frames[sid] = False
                    
            except Exception as e:
                logger.error(f"Video frame error: {str(e)}")
                self.processing_frames[sid] = False
                await sio.emit('error_message', {
                    'code': 500,
                    'message': f'Error processing frame: {str(e)}',
                    'frame_id': data.get('frame_id') if isinstance(data, dict) else 'unknown',
                    'timestamp': time.time()
                }, room=sid, namespace=self.namespace)

    async def emit_to_room(self, room: str, event: str, data: Dict[str, Any]):
        """
        Emit event to all clients in a room
        """
        await sio.emit(event, data, room=room, namespace=self.namespace)
    
    async def emit_to_all(self, event: str, data: Dict[str, Any]):
        """
        Emit event to all clients
        """
        await sio.emit(event, data, namespace=self.namespace)
    
    async def get_connected_clients(self) -> List[str]:
        """
        Get list of connected clients
        """
        return list(self.detectors.keys())

    async def _process_frame(self, sid: str, frame_data: Dict[str, Any]):
        """Process video frame using VideoEmotionDetector."""
        if sid not in self.detectors:
            session = await sio.get_session(sid, namespace=self.namespace)
            config = session.get('config', {})
            self.detectors[sid] = VideoEmotionDetector(config=config)
            logger.info(f"Initialized new VideoEmotionDetector for client {sid} with config: {config}")
            
        if not self._validate_frame_data(frame_data, sid):
            return None
            
        try:
            result = await self.detectors[sid].process_frame(frame_data)
            
            await sio.emit('detection_result', result, room=sid, namespace=self.namespace)
            
            if self.detectors[sid].frame_count % 30 == 0:
                metrics = self.detectors[sid].get_performance_metrics()
                await sio.emit('status', {
                    'code': 200,
                    'message': 'Processing metrics',
                    'timestamp': time.time(),
                    'metrics': metrics
                }, room=sid, namespace=self.namespace)
                
                if metrics['current_fps'] < 3 and metrics['processed_frames'] > 60:
                    suggested_config = {}
                    
                    current_width, current_height = self.detectors[sid].config['processing_resolution']
                    if current_width > 320:
                        suggested_config['processing_resolution'] = (
                            int(current_width * 0.7),
                            int(current_height * 0.7)
                        )
                    
                    if suggested_config:
                        await sio.emit('performance_suggestion', {
                            'code': 200,
                            'message': 'Performance optimization suggestion',
                            'suggested_config': suggested_config,
                            'timestamp': time.time()
                        }, room=sid, namespace=self.namespace)
            
            return result
        except Exception as e:
            logger.error(f"Error processing frame for client {sid}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    def _validate_frame_data(self, frame_data: Dict[str, Any], sid: str) -> bool:
        """Validate incoming frame data format."""
            
        required_fields = ['data', 'frame_id']
        for field in required_fields:
            if field not in frame_data:
                logger.error(f"Missing required field '{field}' in frame data from client {sid}")
                return False
                
        base64_data = frame_data.get('data', '')
        if not base64_data:
            logger.error(f"Empty base64 data from client {sid}")
            return False
            
        try:
            if ',' in base64_data:
                header, base64_data = base64_data.split(',', 1)
                if not header.startswith('data:image'):
                    logger.warning(f"Unusual data URI header from client {sid}: {header}")
                    
            if len(base64_data) < 100:
                logger.warning(f"Suspiciously short base64 data from client {sid}: {len(base64_data)} bytes")
                return False
                
            import base64
            base64.b64decode(base64_data[:20])
            
            return True
        except Exception as e:
            logger.error(f"Invalid base64 data from client {sid}: {str(e)}")
            return False

socket_manager = SocketManager() 