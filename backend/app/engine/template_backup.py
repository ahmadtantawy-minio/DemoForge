"""Template backup/restore for override tracking."""
import os
import json
import hashlib
import shutil
from datetime import datetime

BACKUP_DIR = os.environ.get("DEMOFORGE_BACKUP_DIR", "./data/template-backups")
MANIFEST_PATH = os.path.join(BACKUP_DIR, ".override-manifest.json")


def _load_manifest() -> dict:
    if os.path.isfile(MANIFEST_PATH):
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def _save_manifest(manifest: dict):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def compute_hash(filepath: str) -> str:
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def backup_original(template_id: str, original_path: str, source: str) -> dict:
    """Back up the original template before override. Returns backup info."""
    os.makedirs(os.path.join(BACKUP_DIR, template_id), exist_ok=True)

    manifest = _load_manifest()
    existing = manifest.get(template_id, {})
    version = existing.get("version", 0) + 1

    backup_filename = f"v{version}.yaml"
    backup_path = os.path.join(BACKUP_DIR, template_id, backup_filename)

    shutil.copy2(original_path, backup_path)
    original_hash = compute_hash(original_path)

    manifest[template_id] = {
        "original_hash": original_hash,
        "backup_path": backup_path,
        "backup_filename": backup_filename,
        "original_source": source,
        "overridden_at": datetime.utcnow().isoformat() + "Z",
        "version": version,
    }
    _save_manifest(manifest)

    return manifest[template_id]


def get_override_info(template_id: str) -> dict | None:
    """Get override info for a template, or None if not overridden."""
    manifest = _load_manifest()
    return manifest.get(template_id)


def remove_override(template_id: str) -> bool:
    """Remove override entry from manifest (called on revert)."""
    manifest = _load_manifest()
    if template_id in manifest:
        del manifest[template_id]
        _save_manifest(manifest)
        return True
    return False
