# 07 — Local examiner LLM with Ollama

## Objective
Measure whether small open models running locally on a CPU can generate the examiner's adaptive follow-up questions fast enough to replace a paid text or voice model for that step.

## Method
- Models served by Ollama: `qwen3:0.6b`, `qwen3:1.7b` and `llama3.2:3b` (default quantisation).
- A system prompt asks for one follow-up question of at most 20 words. Five candidate answers (Part 1 style) are sent one at a time after a warm-up call. Thinking mode is disabled, temperature 0.4, output capped at 60 tokens.
- Recorded: end-to-end wall time per reply, generation speed (tokens per second) and a format check (exactly one question, ends with "?", at most 20 words).
- Replies are listed in `results.json` for reading.

Machine: Intel Core i7-1195G7 (4 cores), 8 GB RAM, no GPU, no other heavy load.

## Results

| Model | Median wall time (s) | Median tokens/s | Format check |
|---|---|---|---|
| qwen3:0.6b | 2.38 | 69.6 | 5/5 |
| qwen3:1.7b | 2.97 | 26.0 | 5/5 |
| llama3.2:3b | 3.98 | 13.5 | 5/5 |

Example replies to "I live in a small town near the sea…":

- qwen3:0.6b — *What makes the small town near the sea unique?*
- qwen3:1.7b — *What do you think about the local community or the way people interact there?*
- llama3.2:3b — *Do you think the town's quiet nature is a disadvantage for young people, or an advantage?*

## Findings
- All three satisfy the output format, but wall time of 2.4–4.0 s per reply is slow for a live turn. Prompt processing, not generation, is a large share of it at this short length, so streaming the first sentence to the voice early helps.
- Quality differs even where format passes. `qwen3:0.6b` once produced a two-sentence reply that mixed up who was speaking ("…I also enjoy playing it with my friends. How does this help you?"); `llama3.2:3b` produced the most natural, answer-specific questions but is about 1.7x slower than `qwen3:1.7b`.
- With no API charge, the local route costs only machine time. A 3B model is the smallest tried that read as examiner-like; whether it holds up across a whole test was not measured.

## Limitations
- Five prompts, one run each. No human rating, no multi-turn conversation, no Part 3 abstract questions, no check that questions stay on topic or avoid giving feedback.
- Time to first token was not measured separately from total time.
- 8 GB of RAM holds one of these models plus the speech models, but the combined memory footprint of the full local pipeline was not measured here.

## Reproduce
```
ollama pull qwen3:0.6b
ollama pull qwen3:1.7b
ollama pull llama3.2:3b
python run.py qwen3:0.6b qwen3:1.7b llama3.2:3b
```
