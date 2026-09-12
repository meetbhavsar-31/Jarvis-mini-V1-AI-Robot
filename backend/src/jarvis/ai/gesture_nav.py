import cv2
from jarvis.common.logger import setup_logger

logger = setup_logger()

try:
    import mediapipe as mp
    mp_hands = mp.solutions.hands
except (ImportError, AttributeError) as e:
    mp_hands = None
    logger.warning(f"MediaPipe hands solution not available: {e}")

class GestureNavigator:
    def __init__(self):
        self.mp_hands = mp_hands
        if self.mp_hands:
            self.hands = self.mp_hands.Hands(
                static_image_mode=False,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.5,
                max_num_hands=1
            )
        else:
            self.hands = None

    def detect_gesture(self, frame) -> str:
        if self.hands is None or frame is None:
            return "none"

        # FIX: this method had no error handling at all. app.py's
        # gesture_loop() called it directly in a `while True` with no
        # try/except either, so a single bad frame (wrong shape/dtype,
        # decode glitch, mediapipe internal error) would raise here,
        # propagate up uncaught, and silently kill the entire background
        # gesture thread forever -- Gesture Mode would then simply never
        # respond again until the whole app was restarted. gesture_loop()
        # in app.py now also wraps its call in try/except as a second line
        # of defense, but this method should never crash the caller either.
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = self.hands.process(rgb)
        except Exception as e:
            logger.error(f"Gesture detection failed on this frame: {e}")
            return "none"

        if res.multi_hand_landmarks:
            hand = res.multi_hand_landmarks[0]

            # Y-coordinates: lower value = higher up on the physical screen
            index_up = hand.landmark[8].y < hand.landmark[6].y
            middle_up = hand.landmark[12].y < hand.landmark[10].y
            ring_up = hand.landmark[16].y < hand.landmark[14].y
            pinky_up = hand.landmark[20].y < hand.landmark[18].y

            fingers_up = sum([index_up, middle_up, ring_up, pinky_up])

            # X-coordinates for thumb direction (Fist closed)
            thumb_x = hand.landmark[4].x
            pinky_x = hand.landmark[20].x

            if fingers_up >= 4:
                return "stop"       # Open Palm = Stop
            elif fingers_up == 1 or fingers_up == 2:
                return "forward"    # Pointing forward / Peace sign = Forward
            elif fingers_up == 0:
                # NOTE: if left/right ever come out reversed in practice,
                # it's because the forward-facing camera image isn't
                # mirrored the way a selfie camera would be -- swap the two
                # branches below rather than treating it as a logic bug.
                if thumb_x < pinky_x - 0.05:
                    return "left"   # Thumb pointing left
                elif thumb_x > pinky_x + 0.05:
                    return "right"  # Thumb pointing right

        return "none"
