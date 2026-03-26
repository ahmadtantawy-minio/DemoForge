FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir pyarrow boto3 pyyaml faker requests "pyiceberg[s3fs]" kafka-python-ng
COPY . /app/
WORKDIR /app
CMD ["python", "generate.py"]
