FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[all]"

EXPOSE 8000 8001

CMD ["python", "-m", "uvicorn", "datahek.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]