# Contributing

Use Python 3.12, install `requirements.txt` in a virtual environment, and run `python -m pytest` before
submitting a change. Tests use isolated databases and stubbed providers; no inventory API keys are needed.

Keep listing-provider calls bounded and user initiated unless scheduling is explicitly enabled. A partial scan
must leave unseen listings unchanged. Preserve existing saved settings and keep vehicle-specific inference
scoped to its actual make and model.

Use synthetic listings and redacted examples in reports, tests, and screenshots. Do not submit API keys,
working databases, contact notes, exports, or downloaded listing photos.
