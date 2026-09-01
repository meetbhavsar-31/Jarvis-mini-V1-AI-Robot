import chromadb
import time
from jarvis.common.logger import setup_logger

logger = setup_logger()

class LongTermMemory:
    def __init__(self):
        # Creates a permanent database folder on your laptop
        self.client = chromadb.PersistentClient(path="./jarvis_brain_db")
        self.memory = self.client.get_or_create_collection(name="jarvis_core")
        logger.info("ChromaDB Long-Term Memory Initialized.")

    def remember(self, text: str):
        """Saves a fact permanently into JARVIS's brain."""
        doc_id = str(time.time())
        self.memory.add(documents=[text], ids=[doc_id])
        logger.info(f"Memory saved: {text}")

    def recall(self, query: str) -> str:
        """Searches past memories for context."""
        try:
            results = self.memory.query(query_texts=[query], n_results=2)
            if results and results['documents'] and results['documents'][0]:
                return " ".join(results['documents'][0])
        except Exception as e:
            logger.error(f"Memory Recall Error: {e}")
        return ""