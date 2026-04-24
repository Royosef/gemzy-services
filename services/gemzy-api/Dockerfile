FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build with the repo root as context:
# docker build -f services/gemzy-api/Dockerfile .
COPY services/gemzy-api/server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/gemzy-api/server ./server
COPY packages/prompting/prompting ./prompting

RUN adduser --disabled-password --gecos "" gemzy && chown -R gemzy:gemzy /app
USER gemzy

EXPOSE 5050

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "5050"]
