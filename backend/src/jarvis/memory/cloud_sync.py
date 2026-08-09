from jarvis.common.logger import setup_logger

logger = setup_logger()

class CloudSyncManager:
    def __init__(self):
        self.enabled = False
        
    def sync_to_cloud(self):
        """Placeholder for future cloud sync logic."""
        if self.enabled:
            logger.info("Syncing local database to cloud...")
        else:
            pass # Cloud sync disabled for local operation