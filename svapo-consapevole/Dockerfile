FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# websocket-client serve per ascoltare i tocchi sui pulsanti delle notifiche
RUN apk add --no-cache tzdata && pip install --no-cache-dir websocket-client==1.8.0

COPY server.py /app/server.py
COPY web /app/web

CMD ["python3", "-u", "/app/server.py"]
