FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget \
 && rm -rf /var/lib/apt/lists/*

# Litestream — SQLite replication to GCS
ARG LITESTREAM_VERSION=0.3.13
RUN wget -qO /tmp/ls.tgz \
      "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
 && tar -xzf /tmp/ls.tgz -C /usr/local/bin litestream \
 && rm /tmp/ls.tgz

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY litestream.yml /etc/litestream.yml
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /data/hub-api

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
