FROM python:3.12-slim
COPY app.py /app.py
RUN mkdir -p /srv/api
EXPOSE 5000
CMD ["python3", "-u", "/app.py"]
