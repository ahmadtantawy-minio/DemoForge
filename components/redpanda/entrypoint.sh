#!/bin/bash
# Dynamic entrypoint that uses the container hostname for advertise addresses.
# This ensures Kafka clients can reconnect using the correct Docker DNS name.
ADVERTISE_HOST="${HOSTNAME}"

exec redpanda start \
  --overprovisioned \
  --smp 1 \
  --memory 512M \
  --reserve-memory 0M \
  --node-id 0 \
  --kafka-addr "internal://0.0.0.0:9092,external://0.0.0.0:19092" \
  --advertise-kafka-addr "internal://${ADVERTISE_HOST}:9092,external://localhost:19092" \
  --schema-registry-addr "internal://0.0.0.0:8081,external://0.0.0.0:18081" \
  --pandaproxy-addr "internal://0.0.0.0:8082,external://0.0.0.0:18082" \
  --mode dev-container \
  --default-log-level=warn
