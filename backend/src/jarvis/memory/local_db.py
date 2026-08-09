import sqlite3
import os
from datetime import datetime
from jarvis.common.logger import setup_logger

logger = setup_logger()

class LocalDatabase:
    def __init__(self):
        # Create the memory folder if it doesn't exist
        db_dir = os.path.join(os.path.dirname(__file__), "../../../../../memory")
        os.makedirs(db_dir, exist_ok=True)
        
        self.db_path = os.path.join(db_dir, "jarvis_memory.db")
        self._initialize_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_tables(self):
        """Creates the tables if they don't exist yet."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Chat History Table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL
                    )
                ''')
                
                # Vision & Telemetry State Table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS telemetry_state (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        sensor_type TEXT NOT NULL,
                        reading TEXT NOT NULL
                    )
                ''')
                conn.commit()
                logger.info("Local SQLite database initialized successfully.")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")

    def add_chat_message(self, role: str, content: str):
        """Saves a single chat message (user or assistant)."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO chat_history (role, content) VALUES (?, ?)", 
                    (role, content)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to add chat message: {e}")

    def get_recent_chat_history(self, limit: int = 10):
        """Retrieves the last X messages for context."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", 
                    (limit,)
                )
                # Reverse so they are in chronological order
                return cursor.fetchall()[::-1]
        except Exception as e:
            logger.error(f"Failed to fetch chat history: {e}")
            return []

    def log_telemetry(self, sensor_type: str, reading: str):
        """Logs a hardware reading (e.g., 'vision', 'detected: cup, person')."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO telemetry_state (sensor_type, reading) VALUES (?, ?)", 
                    (sensor_type, reading)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log telemetry: {e}")

    def get_latest_telemetry(self, sensor_type: str):
        """Gets the most recent reading from a specific sensor."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT reading FROM telemetry_state WHERE sensor_type = ? ORDER BY id DESC LIMIT 1", 
                    (sensor_type,)
                )
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Failed to get latest telemetry: {e}")
            return None