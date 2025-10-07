# ui_handler.py (Updated to remove call to reflection)

import tkinter as tk
from tkinter import scrolledtext
import threading
import config

class ChatApplication:
    def __init__(self, root, voice_handler, chat_logic):
        self.root = root
        self.voice_handler = voice_handler
        self.chat_logic = chat_logic
        self.llm_handler = None
        self.root.title("AI Friend")
        self.root.geometry("600x700")
        self._setup_widgets()
        self.display_message("System", "Models loading... Amadeus Memory Core online.")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_widgets(self):
        # ... (unchanged, omitted for brevity) ...
        main_frame = tk.Frame(self.root, bg="#2E2E2E")
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.chat_history_text = scrolledtext.ScrolledText(
            main_frame, wrap=tk.WORD, state='disabled', bg="#1E1E1E", fg="#EAEAEA", font=("Helvetica", 10)
        )
        self.chat_history_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        input_frame = tk.Frame(main_frame, bg="#2E2E2E")
        input_frame.pack(padx=10, pady=5, fill=tk.X)
        self.listen_button = tk.Button(
            input_frame, text="🎤", command=self.start_listening, bg="#555555", fg="#FFFFFF", relief=tk.FLAT, font=("Helvetica", 12, "bold")
        )
        self.listen_button.pack(side=tk.LEFT, ipadx=5, ipady=4, padx=(0, 10))
        self.user_input_entry = tk.Entry(
            input_frame, bg="#3C3C3C", fg="#FFFFFF", insertbackground="#FFFFFF", font=("Helvetica", 11)
        )
        self.user_input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 10))
        self.user_input_entry.bind("<Return>", self.send_message)
        self.send_button = tk.Button(
            input_frame, text="Send", command=self.send_message, bg="#007ACC", fg="#FFFFFF", relief=tk.FLAT, font=("Helvetica", 10, "bold")
        )
        self.send_button.pack(side=tk.RIGHT, ipadx=10, ipady=4)

    def start_listening(self):
        # ... (unchanged, omitted for brevity) ...
        self.listen_button.config(state='disabled', text="...")
        self.voice_handler.listen(self.handle_recognized_text)

    def handle_recognized_text(self, text):
        # ... (unchanged, omitted for brevity) ...
        if "[ERROR]" not in text:
            self.user_input_entry.delete(0, tk.END)
            self.user_input_entry.insert(0, text)
            self.send_message()
        else:
            self.display_message("System", text)
        self.listen_button.config(state='normal', text="🎤")

    def send_message(self, event=None):
        # ... (unchanged, omitted for brevity) ...
        if self.llm_handler is None or self.llm_handler.llm is None:
            self.display_message("System", "The AI model is still loading. Please wait.")
            return
        user_input = self.user_input_entry.get().strip()
        if not user_input:
            return
        print("\n" + "="*50)
        print(f"You: {user_input}")
        self.display_message("You", user_input)
        self.user_input_entry.delete(0, tk.END)
        self.toggle_inputs('disabled')
        self.chat_logic.add_user_message(user_input)
        threading.Thread(target=self.process_response, args=(user_input,), daemon=True).start()

    def process_response(self, user_query):
        history = self.chat_logic.get_full_history_with_memory(user_query)
        ai_message = self.llm_handler.get_response(history)
        self.chat_logic.add_ai_message(ai_message)
        
        # The call to process_and_archive has been removed.
        
        self.root.after(0, self.display_ai_message, ai_message)

    def display_ai_message(self, ai_message):
        # ... (unchanged, omitted for brevity) ...
        print(f"AI: {ai_message}")
        print("="*50 + "\n")
        self.display_message("AI", ai_message)
        self.voice_handler.speak(ai_message)
        self.toggle_inputs('normal')
        self.user_input_entry.focus_set()

    def toggle_inputs(self, state):
        # ... (unchanged, omitted for brevity) ...
        self.user_input_entry.config(state=state)
        self.send_button.config(state=state)
        self.listen_button.config(state=state)

    def on_closing(self):
        # ... (unchanged, omitted for brevity) ...
        print("\n--- End of Session ---")
        print("Generating session summary...")
        transcript = self.chat_logic.get_user_transcript()
        if transcript and len(transcript.split()) > 10:
            session_summary = self.llm_handler.get_session_summary(transcript)
            print("\n--- Session Summary ---")
            print(session_summary)
            self.chat_logic.memory.archive_memory(session_summary, "Session Summary")
        else:
            print("Not enough conversation to generate a summary.")
        self.chat_logic.close()
        self.root.destroy()
        
    def set_llm_handler(self, llm_handler):
        # ... (unchanged, omitted for brevity) ...
        self.llm_handler = llm_handler
        self.display_message("AI", "Alright, I'm here. What's the plan? 😉")

    def display_message(self, sender, message):
        # ... (unchanged, omitted for brevity) ...
        self.chat_history_text.config(state='normal')
        self.chat_history_text.insert(tk.END, f"{sender}: {message}\n\n")
        self.chat_history_text.config(state='disabled')
        self.chat_history_text.yview(tk.END)