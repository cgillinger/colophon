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

COPY tools/install_calibre_plugins.sh /tmp/install_calibre_plugins.sh
RUN bash /tmp/install_calibre_plugins.sh \
    && rm /tmp/install_calibre_plugins.sh

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /books /data

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "wsgi:app"]
