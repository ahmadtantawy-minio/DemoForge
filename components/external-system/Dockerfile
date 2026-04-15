FROM python:3.11-slim AS builder
RUN pip install --no-cache-dir --prefix=/install pyarrow boto3 pyyaml faker requests "pyiceberg[s3fs]"

FROM python:3.11-slim AS prod
ENV PYTHONUNBUFFERED=1
COPY --from=builder /install /usr/local
COPY . /app/
WORKDIR /app
CMD ["python", "run.py"]
