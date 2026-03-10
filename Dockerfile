FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data

ENV PYTHONPATH=/app/src
ENV PORT=8000

EXPOSE 8000

CMD ["python3", "-m", "job_agent", "serve-ui", "--host", "0.0.0.0", "--port", "8000"]
