FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Embed a Unicode font in exported study PDFs and OCR embedded images only when present.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app \
    && useradd --system --gid app --create-home app

COPY requirements.txt /app/requirements.txt

RUN pip install -r /app/requirements.txt

COPY --chown=app:app . /app

RUN chown app:app /app

USER app

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["python", "-m", "config.web_runtime"]
