FROM python:3.12-slim
RUN pip install --no-cache-dir flask==3.0.3
WORKDIR /app
COPY app.py config.yml /app/
COPY order-report /usr/local/bin/order-report
RUN chmod 0755 /usr/local/bin/order-report && mkdir -p /app/data
EXPOSE 8080
CMD ["python", "/app/app.py"]
