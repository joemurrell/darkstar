FROM python:3.11-slim

# Reduce glibc memory arena fragmentation in containers
ENV MALLOC_ARENA_MAX=2

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
# The extracted ACC documentation the bot loads at startup. Generate with
# scripts/extract_pdf.py and commit it — the build (and a working bot)
# requires it.
COPY acc_document.txt .

RUN useradd -U -u 1000 appuser && chown -R 1000:1000 /app
USER 1000

CMD ["python", "app.py"]
