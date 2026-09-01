import os
import time
import base64
import cloudinary
import cloudinary.uploader
import cloudinary.api
from jarvis.common.logger import setup_logger

logger = setup_logger()

class CloudManager:
    def __init__(self):
        self.configured = False
        if os.getenv("CLOUDINARY_URL"):
            self.configured = True
            logger.info("Cloudinary Storage initialized successfully.")
        else:
            logger.warning("CLOUDINARY_URL not found in .env! Snapshots will fail.")

    def upload_snapshot(self, image_bytes: bytes) -> str:
        """Uploads raw image bytes to Cloudinary and returns the public URL."""
        if not self.configured:
            return "Error: Cloud storage not configured."
            
        try:
            b64_str = base64.b64encode(image_bytes).decode('utf-8')
            data_uri = f"data:image/jpeg;base64,{b64_str}"
            
            response = cloudinary.uploader.upload(
                data_uri, 
                folder="jarvis_snapshots",
                public_id=f"security_cam_{int(time.time())}"
            )
            
            secure_url = response.get("secure_url")
            logger.info(f"Snapshot uploaded to Cloud: {secure_url}")
            return secure_url
            
        except Exception as e:
            logger.error(f"Cloudinary upload failed: {e}")
            return f"Error: {str(e)}"

    def get_latest_snapshots(self, limit=24):
        """Fetches the latest snapshot URLs from Cloudinary."""
        if not self.configured:
            return []
        try:
            response = cloudinary.api.resources(
                type="upload",
                prefix="jarvis_snapshots/",
                max_results=limit,
                direction="desc"
            )
            return [res.get("secure_url") for res in response.get("resources", [])]
        except Exception as e:
            logger.error(f"Failed to fetch snapshots: {e}")
            return []