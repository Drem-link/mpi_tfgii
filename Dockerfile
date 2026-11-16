FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPI_DATASET_PATH=/var/lib/mpi/deposits.zip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 mpi \
    && useradd --system --uid 10001 --gid mpi --home-dir /app mpi \
    && mkdir -p /var/lib/mpi \
    && chown mpi:mpi /var/lib/mpi

COPY app ./app
COPY static ./static

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
