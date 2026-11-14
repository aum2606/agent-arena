# The image model-written snippets run in (D-044, D-069): the base pinned by digest, plus SymPy because the
# attacker prompt allows it. The worker builds it as arena-sandbox:1 when it is missing. SymPy's version is the
# one in uv.lock. The runtime container has no network; only this build step does.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
RUN pip install --no-cache-dir sympy==1.14.0
