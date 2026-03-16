FROM python:3.11-slim
RUN pip install --no-cache-dir pyarrow boto3
COPY generate.py /app/generate.py
WORKDIR /app
CMD ["python", "generate.py"]
