FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OSIFONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
    ZARYA_PROJECTS_DIR=/data/projects

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-dejavu-core \
        fonts-liberation \
        libcairo2 \
        libharfbuzz-subset0 \
        libopenjp2-7 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --requirement requirements.txt
RUN python -c "import cairosvg; assert cairosvg.svg2pdf(bytestring=b'<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1\" height=\"1\"/>').startswith(b'%PDF')"

COPY app ./app

RUN useradd --create-home --uid 10001 zarya \
    && mkdir -p /data/projects \
    && chown -R zarya:zarya /data

USER zarya

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
