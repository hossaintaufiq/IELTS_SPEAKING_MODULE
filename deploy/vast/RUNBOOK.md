# vast.ai benchmark session: runbook

Goal: one focused 4-6 hour session on a single RTX 4090 to measure STT, TTS and LLM on a real GPU (milestone M1). Budget is limited, so everything is prepared first and the instance is destroyed as soon as the numbers are saved.

## Before renting (free)

1. Public SSH key is added in the vast.ai console (Account, SSH Keys). Private key: `~/.ssh/vast_ed25519`. Keys apply at instance creation, so this must happen first.
2. Create an API key in the console (Account, API Keys), under the account that holds the credit. Put it in `deploy/vast/.env` as `VAST_API_KEY=...` (copy `.env.example`). Never paste it into chat.
3. Collect test audio: 20-50 clips of real non-native speakers as `eval/data/audio/NAME.wav` + `NAME.txt` (exact transcript). Without them only speed is measured, not accuracy.
4. Decide the LLM candidates to compare (set `LLM=` for `setup_instance.sh`). The default is a placeholder.

## Run (paid clock starts at step 2)

Use the venv Python from the repo root. The `vastai.exe` launcher is blocked on this PC, so everything goes through `vast.py`.

```
python deploy/vast/vast.py search
python deploy/vast/vast.py rent OFFER_ID --max-price 0.55          # dry run: prints price
python deploy/vast/vast.py rent OFFER_ID --max-price 0.55 --yes    # rents
python deploy/vast/vast.py status                                  # wait for "running", read SSH host/port
```

Offers are volatile: the list changes between calls, so an offer ID may vanish within seconds. If `rent` says "not found", run `search` again and rent the new ID straight away. Tested 2026-11-21: the price cap refuses an offer above `--max-price` correctly; no instance was ever created.

Pick offers with a high `Net_down`, `R` (reliability) above 98, and a $/hr you are comfortable with. Prefer on-demand over interruptible so the run is not cut off.

```
bash deploy/vast/upload.sh HOST PORT      # excludes .env, .venv, runs; NEVER use scp -r . (it would send your API key)
ssh -p PORT -i ~/.ssh/vast_ed25519 root@HOST -L 8080:localhost:8080
cd /workspace/speaking-service && bash deploy/vast/setup_instance.sh
```

Then wait for `Application startup complete` in `/workspace/vllm.log`, start the live test bench, and open
`http://localhost:8080` on your PC (the SSH forward makes it a localhost page, which browsers allow to use the mic):

```
cd /workspace/speaking-service && HOST=0.0.0.0 PORT=8080 python -m worker.server
```

Take the speaking test with headphones. Each run is saved to `runs/run_*.json` (transcript, phases, reply delays); `scp` it back
and use the UI's Download button too. UI-only dry run with no models: `MOCK=1 python -m worker.server`.

Then, for the numbers, on the box:

```
python -m eval.bench_stt --dir eval/data/audio --model small.en
python -m eval.bench_stt --dir eval/data/audio --model large-v3-turbo
python -m eval.bench_tts --model models/cache/kokoro-v1.0.onnx --voices models/cache/voices-v1.0.bin
python -m eval.bench_llm --model <the served model> --streams 12
nvidia-smi        # record VRAM used while all three are loaded
```

Copy the output into `docs/PROGRESS.md` and save the full logs (`scp` them back).

## Finish (do not skip)

```
python deploy/vast/vast.py destroy INSTANCE_ID
python deploy/vast/vast.py status     # confirm no instance and check the remaining balance
```

Stopping an instance does not stop billing: disk charges continue. Only destroy ends it. A zero balance auto-stops instances and can lose unsaved work, so copy results off first.

## Known gaps (not verified)

- `setup_instance.sh`, `bench_tts.py` and the model download URLs are untested; they have never run on a GPU. Expect to fix small things in the first 15 minutes.
- Model names and vLLM flags are placeholders. Re-check the current vLLM and kokoro-onnx docs.
- Pipecat installs as 0.0.108 on this PC's Python 3.10; newer releases (1.x) may need a newer Python. Decide on the GPU box's Python version before writing `worker/pipeline.py`.
- The Docker image tag in `vast.py` is a guess at a valid PyTorch+CUDA image.
