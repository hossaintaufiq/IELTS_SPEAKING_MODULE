"""
Local-IELTS Speaking Mock Test Runner
Interactive command-line interface for taking IELTS speaking tests and getting band scores.
"""

import os
import sys
import json
import time
from datetime import datetime

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from session.test_manager import IELTSTestManager

def print_banner():
    print("""
======================================================================
     LOCAL-IELTS: ON-DEVICE AI EXAMINER & BAND SCORING SYSTEM
       (Fluency | Lexical Resource | Grammar | Pronunciation)
======================================================================
""")

def print_scorecard(report: dict):
    print("\n" + "="*65)
    print("                OFFICIAL IELTS SPEAKING REPORT")
    print("="*65)
    print(f"\n >>> OVERALL BAND SCORE:  {report['overall_band']} / 9.0  (Raw Average: {report['raw_average']}) <<<\n")
    print("-" * 65)

    breakdown = report["breakdown"]
    criteria_names = [
        ("Fluency and Coherence", "fluency_and_coherence"),
        ("Lexical Resource", "lexical_resource"),
        ("Grammatical Range & Accuracy", "grammatical_range_and_accuracy"),
        ("Pronunciation", "pronunciation")
    ]

    for display_name, key in criteria_names:
        item = breakdown[key]
        print(f" • {display_name:<30}: Band {item['band']}")
        print(f"   Feedback: {item['feedback']}")
        print()

    print("-" * 65)
    print(f" • Primary Diagnostic Area : {report['primary_weakness']}")
    print(f" • Targeted Recommendation : {report['key_recommendation']}")
    print("="*65 + "\n")

def run_diagnostic_test():
    """Runs a quick single-turn test to verify all 4 scoring modules instantly."""
    print("\n[Diagnostic Mode]: Running quick assessment test...")
    manager = IELTSTestManager(BASE_DIR)

    sample_transcript = (
        "Well, I grew up in a vibrant coastal town which was renowned for its scenic beaches "
        "and rich cultural heritage. However, in recent years, rapid urbanization has noticeably "
        "exacerbated the local traffic congestion. Although the local council has implemented several "
        "sustainable initiatives, much remains to be done."
    )

    sample_words = []
    t = 0.5
    for w in sample_transcript.split():
        sample_words.append({"word": w, "start": round(t, 2), "end": round(t + 0.35, 2), "prob": 0.94})
        t += 0.42

    dummy_turns = [{
        "transcript": sample_transcript,
        "duration": 18.0,
        "words_data": sample_words
    }]

    report = manager.evaluate_full_session(dummy_turns)
    print_scorecard(report)

def run_interactive_session():
    """Runs an interactive mock exam with audio capture and speech synthesis."""
    session_id = datetime.now().strftime("test_%Y%m%d_%H%M%S")
    manager = IELTSTestManager(BASE_DIR)

    print(f"\n[Session Initialized]: ID {session_id}")
    print("You will complete Part 1, Part 2, and Part 3.")
    print("Please ensure your microphone is connected.\n")

    input("Press Enter to begin the test...")

    all_turns = []

    # Part 1
    p1_turns = manager.run_part_1(session_id)
    all_turns.extend(p1_turns)

    # Part 2
    p2_result = manager.run_part_2(session_id)
    all_turns.append(p2_result)

    # Part 3
    p3_turns = manager.run_part_3(session_id, p2_result["cue_card"])
    all_turns.extend(p3_turns)

    # Final Evaluation
    print("\n[Computing Band Score across all responses...]")
    report = manager.evaluate_full_session(all_turns)
    print_scorecard(report)

    # Save Session Record
    report_file = os.path.join(BASE_DIR, "storage", "reports", f"{session_id}.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "session_id": session_id,
            "turns": all_turns,
            "report": report
        }, f, indent=2)
    print(f"[Saved]: Full test record saved to {report_file}")

def main():
    print_banner()
    print("Select an option:")
    print("  1. Run Instant Scoring Engine Diagnostic (Fast test without microphone)")
    print("  2. Start Full Interactive IELTS Speaking Mock Exam (Microphone + TTS)")
    print("  3. Exit")

    choice = input("\nEnter choice (1, 2, or 3): ").strip()
    if choice == "1":
        run_diagnostic_test()
    elif choice == "2":
        run_interactive_session()
    else:
        print("Exiting.")

if __name__ == "__main__":
    main()

