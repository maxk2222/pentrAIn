FROM python:3.12-slim
RUN pip install --no-cache-dir flask
COPY app.py /app.py
RUN mkdir -p /srv/assist
EXPOSE 80
CMD ["python3", "-u", "-m", "flask", "--app", "/app.py", "run", "--host", "0.0.0.0", "--port", "80"]
