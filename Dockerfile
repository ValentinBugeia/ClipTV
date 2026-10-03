# Image cliptv : ffmpeg + whisper + opencv + Claude, prête pour un serveur.
#   docker compose up -d            (voir README, section « Déploiement »)
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY clipbot ./clipbot
RUN pip install --no-cache-dir ".[all]"

# police des sous-titres (licence SIL OFL) ; tes propres .ttf dans fonts/ sont aussi copiés
COPY fonts ./fonts
ADD https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf \
    ./fonts/Montserrat-Black.ttf

# données (base SQLite, tokens, vidéos) et modèles Whisper dans le volume /data
ENV CLIPBOT_DATA_DIR=/data \
    HF_HOME=/data/models \
    PYTHONUNBUFFERED=1
VOLUME /data

ENTRYPOINT ["clipbot"]
CMD ["doctor"]
