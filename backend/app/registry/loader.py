"""Load component manifests from YAML files on disk."""
import os
import yaml
from ..models.component import ComponentManifest

_registry: dict[str, ComponentManifest] = {}

def load_registry(components_dir: str) -> dict[str, ComponentManifest]:
    """Scan components_dir for manifest.yaml files and parse them."""
    global _registry
    _registry = {}
    for entry in os.listdir(components_dir):
        manifest_path = os.path.join(components_dir, entry, "manifest.yaml")
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                raw = yaml.safe_load(f)
            manifest = ComponentManifest(**raw)
            _registry[manifest.id] = manifest
    # Backward compatibility: minio-aistore → minio
    if "minio" in _registry and "minio-aistore" not in _registry:
        _registry["minio-aistore"] = _registry["minio"]
    return _registry

def get_registry() -> dict[str, ComponentManifest]:
    return _registry

def get_component(component_id: str) -> ComponentManifest | None:
    return _registry.get(component_id)
