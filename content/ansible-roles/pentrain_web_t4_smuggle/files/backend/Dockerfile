FROM python:3.12-slim
RUN pip install --no-cache-dir flask
COPY app.py /app.py
EXPOSE 5000
CMD ["python3", "-u", "/app.py"]
