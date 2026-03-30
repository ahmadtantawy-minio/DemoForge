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


class BackupError(Exception):
    """Raised when a template backup cannot be safely completed."""
    pass


def backup_original(template_id: str, original_path: str, source: str) -> dict:
    """Back up the original template before override. Returns backup info.

    Raises BackupError if the backup cannot be created or verified.
    This is a safety-critical path — we never proceed with an override
    unless the original is safely backed up and verified.
    """
    # 1. Verify the original file is readable
    if not os.path.isfile(original_path):
        raise BackupError(f"Original template file not found: {original_path}")

    try:
        original_hash = compute_hash(original_path)
    except Exception as e:
        raise BackupError(f"Cannot read original template for hashing: {e}")

    # 2. Create backup directory
    backup_dir = os.path.join(BACKUP_DIR, template_id)
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except OSError as e:
        raise BackupError(f"Cannot create backup directory '{backup_dir}': {e}")

    # 3. Determine version
    manifest = _load_manifest()
    existing = manifest.get(template_id, {})
    version = existing.get("version", 0) + 1

    backup_filename = f"v{version}.yaml"
    backup_path = os.path.join(backup_dir, backup_filename)

    # 4. Copy the original
    try:
        shutil.copy2(original_path, backup_path)
    except Exception as e:
        raise BackupError(f"Failed to copy original to backup location: {e}")

    # 5. Verify the backup was written and matches the original
    if not os.path.isfile(backup_path):
        raise BackupError(f"Backup file was not created at '{backup_path}'")

    try:
        backup_hash = compute_hash(backup_path)
    except Exception as e:
        raise BackupError(f"Cannot verify backup file: {e}")

    if backup_hash != original_hash:
        # Remove the corrupt backup
        try:
            os.remove(backup_path)
        except OSError:
            pass
        raise BackupError(
            f"Backup verification failed — hash mismatch "
            f"(original={original_hash}, backup={backup_hash}). "
            f"Override aborted to prevent data loss."
        )

    # 6. Update manifest only after verified backup
    manifest[template_id] = {
        "original_hash": original_hash,
        "backup_path": backup_path,
        "backup_filename": backup_filename,
        "original_source": source,
        "overridden_at": datetime.utcnow().isoformat() + "Z",
        "version": version,
    }

    try:
        _save_manifest(manifest)
    except Exception as e:
        raise BackupError(f"Backup file saved but manifest update failed: {e}")

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
