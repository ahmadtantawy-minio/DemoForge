#!/usr/bin/env python3
"""DemoForge image pre-flight check. Validates all component images are cached."""
import argparse
import os
import subprocess
import sys
import yaml


def load_manifests(components_dir="components"):
    """Load all component manifests from the components directory."""
    manifests = []
    if not os.path.isdir(components_dir):
        print(f"Error: components directory '{components_dir}' not found")
        sys.exit(1)

    for name in sorted(os.listdir(components_dir)):
        manifest_path = os.path.join(components_dir, name, "manifest.yaml")
        if not os.path.isfile(manifest_path):
            continue
        with open(manifest_path) as f:
            data = yaml.safe_load(f)
        if data and data.get("image"):
            manifests.append({
                "component": name,
                "image": data["image"],
                "size_mb": data.get("image_size_mb"),
                "build_context": data.get("build_context", ""),
            })
    return manifests


def check_cached(image_ref):
    """Check if a Docker image is cached locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_ref],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="DemoForge image pre-flight check")
    parser.add_argument("--mode", choices=["se", "dev"], default="se",
                        help="se = check all images; dev = skip build_context images")
    parser.add_argument("--fail-on-missing", action="store_true",
                        help="Exit with code 1 if any images are missing")
    parser.add_argument("--pull-missing", action="store_true",
                        help="Pull all missing images")
    args = parser.parse_args()

    manifests = load_manifests()

    # In dev mode, skip images with build_context (they're built locally)
    if args.mode == "dev":
        manifests = [m for m in manifests if not m["build_context"]]

    print("DemoForge image pre-flight check")
    print("-" * 70)
    print(f" {'Component':<22} {'Image ref':<38} {'Status':<10} {'Size'}")
    print("-" * 70)

    cached_count = 0
    missing_count = 0
    total_missing_mb = 0
    missing_images = []

    for m in manifests:
        is_cached = check_cached(m["image"])
        size_str = f'{m["size_mb"]} MB' if m["size_mb"] else "?"

        if is_cached:
            status = "cached"
            status_icon = "+"
            cached_count += 1
        else:
            status = "missing"
            status_icon = "X"
            missing_count += 1
            missing_images.append(m["image"])
            if m["size_mb"]:
                total_missing_mb += m["size_mb"]

        print(f" {m['component']:<22} {m['image']:<38} {status_icon} {status:<8} {size_str}")

    print("-" * 70)
    total = cached_count + missing_count
    total_est = f"~{total_missing_mb / 1000:.1f} GB" if total_missing_mb else "0"
    print(f" {cached_count}/{total} images cached. {total_est} missing.")

    if missing_images:
        print(f"\nMissing images — run: make pull-missing")
        for img in missing_images:
            print(f"  {img}")

    if args.pull_missing and missing_images:
        print(f"\nPulling {len(missing_images)} missing images...")
        for img in missing_images:
            print(f"  Pulling {img}...")
            subprocess.run(["docker", "pull", img], check=False)
        print("Done.")

    if args.fail_on_missing and missing_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
