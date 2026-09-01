Compose file lives at the repository root (`docker-compose.yml`) so `docker compose up -d` works on Windows with relative volumes `./data`, `./logs`, and `./strategies`.

If `docker` is not on PATH, Docker Desktop's user-scope binary is typically:

`%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe`

Production backend start: `alembic upgrade head` then uvicorn. Do not use `create_all` on that path.

