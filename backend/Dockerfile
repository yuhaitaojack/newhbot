FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml alembic.ini /app/
COPY migrations /app/migrations
COPY app /app/app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlalchemy aiosqlite alembic pydantic pydantic-settings httpx python-multipart

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
