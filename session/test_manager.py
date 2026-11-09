"""
IELTS Test Session Manager
Implements the official 3-part test state machine.
"""

import os
import json
import time
from typing import Dict, List

from core.audio_capture import AudioCapture
from core.transcriber import LocalTranscriber
from core.examiner_agent import ExaminerAgent
from core.tts_engine import LocalTTSEngine

from scoring.fluency_scorer import FluencyScorer
from scoring.lexical_scorer import LexicalScorer
from scoring.grammar_scorer import GrammarScorer
from scoring.pronunciation_scorer import PronunciationScorer
from scoring.score_synthesizer import ScoreSynthesizer

class IELTSTestManager:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.data_dir = os.path.join(base_dir, "data")
        self.storage_dir = os.path.join(base_dir, "storage")

        # Load Question Bank
        qb_path = os.path.join(self.data_dir, "question_bank.json")
        with open(qb_path, "r", encoding="utf-8") as f:
            self.question_bank = json.load(f)

        # Core Engines
        self.audio = AudioCapture()
        self.asr = LocalTranscriber()
        self.examiner = ExaminerAgent()
        self.tts = LocalTTSEngine()

        # Scoring Engines
        self.fc_scorer = FluencyScorer(os.path.join(self.data_dir, "fillers.json"))
        self.lr_scorer = LexicalScorer(
            os.path.join(self.data_dir, "cefr_vocab_list.json"),
            os.path.join(self.data_dir, "discourse_markers.json")
        )
        self.gra_scorer = GrammarScorer()
        self.pr_scorer = PronunciationScorer()
        self.synthesizer = ScoreSynthesizer()

    def run_part_1(self, session_id: str) -> List[Dict]:
        """Conducts Part 1: Introduction and Interview."""
        print("\n" + "="*60)
        print("          STARTING IELTS SPEAKING - PART 1")
        print("="*60)

        turns = []
        topic_data = self.question_bank["part_1_topics"][0]
        questions = topic_data["questions"]

        for idx, q in enumerate(questions[:3], 1):
            self.tts.speak(q)

            # Record candidate
            wav_path = os.path.join(self.storage_dir, "audio", f"{session_id}_p1_q{idx}.wav")
            duration = self.audio.record_to_file(wav_path, max_duration_sec=30)

            # Transcribe
            transcript, words_data = self.asr.transcribe(wav_path)
            print(f"[Candidate Transcript]: \"{transcript}\"")

            turns.append({
                "question": q,
                "transcript": transcript,
                "duration": duration,
                "words_data": words_data
            })
            time.sleep(1)

        return turns

    def run_part_2(self, session_id: str) -> Dict:
        """Conducts Part 2: Long Turn (Cue Card)."""
        print("\n" + "="*60)
        print("          STARTING IELTS SPEAKING - PART 2")
        print("="*60)

        card = self.question_bank["part_2_cue_cards"][0]

        intro_text = (
            "Now, I am going to give you a topic, and I would like you to talk about it for one to two minutes. "
            "Before you talk, you will have one minute to think about what you are going to say. "
            "Here is your topic."
        )
        self.tts.speak(intro_text)

        print("\n" + "-"*50)
        print(f"CUE CARD: {card['title'].upper()}")
        print("You should say:")
        for bullet in card["bullet_points"]:
            print(f"  • {bullet}")
        print("-"*50)

        # 60-Second Preparation Timer
        print("\n[Timer]: 1-minute preparation time begins now. Prepare your thoughts...")
        for remaining in range(5, 0, -1):  # Shortened to 5s for snappy interactive demo
            print(f"  Preparation time remaining: {remaining}s...", end="\r")
            time.sleep(1)
        print("\n[Timer]: Preparation time is up.")

        prompt_speech = "All right. Remember, you have one to two minutes for this. Please begin speaking now."
        self.tts.speak(prompt_speech)

        # Record monologue
        wav_path = os.path.join(self.storage_dir, "audio", f"{session_id}_p2_monologue.wav")
        duration = self.audio.record_to_file(wav_path, max_duration_sec=120)

        transcript, words_data = self.asr.transcribe(wav_path)
        print(f"[Candidate Transcript]: \"{transcript}\"")

        return {
            "cue_card": card,
            "transcript": transcript,
            "duration": duration,
            "words_data": words_data
        }

    def run_part_3(self, session_id: str, card: Dict) -> List[Dict]:
        """Conducts Part 3: Two-way Abstract Discussion."""
        print("\n" + "="*60)
        print("          STARTING IELTS SPEAKING - PART 3")
        print("="*60)

        intro = f"We have been talking about a memorable journey, and now I would like to discuss with you one or two more general questions related to this."
        self.tts.speak(intro)

        turns = []
        questions = card.get("part_3_questions", [])

        for idx, q in enumerate(questions[:2], 1):
            self.tts.speak(q)

            wav_path = os.path.join(self.storage_dir, "audio", f"{session_id}_p3_q{idx}.wav")
            duration = self.audio.record_to_file(wav_path, max_duration_sec=45)

            transcript, words_data = self.asr.transcribe(wav_path)
            print(f"[Candidate Transcript]: \"{transcript}\"")

            turns.append({
                "question": q,
                "transcript": transcript,
                "duration": duration,
                "words_data": words_data
            })
            time.sleep(1)

        return turns

    def evaluate_full_session(self, all_turns: List[Dict]) -> Dict:
        """Aggregates all speech data across the test and computes the final Band Score."""
        combined_text = " ".join([t["transcript"] for t in all_turns if t.get("transcript")])
        combined_words = []
        total_time = 0.0

        for t in all_turns:
            total_time += t.get("duration", 0.0)
            combined_words.extend(t.get("words_data", []))

        # Evaluate the 4 criteria
        fc_res = self.fc_scorer.evaluate(combined_words, total_time)
        lr_res = self.lr_scorer.evaluate(combined_text)
        gra_res = self.gra_scorer.evaluate(combined_text)
        pr_res = self.pr_scorer.evaluate(combined_words)

        return self.synthesizer.synthesize(fc_res, lr_res, gra_res, pr_res)

