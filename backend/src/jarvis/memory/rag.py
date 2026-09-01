import os
import chromadb
from jarvis.common.logger import setup_logger

logger = setup_logger()

class LongTermMemoryManager:
    def __init__(self, persist_path="./jarvis_brain_db"):
        try:
            self.client = chromadb.PersistentClient(path=persist_path)
            self.collection = self.client.get_or_create_collection(name="jarvis_long_term_memory")
            logger.info(f"ChromaDB Long-Term Memory initialized successfully at path: {persist_path}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")

    def add_memory(self, doc_id: str, text_content: str, metadata: dict = None):
        """Stores text data permanently into the vector database."""
        try:
            self.collection.upsert(
                documents=[text_content],
                metadatas=[metadata or {"source": "user_interaction"}],
                ids=[doc_id]
            )
            logger.info(f"Stored long-term memory ID: {doc_id}")
        except Exception as e:
            logger.error(f"Error adding memory to ChromaDB: {e}")

    def query_memory(self, query_text: str, n_results: int = 2) -> str:
        """Searches past long-term memories using semantic similarity."""
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            documents = results.get("documents", [[]])[0]
            if documents:
                return "\n".join(documents)
            return ""
        except Exception as e:
            logger.error(f"Error querying ChromaDB memory: {e}")
            return ""

    def get_all_memories(self):
        """Fetches all stored memories for the dashboard."""
        try:
            result = self.collection.get()
            memories = []
            if result and "ids" in result:
                for i in range(len(result["ids"])):
                    memories.append({
                        "id": result["ids"][i],
                        "text": result["documents"][i],
                        "metadata": result["metadatas"][i] if result["metadatas"] else {}
                    })
            memories.sort(key=lambda x: x["metadata"].get("timestamp", 0), reverse=True)
            return memories
        except Exception as e:
            logger.error(f"Error fetching all memories: {e}")
            return []

    def delete_memory(self, doc_id: str):
        """Deletes a specific memory by ID."""
        try:
            self.collection.delete(ids=[doc_id])
            logger.info(f"Deleted memory ID: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting memory {doc_id}: {e}")
            return False