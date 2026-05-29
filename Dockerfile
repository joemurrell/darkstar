FROM python:3.11-slim

# Reduce glibc memory arena fragmentation in containers
ENV MALLOC_ARENA_MAX=2

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py db.py ./
# The extracted ACC documentation the bot loads at startup. Generate with
# scripts/extract_pdf.py and commit it — the build (and a working bot)
# requires it.
COPY acc_document.txt .
# The pre-generated quiz question bank. Committed empty ([]) until seeded with
# scripts/generate_quiz_bank.py; the bot falls back to live generation while
# it's empty.
COPY acc_questions.json .

RUN useradd -U -u 1000 appuser && chown -R 1000:1000 /app
USER 1000

CMD ["python", "app.py"]
