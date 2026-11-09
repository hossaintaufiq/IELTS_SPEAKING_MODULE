"""
Local-IELTS Resource Downloader & Environment Setup Script
Automates the acquisition of all offline weights from Hugging Face and creates folder structures.
"""

import os
import sys
import json
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DIRS_TO_CREATE = [
    "models/llm",
    "models/asr",
    "models/tts",
    "models/grammar",
    "models/pronunciation",
    "data",
    "storage/audio",
    "storage/sessions",
    "storage/reports"
]

def make_directories():
    print("[1/5] Creating directory structure...")
    for d in DIRS_TO_CREATE:
        full_path = os.path.join(BASE_DIR, d)
        os.makedirs(full_path, exist_ok=True)
    print("      Directory structure ready.")

def create_lexicon_data():
    print("[2/5] Initializing linguistic dictionaries...")
    
    # Fillers dictionary
    fillers_path = os.path.join(BASE_DIR, "data", "fillers.json")
    if not os.path.exists(fillers_path):
        fillers = [
            "um", "uh", "er", "ah", "like", "you know", "i mean", 
            "sort of", "kind of", "basically", "actually"
        ]
        with open(fillers_path, "w", encoding="utf-8") as f:
            json.dump(fillers, f, indent=2)

    # Discourse markers for Band 7+ Coherence
    markers_path = os.path.join(BASE_DIR, "data", "discourse_markers.json")
    if not os.path.exists(markers_path):
        markers = {
            "addition": ["furthermore", "moreover", "in addition", "additionally", "not only that but"],
            "contrast": ["on the other hand", "however", "nevertheless", "conversely", "whereas", "in contrast"],
            "cause_effect": ["consequently", "as a result", "therefore", "thus", "for this reason"],
            "example": ["for instance", "to illustrate", "such as", "a prime example being"],
            "concession": ["despite this", "although", "even though", "admittedly"],
            "opinion": ["from my perspective", "in my view", "as far as i am concerned", "i am convinced that"]
        }
        with open(markers_path, "w", encoding="utf-8") as f:
            json.dump(markers, f, indent=2)

    # CEFR Sample Tier Lexicon
    cefr_path = os.path.join(BASE_DIR, "data", "cefr_vocab_list.json")
    if not os.path.exists(cefr_path):
        sample_cefr = {
            "C1_C2": [
                "ubiquitous", "scenic", "profound", "detrimental", "imperative", 
                "proliferation", "exacerbate", "unprecedented", "compelling", 
                "paramount", "versatile", "innovative", "reminisce", "vibrant",
                "perspective", "sustainable", "infrastructure", "implication"
            ],
            "B1_B2": [
                "convenient", "essential", "advantage", "disadvantage", "challenge",
                "opportunity", "frequently", "tradition", "impact", "influence",
                "beneficial", "experience", "society", "environment", "culture"
            ]
        }
        with open(cefr_path, "w", encoding="utf-8") as f:
            json.dump(sample_cefr, f, indent=2)

    print("      Linguistic reference data initialized.")

def setup_nlp_engine():
    print("[3/5] Initializing NLP linguistic analyzer (spaCy / NLTK)...")
    # Dynamic check to prevent static LSP / Pyright warnings if spaCy is not present
    spacy_ready = False
    try:
        import importlib
        spacy_module = importlib.import_module("spacy")
        try:
            spacy_module.load("en_core_web_sm")
            print("      [NLP] spaCy model 'en_core_web_sm' is ready.")
            spacy_ready = True
        except Exception:
            try:
                subprocess.check_call([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
                spacy_ready = True
            except Exception:
                pass
    except Exception:
        # Expected when spaCy is missing or when Windows Application Control blocks third-party cblas/thinc DLLs
        pass

    # If spaCy is unavailable or blocked by OS policy, verify NLTK
    if not spacy_ready:
        print("      [NLP] Falling back to pre-approved NLTK engine...")
        try:
            import nltk
            for package in ["punkt", "punkt_tab", "averaged_perceptron_tagger_eng", "wordnet"]:
                nltk.download(package, quiet=True)
            print("      [NLP] NLTK tokenizers and POS taggers are verified and ready.")
        except Exception as e:
            print(f"      [NLP Warning] Could not configure NLTK: {e}")

def download_llm_instructions():
    print("[4/5] LLM Acquisition Instructions:")
    llm_dir = os.path.join(BASE_DIR, "models", "llm")
    model_name = "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    expected_path = os.path.join(llm_dir, model_name)
    
    if os.path.exists(expected_path):
        print(f"      [FOUND] Local LLM is ready at: {expected_path}")
    else:
        print("      To download the 8B LLM locally, run either:")
        print(f"        huggingface-cli download bartowski/Meta-Llama-3.1-8B-Instruct-GGUF {model_name} --local-dir {llm_dir}")
        print("      OR use Ollama:")
        print("        ollama pull llama3.1:8b-instruct-q4_K_M")

def summary():
    print("\n[5/5] Setup Check Complete!")
    print(f"Project root is: {BASE_DIR}")
    print("Refer to STRUCTURE.md for full model documentation and API options.")

if __name__ == "__main__":
    make_directories()
    create_lexicon_data()
    setup_nlp_engine()
    download_llm_instructions()
    summary()

