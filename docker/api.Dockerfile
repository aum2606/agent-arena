FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev
# Not root: when the sandbox is off the worker runs model-written code in this container (D-068).
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "arena_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
