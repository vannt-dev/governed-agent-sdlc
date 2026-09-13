# Contributing

Open an issue before changing workflow semantics, artifact schemas, approval rules, role authority, or
security hooks. Pull requests should remain focused and include tests for every allow and deny path
changed in a guard.

Run locally:

```bash
python -m pip install -e .
agentkit validate
python -m unittest discover -s tests -v
```

Generated adapter files must identify their canonical core source. Do not duplicate a policy across
roles, adapters, documentation, and workflows.

