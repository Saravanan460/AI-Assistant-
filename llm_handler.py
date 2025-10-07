# llm_handler.py (Updated to remove turn-by-turn summary)

from llama_cpp import Llama
import config

class LLMHandler:
    def __init__(self):
        print("Loading main model...")
        self.llm = Llama(
            model_path=config.MODEL_PATH,
            n_ctx=config.N_CTX,
            n_gpu_layers=config.N_GPU_LAYERS,
            verbose=False
        )
        print("Main model loaded successfully.")

    def get_response(self, messages):
        response = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=1024,
            temperature=0.7
        )
        return response['choices'][0]['message']['content'].strip()

    # The old get_summary function has been removed.

    def get_session_summary(self, full_chat_text: str):
        """
        Summarizes the entire user-side conversation at the end of a session.
        """
        system_prompt = """You are a world-class summarization AI. Your task is to read a transcript of a user's side of a conversation and create a concise, bulleted list of the key personal facts revealed by the user. Focus on preferences, relationships, life events, and opinions.

- Extract concrete information.
- Use the third person (e.g., "The user...").
- Combine related facts into single, coherent points.
- If no significant personal information was revealed, state that."""

        user_prompt = f"""Please summarize the key personal facts from the following transcript of my conversation:

{full_chat_text}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        response = self.llm.create_chat_completion(
            messages=messages, max_tokens=256, temperature=0.2
        )
        return response['choices'][0]['message']['content'].strip()