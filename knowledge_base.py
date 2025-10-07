import time
import chromadb

class MemoryManager:
    def __init__(self, db_path="./chroma_db", collection_name="chatbot_memory"):
        print("Initializing Advanced Memory Core...")
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(name=collection_name)
        print("Advanced Memory Core online.")

    def recall_memories(self, query: str, n_results: int = 3) -> str:
        if self.collection.count() == 0:
            return ""
        
        results = self.collection.query(query_texts=[query], n_results=n_results)
        recalled_docs = results['documents'][0] if results['documents'] else []
        
        if not recalled_docs:
            return ""
        
        context_header = "\n\n--- RECALLED MEMORIES (Use these for context) ---\n"
        context = "\n".join(f"- {doc}" for doc in recalled_docs)
        return context_header + context

    def archive_memory(self, text: str, memory_type: str = "Conversation"):
        if not text or len(text.split()) < 4:
            return
            
        memory_id = str(int(time.time() * 1000))
        self.collection.add(
            documents=[text],
            metadatas=[{"type": memory_type}],
            ids=[memory_id]
        )
        print(f"[{memory_type} Memory Archived]: {text}")