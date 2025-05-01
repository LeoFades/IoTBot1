import cv2
import base64
import threading
import time
import logging
from flask_socketio import SocketIO

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("webcam_stream.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("WebcamStream")

class WebcamStreamer:
    def __init__(self, socketio, camera_id=0, fps=20, quality=70, flip_method=0):
        """Initialize the webcam streamer
        
        Args:
            socketio: The Flask-SocketIO instance
            camera_id: Camera device ID (default: 0)
            fps: Frames per second (default: 20)
            quality: JPEG quality 0-100 (default: 70)
            flip_method: 0=none, 1=horizontal, 2=vertical, 3=both
        """
        self.socketio = socketio
        self.camera_id = camera_id
        self.fps = fps
        self.quality = quality
        self.flip_method = flip_method
        self.running = False
        self.camera = None
        self.thread = None
        
        # Frame dimensions
        self.width = 640
        self.height = 480
        
        logger.info(f"WebcamStreamer initialized (camera_id={camera_id}, fps={fps})")

    def start(self):
        """Start the webcam streaming"""
        if self.running:
            logger.warning("Webcam streamer is already running")
            return
        
        try:
            self.camera = cv2.VideoCapture(self.camera_id)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            
            if not self.camera.isOpened():
                logger.error(f"Could not open camera with ID {self.camera_id}")
                return False
                
            self.running = True
            self.thread = threading.Thread(target=self._stream_thread)
            self.thread.daemon = True
            self.thread.start()
            logger.info("Webcam streaming started")
            return True
            
        except Exception as e:
            logger.error(f"Error starting webcam stream: {e}")
            return False
    
    def stop(self):
        """Stop the webcam streaming"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        
        if self.camera:
            self.camera.release()
            self.camera = None
        
        logger.info("Webcam streaming stopped")
    
    def _stream_thread(self):
        """Thread function that captures and emits webcam frames"""
        frame_interval = 1.0 / self.fps
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.quality]
        
        while self.running:
            start_time = time.time()
            
            # Capture frame
            success, frame = self.camera.read()
            if not success:
                logger.warning("Failed to capture frame")
                time.sleep(0.1)
                continue
            
            # Apply flip if needed
            if self.flip_method == 1:
                frame = cv2.flip(frame, 1)  # Horizontal
            elif self.flip_method == 2:
                frame = cv2.flip(frame, 0)  # Vertical
            elif self.flip_method == 3:
                frame = cv2.flip(frame, -1)  # Both
            
            # Encode the frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, encode_params)
            if not ret:
                continue
                
            # Convert to base64 string
            jpg_as_text = base64.b64encode(buffer).decode('utf-8')
            
            # Emit the frame via socketio
            self.socketio.emit('webcam_frame', {'image': jpg_as_text})
            
            # Calculate sleep time to maintain FPS
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            time.sleep(sleep_time)

# To be integrated with main Flask app
def init_webcam_stream(app):
    """Initialize and return SocketIO instance with webcam streaming"""
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
    streamer = WebcamStreamer(socketio)
    
    @socketio.on('connect')
    def handle_connect():
        logger.info("Client connected to webcam stream")
        if not streamer.running:
            streamer.start()
    
    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info("Client disconnected from webcam stream")
        # Keep streaming in case other clients are still connected
    
    @socketio.on('start_stream')
    def handle_start_stream(data=None):
        if not streamer.running:
            success = streamer.start()
            return {'success': success}
        return {'success': True}
    
    @socketio.on('stop_stream')
    def handle_stop_stream(data=None):
        if streamer.running:
            streamer.stop()
            return {'success': True}
        return {'success': False}
        
    return socketio, streamer