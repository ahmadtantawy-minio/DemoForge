"""MinIO container image refs by edition."""

MINIO_CE_IMAGE = "quay.io/minio/minio:latest"
MINIO_AISTOR_IMAGE = "quay.io/minio/aistor/minio:latest"
MINIO_EDGE_IMAGE = "quay.io/minio/aistor/minio:edge"


def minio_image_for_edition(edition: str) -> str:
    if edition == "aistor":
        return MINIO_AISTOR_IMAGE
    if edition == "aistor-edge":
        return MINIO_EDGE_IMAGE
    return MINIO_CE_IMAGE
