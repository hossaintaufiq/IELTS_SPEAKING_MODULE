"""
IELTS Examiner Persona Agent
Conducts Parts 1, 2, and 3 dialogue using local LLM inference or dynamic question banks.
"""

import os
import json
import urllib.request
from typing import List, Dict

class ExaminerAgent:
    def __init__(self, gguf_path: str = None, use_ollama: bool = True, ollama_model: str = "llama3.1:8b-instruct-q4_K_M"):
        self.gguf_path = gguf_path
        self.use_ollama = use_ollama
        self.ollama_model = ollama_model
        self.llama_cpp_model = None

        self.system_prompt = (
            "You are a strict, formal, certified British Council IELTS Speaking Examiner. "
            "You are conducting an official IELTS Speaking exam. "
            "Strict Guidelines:\n"
            "1. Ask exactly ONE natural follow-up question per turn.\n"
            "2. Keep your conversational turn concise, polite, and neutral (1-2 sentences max).\n"
            "3. NEVER provide feedback, scores, praise (like 'Good job!' or 'Well done!'), or grammar corrections during the test.\n"
            "4. Follow the candidate's line of thought with authentic IELTS inquiry (e.g. 'Why do you say that?', 'Could you give an example?')."
        )
        self.history = [{"role": "system", "content": self.system_prompt}]
        self._init_backend()

    def _init_backend(self):
        # Auto-detect GGUF in models/llm/ if path not explicitly given
        if not self.gguf_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            llm_dir = os.path.join(base_dir, "models", "llm")
            if os.path.exists(llm_dir):
                for f in os.listdir(llm_dir):
                    if f.endswith(".gguf"):
                        self.gguf_path = os.path.join(llm_dir, f)
                        break

        if self.gguf_path and os.path.exists(self.gguf_path):
            try:
                from llama_cpp import Llama
                print(f"[ExaminerAgent] Found local GGUF model: {self.gguf_path}")
                self.llama_cpp_model = Llama(
                    model_path=self.gguf_path,
                    n_ctx=4096,
                    n_gpu_layers=-1,
                    verbose=False
                )
            except Exception as e:
                print(f"[ExaminerAgent Warning] Could not load llama-cpp: {e}")

    def query_ollama(self, messages: List[Dict]) -> str:
        """Queries local Ollama instance running on localhost:11434."""
        url = "http://localhost:11434/api/chat"
        payload = json.dumps({
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 70}
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["message"]["content"].strip()

    def generate_turn(self, candidate_utterance: str, part: int = 1, fallback_question: str = None) -> str:
        """
        Receives candidate's answer and produces the examiner's next inquiry,
        actively listening to what the candidate said and generating an authentic contextual follow-up.
        """
        candidate_utterance = candidate_utterance.strip()
        words = candidate_utterance.split()

        # Handle very short answers / hesitant candidate
        if len(words) < 5 and candidate_utterance:
            prompt = (
                f"Candidate provided a very short or hesitant response: '{candidate_utterance}'. "
                "As a supportive but formal IELTS examiner, ask them to expand or elaborate on this naturally in one sentence."
            )
        elif part == 1:
            prompt = (
                f"The candidate just answered: '{candidate_utterance}'. "
                "As an authentic British Council IELTS Speaking examiner conducting Part 1, briefly acknowledge their answer "
                "(e.g., 'I see.', 'Right.', 'Interesting.') and ask ONE natural follow-up question directly related to what they specifically mentioned. "
                "Keep it natural, conversational, and under 2 sentences."
            )
        elif part == 2:
            prompt = (
                f"The candidate just completed their Part 2 monologue: '{candidate_utterance[:300]}...'. "
                "Thank them politely in one short sentence and introduce a brief follow-up question."
            )
        else: # Part 3
            prompt = (
                f"The candidate just stated: '{candidate_utterance}'. "
                "As an IELTS Speaking examiner conducting Part 3, ask an abstract, analytical follow-up question "
                "that builds directly on their specific perspective (e.g., societal implications, comparing past vs future, or asking 'Why do you think that is?'). "
                "Keep it strictly to one insightful question."
            )

        self.history.append({"role": "user", "content": prompt})

        # 1. Try Ollama local HTTP daemon
        if self.use_ollama:
            try:
                reply = self.query_ollama(self.history)
                # Clean up quotes and unwanted meta text
                reply = reply.strip().strip('"').strip("'")
                self.history.append({"role": "assistant", "content": reply})
                return reply
            except Exception:
                pass

        # 2. Try llama-cpp-python
        if self.llama_cpp_model is not None:
            try:
                resp = self.llama_cpp_model.create_chat_completion(
                    messages=self.history,
                    temperature=0.35,
                    max_tokens=65
                )
                reply = resp["choices"][0]["message"]["content"].strip().strip('"').strip("'")
                self.history.append({"role": "assistant", "content": reply})
                return reply
            except Exception:
                pass

        # 3. Dynamic Linguistic Contextual Synthesizer (Ensures contextual follow-up even without GPU daemon)
        contextual_reply = self._generate_contextual_followup(candidate_utterance, part, fallback_question)
        self.history.append({"role": "assistant", "content": contextual_reply})
        return contextual_reply

    def _generate_contextual_followup(self, utterance: str, part: int, fallback_question: str = None) -> str:
        """
        Dynamically extracts key concepts from candidate speech and generates relevant IELTS follow-ups.
        """
        if not utterance or len(utterance.split()) < 4:
            return "Could you elaborate a bit more on why that is the case for you?"

        lower = utterance.lower()

        # Part 1: Personal context follow-ups
        if part == 1:
            if any(k in lower for k in ["work", "job", "career", "study", "university", "school", "engineer", "software"]):
                return "Interesting. What do you find to be the most demanding aspect of that field?"
            elif any(k in lower for k in ["hometown", "city", "village", "country", "born", "live", "place"]):
                return "I see. In what ways has that area changed since your childhood?"
            elif any(k in lower for k in ["family", "friend", "people", "parents", "children"]):
                return "Right. And how do you usually prefer to spend your leisure time with them?"
            elif any(k in lower for k in ["travel", "journey", "trip", "holiday", "visit"]):
                return "That sounds enjoyable. Do you prefer travelling independently or in a group?"
            else:
                return "I understand. And how has this impacted your personal daily routine recently?"

        # Part 3: Abstract societal follow-ups
        else:
            if any(k in lower for k in ["technology", "ai", "digital", "phone", "internet", "machine"]):
                return "You made an interesting point. Do you believe technological developments will create more problems than they solve in the future?"
            elif any(k in lower for k in ["tourism", "travel", "culture", "local", "environment"]):
                return "That is a notable perspective. How can communities balance economic benefits of tourism with preserving local heritage?"
            elif any(k in lower for k in ["government", "society", "people", "public", "money"]):
                return "To what extent should individuals take responsibility for this, rather than relying on authorities?"
            else:
                return "Interesting view. Why do you think people's attitudes toward this have evolved so significantly in recent years?"

