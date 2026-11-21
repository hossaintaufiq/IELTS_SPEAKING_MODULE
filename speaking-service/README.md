# Speaking Service

Fully local IELTS Speaking test service: an AI examiner that speaks, listens and produces estimated practice feedback. Runs on GPU servers, called by the company's Node app over an API. See `docs/`.

- `docs/PROGRESS.md`: what is done, next and blocked (update with every change)
- `docs/DECISIONS.md`: why we chose what we chose, plus open questions
- `docs/ARCHITECTURE.md`: shape and diagram link
- `docs/API_CONTRACT.md`: draft contract for the Node team

## Run the tests

```
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest
```

Only the pure-Python parts exist and are tested so far (eval metrics, GPU provisioner interface, test flow). The voice pipeline and control-plane API are not written yet; see PROGRESS.md.
