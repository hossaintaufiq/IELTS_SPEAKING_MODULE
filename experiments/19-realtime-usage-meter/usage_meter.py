from __future__ import annotations

from dataclasses import dataclass, field

PRICES_PER_M = {
    "realtime-2.1": {"audio_in": 32.0, "audio_cached": 0.40, "audio_out": 64.0},
    "realtime-2.1-mini": {"audio_in": 10.0, "audio_cached": 0.30, "audio_out": 20.0},
}


@dataclass
class UsageMeter:
    model: str
    audio_in: int = 0
    audio_cached: int = 0
    audio_out: int = 0
    text_in: int = 0
    text_out: int = 0
    responses: int = 0
    seen: set = field(default_factory=set)

    def feed(self, event: dict) -> bool:
        if event.get("type") != "response.done":
            return False
        response = event.get("response", {})
        key = response.get("id") or event.get("event_id")
        if key in self.seen:
            return False
        usage = response.get("usage")
        if not usage:
            return False
        self.seen.add(key)
        details_in = usage.get("input_token_details", {})
        cached = details_in.get("cached_tokens_details", {}).get("audio_tokens", 0)
        self.audio_cached += cached
        self.audio_in += max(details_in.get("audio_tokens", 0) - cached, 0)
        self.text_in += details_in.get("text_tokens", 0)
        details_out = usage.get("output_token_details", {})
        self.audio_out += details_out.get("audio_tokens", 0)
        self.text_out += details_out.get("text_tokens", 0)
        self.responses += 1
        return True

    def audio_cost_usd(self) -> float:
        p = PRICES_PER_M[self.model]
        return (
            self.audio_in * p["audio_in"] + self.audio_cached * p["audio_cached"] + self.audio_out * p["audio_out"]
        ) / 1e6

    def summary(self) -> dict:
        return {
            "model": self.model,
            "responses": self.responses,
            "audio_in_tokens": self.audio_in,
            "audio_cached_tokens": self.audio_cached,
            "audio_out_tokens": self.audio_out,
            "cache_hit_pct": round(100 * self.audio_cached / max(self.audio_cached + self.audio_in, 1), 1),
            "audio_cost_usd": round(self.audio_cost_usd(), 5),
        }
