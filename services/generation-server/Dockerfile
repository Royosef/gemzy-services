FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Build with the repo root as context:
# docker build -f services/generation-server/Dockerfile .
COPY services/generation-server/generation_server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/generation-server/generation_server ./generation_server
COPY packages/prompting/prompting ./prompting

EXPOSE 8100

CMD ["uvicorn", "generation_server.app:app", "--host", "0.0.0.0", "--port", "8100"]
