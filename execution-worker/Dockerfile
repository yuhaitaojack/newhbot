ARG BASE_IMAGE=hummingbot/hummingbot:version-2.16.0
FROM ${BASE_IMAGE}

# Official v2.16.0 runtime is Python 3.13.14. Do not install Hummingbot on 3.12.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/hummingbot:/app \
    EXECUTION_ENABLED=false \
    EXECUTION_MODE=hyperliquid \
    HUMMINGBOT_VERSION=v2.16.0 \
    PATH=/opt/conda/envs/hummingbot/bin:${PATH}

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY app /app/app

RUN /opt/conda/envs/hummingbot/bin/pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic

EXPOSE 8001
# Replace Hummingbot's interactive entrypoint with the Worker HTTP API.
ENTRYPOINT []
CMD ["/opt/conda/envs/hummingbot/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
