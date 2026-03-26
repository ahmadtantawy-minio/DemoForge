FROM jupyter/minimal-notebook:latest

USER root
RUN pip install --no-cache-dir \
    boto3==1.35.0 \
    pyarrow==17.0.0 \
    pandas==2.2.3 \
    scikit-learn==1.5.2 \
    mlflow==2.17.0 \
    matplotlib==3.9.2 \
    seaborn==0.13.2 \
    pyiceberg[s3]==0.7.1 \
    qdrant-client==1.12.0 \
    httpx==0.28.1

# Pre-load sample notebooks
COPY notebooks/ /home/jovyan/work/
RUN chown -R jovyan:users /home/jovyan/work/

USER jovyan
