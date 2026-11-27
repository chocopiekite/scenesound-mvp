FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY studio/requirements.txt /app/studio/requirements.txt
RUN python3 -m venv /app/.venv-studio && /app/.venv-studio/bin/pip install --no-cache-dir -r /app/studio/requirements.txt
COPY studio/engine.py studio/automatic.py studio/dialogue.py studio/dialogue_preserve.py studio/dialogue_reference.py studio/dialogue_fades.py studio/speech.py studio/file-upload.cjs studio/storage.cjs studio/editor-model.js studio/server.cjs studio/local-bridge.cjs studio/worker.cjs /app/studio/
COPY scripts/fetch-vad-model.py /app/scripts/fetch-vad-model.py
RUN /app/.venv-studio/bin/python /app/scripts/fetch-vad-model.py
COPY studio/VAD-LICENSE.txt /app/studio/VAD-LICENSE.txt
COPY lib/studio-auth.cjs /app/lib/studio-auth.cjs
RUN useradd --create-home --uid 10001 studio
USER studio
ENV NODE_ENV=production STUDIO_PUBLIC=1 STUDIO_MAX_DURATION=1800 STUDIO_MAX_TRACKS=32 STUDIO_MAX_CLIPS=1024 STUDIO_MAX_SECONDS=14400 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1
EXPOSE 10000
CMD ["node","studio/worker.cjs"]
