# ui_handler.py

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
        
        self.voice_handler.set_interruption_callback(self.handle_interruption)
        self.voice_handler.set_speech_end_callback(self.handle_speech_end)
        
        self.voice_mode_active = False
        
        self.root.title("AI Friend")
        self.root.geometry("600x700")
        self._setup_widgets()
        self.display_message("System", "Models loading... Click the 🎤 to start Voice Mode.")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_widgets(self):
        # ... (unchanged)
        main_frame = tk.Frame(self.root, bg="#2E2E2E")
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.chat_history_text = scrolledtext.ScrolledText(
            main_frame, wrap=tk.WORD, state='disabled', bg="#1E1E1E", fg="#EAEAEA", font=("Helvetica", 10)
        )
        self.chat_history_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        input_frame = tk.Frame(main_frame, bg="#2E2E2E")
        input_frame.pack(padx=10, pady=5, fill=tk.X)
        
        self.listen_button = tk.Button(
            input_frame, text="🎤", command=self.toggle_voice_mode, bg="#555555", fg="#FFFFFF", relief=tk.FLAT, font=("Helvetica", 12, "bold")
        )
        self.listen_button.pack(side=tk.LEFT, ipadx=5, ipady=4, padx=(0, 10))
        
        self.user_input_entry = tk.Entry(
            input_frame, bg="#3C3C3C", fg="#FFFFFF", insertbackground="#FFFFFF", font=("Helvetica", 11)
        )
        self.user_input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 5))
        
        self.user_input_entry.bind("<Return>", self.send_message)
        
        self.send_button = tk.Button(
            input_frame, text="Send", command=self.send_message, bg="#007ACC", fg="#FFFFFF", relief=tk.FLAT, font=("Helvetica", 10, "bold")
        )
        self.send_button.pack(side=tk.RIGHT, ipadx=10, ipady=4)


    def toggle_voice_mode(self):
        # ... (unchanged)
        if self.voice_mode_active:
            self.voice_mode_active = False
            self.listen_button.config(text="🎤", bg="#555555")
            self.display_message("System", "Voice Mode Deactivated.")
            self.toggle_inputs('normal') 
        else:
            self.voice_mode_active = True
            self.display_message("System", "Voice Mode Activated.")
            self.toggle_inputs('disabled') 
            self.start_listening() 

    def start_listening(self):
        # ... (unchanged)
        if not self.voice_mode_active:
            return 
        print("UI: Starting to listen...")
        self.listen_button.config(state='normal', text="...", bg="#E74C3C")
        self.voice_handler.listen(self.handle_recognized_text)

    def handle_speech_end(self):
        # ... (unchanged)
        self.root.after(0, self.process_speech_end)

    def process_speech_end(self):
        # ... (unchanged)
        if self.voice_mode_active:
            print("UI: Speech ended. Looping to listen again.")
            self.start_listening() 
        else:
            print("UI: Speech ended. Voice mode off, not looping.")
            self.listen_button.config(state='normal')

    def handle_recognized_text(self, text):
        # ... (unchanged)
        self.root.after(0, self.process_recognized_text, text)

    # --- MODIFIED ---
    def process_recognized_text(self, text):
        if not self.voice_mode_active:
            self.toggle_inputs('normal')
            self.listen_button.config(state='normal', text="🎤", bg="#555555")
            return

        if "[ERROR]" not in text:
            # We don't need the entry box, pass text directly
            self.send_message(text=text) 
        else:
            self.display_message("System", text)
            self.start_listening() 

    def handle_interruption(self, text):
        # ... (unchanged)
        self.root.after(0, self.process_interruption_text, text)

    # --- MODIFIED ---
    def process_interruption_text(self, text):
        if not self.voice_mode_active:
            return

        if "[ERROR]" not in text:
            # We don't need the entry box, pass text directly
            self.send_message(text=text) 
        else:
            self.display_message("System", text)
            self.start_listening() 

    # --- MODIFIED: To accept text directly ---
    def send_message(self, event=None, text=None):
        if self.llm_handler is None:
            self.display_message("System", "The AI model is still loading. Please wait.")
            return
        
        user_input = ""
        if text:
            # Text came from voice, use it
            user_input = text
        else:
            # Text came from manual entry, get it
            user_input = self.user_input_entry.get().strip()
            
        if not user_input:
            if self.voice_mode_active:
                self.start_listening()
            return
            
        print("\n" + "="*50)
        print(f"You: {user_input}")
        self.display_message("You", user_input)
        self.user_input_entry.delete(0, tk.END)
        
        if not self.voice_mode_active:
            self.toggle_inputs('disabled')

        self.chat_logic.add_user_message(user_input)
        threading.Thread(target=self.process_response, args=(user_input,), daemon=True).start()

    def process_response(self, user_query):
        # ... (unchanged)
        history = self.chat_logic.get_full_history_with_memory(user_query) 
        ai_message = self.llm_handler.get_response(history)
        self.chat_logic.add_ai_message(ai_message) 
        self.root.after(0, self.display_ai_message, ai_message)

    def display_ai_message(self, ai_message):
        # ... (unchanged, includes the empty-string fix)
        if not ai_message.strip():
            print("AI: [Chose to say nothing]")
            if self.voice_mode_active:
                self.start_listening()
            else:
                self.toggle_inputs('normal')
                self.user_input_entry.focus_set()
            return

        print(f"AI: {ai_message}")
        print("="*50 + "\n")
        self.display_message("AI", ai_message)
        
        if self.voice_mode_active:
            self.listen_button.config(state='normal', text="...", bg="#2E8B57") # Green
            self.voice_handler.speak_with_barge_in(ai_message)
        else:
            self.voice_handler.speak_silently(ai_message)
            self.toggle_inputs('normal')
            self.user_input_entry.focus_set()

    def toggle_inputs(self, state):
        # ... (unchanged)
        if self.voice_mode_active:
            self.user_input_entry.config(state=state)
            self.send_button.config(state=state)
            set
            self.listen_button.config(state='normal') 
        else:
            self.user_input_entry.config(state=state)
            self.send_button.config(state=state)
            self.listen_button.config(state=state)

    def on_closing(self):
        # ... (unchanged)
        print("\n--- End of Session ---")
        try:
            transcript = self.chat_logic.get_user_transcript()
            if transcript and len(transcript.split()) > 10:
                session_summary = self.llm_handler.get_session_summary(transcript)
                print("\n--- Session Summary ---")
                print(session_summary)
                self.chat_logic.memory.archive_memory(session_summary, "Session Summary")
            else:
                print("Not enough conversation to generate a summary.")
        except Exception as e:
            print(f"Could not generate summary: {e}")
            
        self.chat_logic.close()
        self.root.destroy()
        
    def set_llm_handler(self, llm_handler):
        # ... (unchanged)
        self.llm_handler = llm_handler
        self.display_message("AI", "Alright, I'm here. What's the plan? 😉")

    def display_message(self, sender, message):
        # ... (unchanged)
        self.chat_history_text.config(state='normal')
        self.chat_history_text.insert(tk.END, f"{sender}: {message}\n\n")
        self.chat_history_text.config(state='disabled')
        self.chat_history_text.yview(tk.END)