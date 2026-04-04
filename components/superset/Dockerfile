FROM apache/superset:4.1.2

USER root

# Install Trino SQLAlchemy driver + flask-cors (required when ENABLE_CORS=True)
RUN pip install --no-cache-dir trino[sqlalchemy] flask-cors

# Copy bootstrap config
COPY superset_config.py /app/superset_config.py
ENV SUPERSET_CONFIG_PATH=/app/superset_config.py

# Copy init script
COPY superset-init.sh /app/superset-init.sh
RUN chmod +x /app/superset-init.sh

USER superset

EXPOSE 8088

ENTRYPOINT ["/app/superset-init.sh"]
