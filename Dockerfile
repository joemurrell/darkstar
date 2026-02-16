FROM python:3.11-slim

# Reduce glibc memory arena fragmentation in containers
ENV MALLOC_ARENA_MAX=2

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python", "app.py"]
