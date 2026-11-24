import json

from fastapi.testclient import TestClient

import worker.server as server
import worker.session as sess


def test_ui_is_served_and_mock_websocket_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    c = TestClient(server.app)
    page = c.get("/")
    assert page.status_code == 200 and "IELTS Speaking" in page.text
    for asset in ("style.css", "app.js", "worklet.js"):
        assert c.get(f"/static/{asset}").status_code == 200

    with c.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"action": "start"}))
        seen = []
        while not any(e.get("type") == "transcript" for e in seen if isinstance(e, dict)):
            m = ws.receive()
            seen.append(json.loads(m["text"]) if m.get("text") else {"bytes": len(m["bytes"])})
        assert any(e.get("phase") == "intro" for e in seen if isinstance(e, dict))
        ws.send_text(json.dumps({"action": "next_part"}))
        ws.send_text(json.dumps({"action": "end"}))
