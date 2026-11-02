# Yuyi

Inspectable external state for conversational assistants: episodic memory, simulated affect, a provisional self model and a neural-style viewer.

Python 3.10+, standard-library runtime. This project does not change model weights or establish consciousness or subjective feelings. Modules are independent: affect does not alter memory retention, and the self model defaults to observation without prompt injection.

```sh
python demo_reading.py
python demo_emotion.py
python demo_self.py
python -m unittest discover -v
python viewer/serve_neural.py
```

Visit `http://127.0.0.1:8765`. The viewer creates a separate fictional demo ledger. Its write/delete actions affect the selected directory; use a copy for existing data. Opening `viewer/dist/index.html` directly uses a separate browser-local demo.

Optional installation exposes Python modules and the `yuyi-emotion` / `yuyi-self` commands:

```sh
python -m pip install .
python -m yuyi_emotion --db data/emotion.sqlite3 init
python -m yuyi_self --assistant assistant-1 init
```

- Memory: transactional SQLite, evidence gates, fading, project boundaries, bounded associative recall and path audits. Root-level memory imports remain available; the turn reader is `from turn_reader import ChatMemory`.
- Affect: baseline, slow mood and short affect; pleasure/arousal/agency coordinates, context-gated word regions, expression guidance and reversible events.
- Self model: scoped capability/limitation/habit proposals, independent evidence, counterexamples, explicit review and revision history. Approval does not automatically enable chat references.
- Viewer: rotatable projected neural field, recall pulses, ledger inspection and loopback-only Python API.

The host supplies model callbacks, trusted source metadata, per-user isolation and its conversation loop. There are no provider keys, messaging integrations or background tasks. Model assessment can be wrong; interface tests are not semantic-quality validation.

[Project guide](docs/PROJECT.md) · [Integration](docs/INTEGRATION.md) · [Privacy](docs/PRIVACY.md) · [MIT license](LICENSE)
