import customtkinter as ctk
import threading
from llm_handler import LLMHandler
from ui_handler import ChatApplication
from voice_handler import VoiceHandler
from chat_logic import ChatLogic # <-- Import ChatLogic

def main():
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    # Initialize all handlers
    voice_handler = VoiceHandler()
    chat_logic = ChatLogic()
    app = ChatApplication(root, voice_handler, chat_logic) # <-- Pass chat_logic
    def load_llm():
        llm_handler = LLMHandler()
        app.set_llm_handler(llm_handler)
    threading.Thread(target=load_llm, daemon=True).start()
    root.mainloop()
if __name__ == "__main__":
    main()
