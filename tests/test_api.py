"""
End-to-End API Simulation Test
Simulates a candidate taking Part 1, Part 2, and Part 3 through the FastAPI REST endpoints.
"""

import urllib.request
import json

BASE_URL = "http://127.0.0.1:8000"

def post_json(endpoint: str, data: dict) -> dict:
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(endpoint: str) -> dict:
    url = f"{BASE_URL}{endpoint}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))

def test_full_exam_flow():
    print("\n--- 1. Testing Health Endpoint ---")
    health = get_json("/api/health")
    print("Health Status:", health)
    assert health["status"] == "online"

    print("\n--- 2. Starting Exam Session ---")
    session = post_json("/api/start-session", {})
    session_id = session["session_id"]
    print(f"Session Created: {session_id}")
    print(f"Examiner: {session['initial_message']}")

    print("\n--- 3. Simulating Part 1 Turns ---")
    p1_answers = [
        "Well, my full name is Aftab Hossain, but most of my friends and family simply call me Aftab.",
        "I was born and raised in a coastal town which is renowned for its picturesque scenery and vibrant community.",
        "Yes, in recent years, urbanization has expanded rapidly, which has led to significant infrastructural improvements."
    ]

    for idx, ans in enumerate(p1_answers, 1):
        turn_resp = post_json("/api/submit-turn", {
            "session_id": session_id,
            "part": 1,
            "question": f"Part 1 Question {idx}",
            "raw_text": ans,
            "duration": 12.0
        })
        print(f"  Turn {idx} submitted. Next Part: {turn_resp['next_part']}")

    print("\n--- 4. Checking Cue Card for Part 2 ---")
    cue_card = get_json(f"/api/cue-card/{session_id}")
    print(f"Cue Card: {cue_card['title']}")

    print("\n--- 5. Simulating Part 2 Monologue ---")
    p2_monologue = (
        "I would like to talk about a memorable journey I took to the highlands with my close friends two years ago. "
        "We decided to travel by train because we wanted to appreciate the scenic landscape. "
        "During the trip, we explored historic sites and hiked through lush mountain trails. "
        "This journey was unforgettable because it gave us a rare opportunity to disconnect from technology and reconnect with nature."
    )
    turn_resp = post_json("/api/submit-turn", {
        "session_id": session_id,
        "part": 2,
        "question": cue_card["title"],
        "raw_text": p2_monologue,
        "duration": 60.0
    })
    print(f"Part 2 Monologue submitted. Next Part: {turn_resp['next_part']}")

    print("\n--- 6. Simulating Part 3 Discussion ---")
    p3_answers = [
        "From my perspective, modern travel has become substantially more accessible due to budget airlines, although it has occasionally led to over-tourism.",
        "Sustainable eco-tourism is of paramount importance to ensure local cultural traditions and delicate ecosystems remain protected for future generations."
    ]
    for idx, ans in enumerate(p3_answers, 1):
        turn_resp = post_json("/api/submit-turn", {
            "session_id": session_id,
            "part": 3,
            "question": f"Part 3 Question {idx}",
            "raw_text": ans,
            "duration": 20.0
        })
        print(f"  Part 3 Turn {idx} submitted. Next Part: {turn_resp['next_part']}")

    print("\n--- 7. Requesting Final Band Scorecard ---")
    report = post_json("/api/evaluate-session", {"session_id": session_id})
    print("\n" + "="*50)
    print(f"OVERALL IELTS BAND: {report['overall_band']} / 9.0 (Raw Average: {report['raw_average']})")
    print("="*50)
    for criterion, data in report["breakdown"].items():
        print(f" • {criterion:<32}: Band {data['band']}")
    print(f"\nPrimary Area for Improvement: {report['primary_weakness']}")
    print(f"Targeted Recommendation:      {report['key_recommendation']}")
    print("="*50)

if __name__ == "__main__":
    test_full_exam_flow()

