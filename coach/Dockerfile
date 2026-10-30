FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY coach ./coach
RUN pip install --no-cache-dir .

CMD ["python", "-m", "coach.main"]
