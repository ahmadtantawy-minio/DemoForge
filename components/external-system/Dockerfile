FROM python:3.11-slim AS builder
RUN pip install --no-cache-dir --prefix=/install pyarrow boto3 pyyaml faker requests "pyiceberg[s3fs]"

FROM python:3.11-slim AS prod
ENV PYTHONUNBUFFERED=1
COPY --from=builder /install /usr/local
# Build context is the parent `components/` directory (see hub-push.sh / demoforge.sh).
COPY external-system/ /app/
COPY data-generator/datasets /app/vendor/data-generator/datasets
COPY data-generator/src /app/vendor/data-generator/src
COPY data-generator/generate.py /app/vendor/data-generator/generate.py
WORKDIR /app
CMD ["python", "run.py"]
