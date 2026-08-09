from mcp.server.fastmcp import FastMCP
from jarvis.common.logger import setup_logger
from jarvis.robot_runtime.telemetry_manager import TelemetryManager
from jarvis.motion.motion_controller import MotionController # Uncommented!

logger = setup_logger()

mcp = FastMCP("jarvis_tools")
telemetry = TelemetryManager()
motion = MotionController() # Uncommented!

@mcp.tool()
def get_current_vision() -> str:
    """Returns a comma-separated string of the objects the robot is currently looking at."""
    state = telemetry.get_current_vision_context()
    logger.info(f"AI requested vision state: {state}")
    return f"I currently see: {state}"

@mcp.tool()
def get_front_distance() -> str:
    """Returns the distance to the nearest object in front of the robot in centimeters."""
    distance = telemetry.db.get_latest_telemetry(sensor_type="ultrasonic_front")
    return f"The nearest object ahead is {distance} cm away." if distance else "Distance unknown."

@mcp.tool() # Uncommented!
def move_robot(direction: str, duration_seconds: float) -> str:
    """Moves the robot forward, backward, left, or right for a specified duration."""
    return motion.execute_movement(direction, duration_seconds)

def start_mcp_server():
    logger.info("Starting Jarvis FastMCP Tool Server...")
    mcp.run()

if __name__ == "__main__":
    start_mcp_server()