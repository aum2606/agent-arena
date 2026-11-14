# The image model-written snippets run in (D-044, D-069): the base pinned by digest, plus SymPy because the
# attacker prompt allows it. The worker builds it as arena-sandbox:1 when it is missing. SymPy's version is the
# one in uv.lock. The runtime container has no network; only this build step does.
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
RUN pip install --no-cache-dir sympy==1.14.0
