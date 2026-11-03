FROM python:3.12-slim
RUN pip install --no-cache-dir flask \
 && apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY app.py /app.py
EXPOSE 8080
CMD ["python3", "-u", "-m", "flask", "--app", "/app.py", "run", "--host", "0.0.0.0", "--port", "8080"]
