# chat_logic.py (Updated to remove turn-by-turn reflection)

from datetime import datetime
from tinydb import TinyDB
from knowledge_base import MemoryManager
import config

class ChatLogic:
    def __init__(self):
        self.db = TinyDB('chat_history.json', indent=2)
        self.memory = MemoryManager()
        self.conversation_history = self.load_chat_history()

    def load_chat_history(self):
        return [{"role": "system", "content": config.SYSTEM_PROMPT}]
    
    def get_user_transcript(self) -> str:
        user_messages = [
            msg['content'] for msg in self.conversation_history if msg['role'] == 'user'
        ]
        return "\n".join(user_messages)

    def get_full_history_with_memory(self, query):
        recalled_context = self.memory.recall_memories(query)
        history_with_memory = self.conversation_history.copy()
        history_with_memory[0] = {
            "role": "system",
            "content": config.SYSTEM_PROMPT + recalled_context
        }
        return history_with_memory

    def add_user_message(self, user_input):
        user_message_data = { "role": "user", "content": user_input, "timestamp": datetime.now().isoformat() }
        self.conversation_history.append(user_message_data)
        self.db.insert(user_message_data)
        return user_message_data

    def add_ai_message(self, ai_response):
        ai_message_data = { "role": "assistant", "content": ai_response, "timestamp": datetime.now().isoformat() }
        self.conversation_history.append(ai_message_data)
        self.db.insert(ai_message_data)
        return ai_message_data

    # The process_and_archive function has been removed.

    def close(self):
        self.db.close()