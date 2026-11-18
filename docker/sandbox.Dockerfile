# The image model-written snippets run in (D-044, D-069): the base pinned by digest, plus SymPy because the
# attacker prompt allows it. The worker builds it as arena-sandbox:1 when it is missing. SymPy's version is the
# one in uv.lock. The runtime container has no network; only this build step does.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
RUN pip install --no-cache-dir sympy==1.14.0
