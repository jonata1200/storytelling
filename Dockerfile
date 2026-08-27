FROM python:3.13-slim

WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

CMD ["python", "-m", "app.workers.main"]
