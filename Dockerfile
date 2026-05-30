FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COLOPHON_LIBRARY_DIR=/books \
    COLOPHON_DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        calibre \
        libxml2 \
        libxslt1.1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends python3-six && rm -rf /var/lib/apt/lists/*

COPY tools/install_calibre_plugins.sh /tmp/install_calibre_plugins.sh
RUN bash /tmp/install_calibre_plugins.sh \
    && rm /tmp/install_calibre_plugins.sh

COPY tools/install_kepubify.sh /tmp/install_kepubify.sh
RUN bash /tmp/install_kepubify.sh \
    && rm /tmp/install_kepubify.sh

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Self-host the webfont so the app shell never blocks first paint on an
# external fonts.googleapis.com request. Must run after `COPY . .` (writes into
# app/static/fonts). Never fails the build — falls back to the vendored copy /
# Georgia. Runs after COPY so a fresh build always refreshes the woff2.
RUN bash tools/install_fonts.sh

RUN pybabel compile -d app/translations

RUN mkdir -p /books /data

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "300", "--workers", "2", "--access-logfile", "-", "--access-logformat", "%(h)s %(r)s %(s)s %(b)s %(L)ss \"%(a)s\"", "wsgi:app"]
