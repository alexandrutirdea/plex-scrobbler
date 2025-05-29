FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY scrobbler.py .
COPY now_playing.py .
COPY start.sh .

RUN chmod +x start.sh && \
    pip install --no-cache-dir requests

CMD ["/app/start.sh"]
