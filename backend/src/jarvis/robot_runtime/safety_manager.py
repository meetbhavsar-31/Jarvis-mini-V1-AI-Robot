import cv2
import time
import threading
from jarvis.common.logger import setup_logger

logger = setup_logger()

class SecurityPatrolManager:
    def __init__(self, vision_pipeline, motion_controller, cloud_manager):
        self.vision = vision_pipeline
        self.motion = motion_controller
        self.cloud = cloud_manager
        self.is_patrolling = False
        self.patrol_thread = None
        self.previous_frame = None

    def start_patrol(self):
        if self.is_patrolling:
            return
        self.is_patrolling = True
        self.patrol_thread = threading.Thread(target=self._patrol_loop, daemon=True)
        self.patrol_thread.start()
        logger.info("Security Patrol Mode Activated.")

    def stop_patrol(self):
        self.is_patrolling = False
        self.motion.execute_movement("stop", 0.0)
        if self.patrol_thread and self.patrol_thread.is_alive():
            self.patrol_thread.join(timeout=2.0)
        logger.info("Security Patrol Mode Deactivated.")

    def _patrol_loop(self):
        while self.is_patrolling:
            frame = self.vision.get_latest_frame()
            if frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if self.previous_frame is None:
                    self.previous_frame = gray
                    time.sleep(1.0)
                    continue

                # Compute frame difference to detect motion
                delta_frame = cv2.absdiff(self.previous_frame, gray)
                thresh = cv2.threshold(delta_frame, 25, 255, cv2.THRESH_BINARY)[1]
                thresh = cv2.dilate(thresh, None, iterations=2)
                
                motion_score = np.sum(thresh) if 'np' in globals() else 0
                
                # If significant movement is detected during patrol
                if motion_score > 100000:
                    logger.warning("Motion detected in patrol zone! Triggering security protocol.")
                    try:
                        self.cloud.upload_snapshot(frame)
                    except Exception as e:
                        logger.error(f"Failed to upload security snapshot: {e}")
                
                self.previous_frame = gray
            
            # Simple patrol navigation pattern: Move forward, scan, or rotate
            self.motion.execute_movement("forward", 1.0)
            time.sleep(3.0)
            self.motion.execute_movement("stop", 0.0)
            time.sleep(2.0)