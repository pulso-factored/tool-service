FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV HOST=0.0.0.0 PORT=8080 PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["tool-service"]
