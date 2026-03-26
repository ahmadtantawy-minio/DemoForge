# Analytics Enrichment Plan — Saved for reference
# See conversation context for full plan details
# Components: Dremio, Redpanda, Redpanda Console, Kafka Connect S3, Nessie
# Datasets: clickstream
# Templates: Streaming Lakehouse, Dremio Lakehouse, Versioned Data Lake, Complete Analytics
# Build order: Redpanda → Kafka producer → Kafka Connect → clickstream → Template 1 → Dremio → Template 2 → Nessie → Template 3 → Template 4
