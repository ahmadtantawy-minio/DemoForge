"""
kafka_writer.py — Write batches as JSON messages to a Kafka topic.

Reads connection config from environment:
  KAFKA_BOOTSTRAP_SERVERS — comma-separated list, e.g. "kafka:9092"
  KAFKA_TOPIC             — topic name to produce to

Auto-creates the topic if it does not exist using the Kafka admin client.
"""

import datetime
import json
import os

try:
    from kafka import KafkaProducer
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError
    _KAFKA_AVAILABLE = True
except ImportError:
    _KAFKA_AVAILABLE = False


def _serialize_value(val):
    """JSON-serialize a row value, converting non-serializable types."""
    if isinstance(val, datetime.datetime):
        return val.isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    return val


class KafkaWriter:
    """Produces JSON messages to a Kafka topic."""

    def __init__(self, bootstrap_servers: str, topic: str):
        if not _KAFKA_AVAILABLE:
            raise RuntimeError(
                "kafka-python-ng is not installed. "
                "Install it with: pip install kafka-python-ng"
            )
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer = None
        self._ensure_topic()

    def _ensure_topic(self):
        """Create the topic if it doesn't already exist."""
        try:
            admin = KafkaAdminClient(bootstrap_servers=self._bootstrap_servers)
            topic = NewTopic(name=self._topic, num_partitions=1, replication_factor=1)
            admin.create_topics([topic])
            print(f"[kafka] Created topic '{self._topic}'.")
        except TopicAlreadyExistsError:
            pass
        except Exception as exc:
            print(f"[kafka] Topic creation skipped: {exc}")
        finally:
            try:
                admin.close()
            except Exception:
                pass

    def _get_producer(self) -> "KafkaProducer":
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        return self._producer

    def write_batch(self, rows: list, columns: list) -> int:
        """Serialize each row as JSON and produce to the topic.

        Returns the number of messages produced.
        """
        if not rows:
            return 0

        producer = self._get_producer()
        for row in rows:
            record = {col["name"]: _serialize_value(row.get(col["name"])) for col in columns}
            producer.send(self._topic, record)
        producer.flush()
        return len(rows)


# ---------------------------------------------------------------------------
# Module-level write_batch — matches the generic writer interface used by
# _get_writer() in generate.py for compatibility. Reads env vars directly.
# ---------------------------------------------------------------------------

def write_batch(
    rows: list,
    columns: list,
    partition_cfg,
    s3_client,
    bucket: str,
) -> str:
    """Generic writer interface adapter for KafkaWriter.

    Ignores partition_cfg, s3_client, and bucket. Reads
    KAFKA_BOOTSTRAP_SERVERS and KAFKA_TOPIC from the environment.
    Returns a pseudo-key of the form 'kafka/<topic>'.
    """
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.environ.get("KAFKA_TOPIC", "data-generator")
    writer = KafkaWriter(bootstrap_servers=bootstrap_servers, topic=topic)
    writer.write_batch(rows, columns)
    return f"kafka/{topic}"
