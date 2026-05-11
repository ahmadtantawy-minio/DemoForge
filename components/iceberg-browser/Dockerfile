FROM python:3.12-slim AS prod

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "fastapi>=0.115" "uvicorn[standard]>=0.32" \
        "pyiceberg==0.11.1" "s3fs==2024.10.0" "fsspec==2024.10.0" \
        "pyarrow>=17,<20" "requests>=2.31" "boto3>=1.34"

COPY app/ /app/

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
