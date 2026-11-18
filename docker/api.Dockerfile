FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev
# Not root: when the sandbox is off the worker runs model-written code in this container (D-068).
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "arena_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
