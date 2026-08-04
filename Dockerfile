FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY trading_debate ./trading_debate

RUN python -m pip install --no-cache-dir .

RUN mkdir -p /app/data /app/reports

EXPOSE 8765

CMD ["trading-debate", "--db", "/app/data/research.sqlite3", "serve", "--reports", "/app/reports", "--host", "0.0.0.0", "--port", "8765"]
