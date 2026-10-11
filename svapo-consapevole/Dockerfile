FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY server.py /app/server.py
COPY web /app/web

CMD ["python3", "-u", "/app/server.py"]
