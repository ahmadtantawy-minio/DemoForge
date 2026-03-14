FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache curl && pip install --no-cache-dir fastapi uvicorn minio python-multipart

COPY app/ /app/

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
