import logging
import os
from datetime import datetime

def setup_logger():
    log_dir = os.path.join(os.path.dirname(__file__), "../../../../memory/logs")
    os.makedirs(log_dir, exist_ok=True)
    
    logger = logging.getLogger("JARVIS_MINI")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        
        # Console Handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        # File Handler
        log_file = os.path.join(log_dir, f"jarvis_{datetime.now().strftime('%Y%m%d')}.log")
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
    return logger