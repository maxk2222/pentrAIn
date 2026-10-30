FROM python:3.12-slim
RUN pip install --no-cache-dir flask
WORKDIR /srv/app
COPY app.py .
EXPOSE 80
CMD ["python", "app.py"]
