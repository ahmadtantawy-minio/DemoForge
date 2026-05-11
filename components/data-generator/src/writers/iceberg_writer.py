"""
iceberg_writer.py — Write batches to an Iceberg REST Catalog via pyiceberg.

This is a stub when pyiceberg is not installed. The iceberg writer is used
when DG_FORMAT=iceberg. It writes via pyiceberg to an AIStor Tables endpoint
or external Iceberg REST catalog.

Connection config (catalog_uri, warehouse, namespace) comes from:
  - DG_ICEBERG_CATALOG_URI env var
  - scenario YAML iceberg section (warehouse, namespace, table)
"""

import datetime
import io

try:
    import pyiceberg.catalog
    import pyiceberg.schema as iceberg_schema
    import pyiceberg.types as T
    import pyarrow as pa
    _PYICEBERG_AVAILABLE = True
except ImportError:
    _PYICEBERG_AVAILABLE = False


# PyArrow type mapping (reused from parquet_writer logic)
_PA_TYPES = {
    "string": None,  # resolved lazily
    "int32": None,
    "int64": None,
    "float32": None,
    "float64": None,
    "boolean": None,
    "timestamp": None,
}


def _get_pa_type(col_type: str):
    import pyarrow as pa
    mapping = {
        "string": pa.string(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "float32": pa.float32(),
        "float64": pa.float64(),
        "boolean": pa.bool_(),
        "timestamp": pa.timestamp("us"),
        "date": pa.date32(),
    }
    return mapping.get(col_type, pa.string())


def _coerce_row(row: dict, columns: list) -> dict:
    out = {}
    for col in columns:
        name = col["name"]
        val = row.get(name)
        col_type = col.get("type", "string")
        if col_type == "timestamp" and isinstance(val, datetime.datetime):
            out[name] = val
        elif col_type in ("int32", "int64") and val is not None:
            out[name] = int(val)
        elif col_type in ("float32", "float64") and val is not None:
            out[name] = float(val)
        elif col_type == "boolean" and val is not None:
            out[name] = bool(val)
        else:
            out[name] = str(val) if val is not None else None
    return out


def _rows_to_arrow_table(rows: list, columns: list):
    import pyarrow as pa
    coerced = [_coerce_row(r, columns) for r in rows]
    arrays = {}
    schema_fields = []
    for col in columns:
        name = col["name"]
        pa_type = _get_pa_type(col.get("type", "string"))
        arrays[name] = pa.array([r[name] for r in coerced], type=pa_type)
        schema_fields.append(pa.field(name, pa_type))
    return pa.table(arrays, schema=pa.schema(schema_fields))


class IcebergWriter:
    """
    Wraps pyiceberg catalog interaction. Creates table if absent, appends rows.
    """

    def __init__(self, catalog_uri: str, warehouse: str, s3_endpoint: str,
                 access_key: str, secret_key: str, sigv4: bool = False):
        if not _PYICEBERG_AVAILABLE:
            raise RuntimeError(
                "pyiceberg is not installed. Install it with: pip install pyiceberg[s3fs]"
            )
        self._catalog_uri = catalog_uri
        self._warehouse = warehouse
        self._s3_endpoint = s3_endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._sigv4 = sigv4
        self._catalog = None

    def _get_catalog(self):
        if self._catalog is not None:
            return self._catalog
        from pyiceberg.catalog.rest import RestCatalog
        props = {
            "uri": self._catalog_uri,
            "warehouse": self._warehouse,
            "s3.endpoint": self._s3_endpoint,
            "s3.access-key-id": self._access_key,
            "s3.secret-access-key": self._secret_key,
            "s3.path-style-access": "true",
            "s3.region": "us-east-1",
            "py-io-impl": "pyiceberg.io.fsspec.FsspecFileIO",
        }
        if self._sigv4:
            import os as _os
            # SigV4 signing uses boto3's credential chain — set AWS env vars
            _os.environ.setdefault("AWS_ACCESS_KEY_ID", self._access_key)
            _os.environ.setdefault("AWS_SECRET_ACCESS_KEY", self._secret_key)
            _os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
            props["rest.sigv4-enabled"] = "true"
            props["rest.signing-region"] = "us-east-1"
            props["rest.signing-name"] = "s3tables"
        self._catalog = RestCatalog(name="demo", **props)
        return self._catalog

    def ensure_table(self, namespace: str, table_name: str, columns: list,
                     location: str = None):
        """Create the Iceberg table if it doesn't exist.

        Args:
            location: Optional S3 URI for table data (e.g. 's3://data-lake-2/orders/').
                      If set, Iceberg stores data files here instead of the default warehouse.
        """
        from pyiceberg.schema import Schema
        from pyiceberg.types import (
            StringType, LongType, IntegerType, FloatType, DoubleType,
            BooleanType, TimestampType, NestedField,
        )

        _iceberg_type_map = {
            "string": StringType(),
            "int32": IntegerType(),
            "int64": LongType(),
            "float32": FloatType(),
            "float64": DoubleType(),
            "boolean": BooleanType(),
            "timestamp": TimestampType(),
        }

        catalog = self._get_catalog()
        full_name = f"{namespace}.{table_name}"

        try:
            catalog.load_table(full_name)
            return  # already exists
        except Exception:
            pass

        # Build Iceberg schema
        fields = []
        for idx, col in enumerate(columns, start=1):
            iceberg_type = _iceberg_type_map.get(col.get("type", "string"), StringType())
            fields.append(
                NestedField(field_id=idx, name=col["name"], field_type=iceberg_type,
                            required=False)
            )

        schema = Schema(*fields)

        try:
            catalog.create_namespace(namespace)
        except Exception:
            pass  # namespace may already exist

        kwargs = {"identifier": full_name, "schema": schema}
        if location:
            kwargs["location"] = location
        catalog.create_table(**kwargs)

    def write_batch(self, rows: list, columns: list, namespace: str, table_name: str) -> int:
        """Append rows to the Iceberg table. Returns number of rows written.

        On failure (e.g. stale table reference after catalog metadata changed),
        invalidates the cached catalog and retries once with a fresh table load.
        """
        if not rows:
            return 0

        catalog = self._get_catalog()
        full_name = f"{namespace}.{table_name}"
        arrow_table = _rows_to_arrow_table(rows, columns)

        for attempt in range(2):
            try:
                table = catalog.load_table(full_name)
                table.append(arrow_table)
                return len(rows)
            except Exception as exc:
                if attempt == 0:
                    # Invalidate cached catalog and retry — table metadata may have changed.
                    self._catalog = None
                    catalog = self._get_catalog()
                else:
                    raise
        return len(rows)


def write_batch_stub(rows: list, columns: list, partition_cfg, s3_client, bucket: str) -> str:
    """
    Stub write_batch for iceberg_writer when called through the generic writer interface.
    Raises a clear error since iceberg writes require IcebergWriter class directly.
    """
    raise RuntimeError(
        "Iceberg writes require the IcebergWriter class directly. "
        "Use DG_FORMAT=parquet, json, or csv for generic S3 writes."
    )
