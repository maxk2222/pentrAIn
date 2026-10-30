FROM python:3.12-slim
RUN pip install --no-cache-dir flask
WORKDIR /srv/api
COPY app.py .
EXPOSE 5000
CMD ["python", "app.py"]
