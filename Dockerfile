FROM python:3.12-slim

WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY index.html data.js /app/
COPY server /app/server

CMD ["python", "-m", "server.app"]
