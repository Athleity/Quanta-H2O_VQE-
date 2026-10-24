# Environment requirements

`pyproject.toml` is the canonical package/dependency definition. These files
are convenience install targets for specific project environments:

- `requirements-wsl.txt` — core project dependencies.
- `requirements-noise.txt` — core dependencies plus Qiskit Aer.
- `requirements-backend-noise.txt` — core dependencies plus Aer and IBM Runtime.

Run pip from the repository root so each editable install (`-e .`) resolves to
the project package:

    python -m pip install --prefer-binary -r config/requirements/requirements-wsl.txt
