#!/usr/bin/env python3
"""Analyse and fix template connection handles + orphaned Prometheus nodes.

Usage:
  python scripts/fix_template_connections.py --dry-run              # preview changes
  python scripts/fix_template_connections.py                        # apply changes
  python scripts/fix_template_connections.py --template dremio-lakehouse  # single template
  python scripts/fix_template_connections.py --fix-prometheus       # also add missing prometheus edges
  python scripts/fix_template_connections.py --dry-run --fix-prometheus
"""

import argparse
import glob
import os
import sys
import yaml


# Handle IDs derived from ComponentNode.tsx and ClusterNode.tsx
# ComponentNode: Left target (no id=null), Right source (no id=null), Bottom source (id="bottom-out")
# ClusterNode: Left target ("data-in"), Right source ("data-out"),
#              Top target ("data-in-top"/"cluster-in-top"), Bottom source/target ("cluster-out-bottom"/"cluster-in")

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo-templates")


def load_template(filepath):
    with open(filepath) as f:
        return yaml.safe_load(f)


def save_template(filepath, data):
    with open(filepath, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=200)


def is_cluster_node(node):
    """Check if a node is a cluster (has cluster-specific fields)."""
    return node.get("type") == "cluster" or node.get("cluster_config") is not None


def get_node_map(template):
    """Build a map of node_id -> node dict, including nodes inside clusters."""
    nodes = {}
    for n in template.get("nodes", []):
        nodes[n["id"]] = n
    for c in template.get("clusters", []):
        nodes[c["id"]] = c
    return nodes


def compute_handles(source_node, target_node, source_is_cluster, target_is_cluster):
    """Determine correct sourceHandle and targetHandle based on relative node positions."""
    sx = source_node.get("position", {}).get("x", 0)
    sy = source_node.get("position", {}).get("y", 0)
    tx = target_node.get("position", {}).get("x", 0)
    ty = target_node.get("position", {}).get("y", 0)

    dx = tx - sx  # positive = target is to the right
    dy = ty - sy  # positive = target is below

    if abs(dx) >= abs(dy):
        # Horizontal dominant — east/west
        if dx >= 0:
            # target is to the right
            source_handle = "data-out" if source_is_cluster else None
            target_handle = "data-in" if target_is_cluster else None
        else:
            # target is to the left
            source_handle = None  # no left source on component
            target_handle = None
    else:
        # Vertical dominant — north/south
        if dy >= 0:
            # target is below
            source_handle = "cluster-out-bottom" if source_is_cluster else "bottom-out"
            target_handle = "data-in-top" if target_is_cluster else None
        else:
            # target is above
            source_handle = "data-out" if source_is_cluster else None  # no top source
            target_handle = "cluster-in-top" if target_is_cluster else None

    return source_handle, target_handle


def analyse_template(template, filepath, dry_run=True):
    """Analyse and optionally fix edge handles in a template."""
    filename = os.path.basename(filepath)
    nodes = get_node_map(template)
    edges = template.get("edges", [])
    cluster_ids = {c["id"] for c in template.get("clusters", [])}

    fixes = []
    for edge in edges:
        source_id = edge.get("source")
        target_id = edge.get("target")

        if source_id not in nodes or target_id not in nodes:
            continue

        source_node = nodes[source_id]
        target_node = nodes[target_id]
        source_is_cluster = source_id in cluster_ids
        target_is_cluster = target_id in cluster_ids

        # Special case: cluster-to-cluster edges — preserve their handles
        conn_type = edge.get("connection_type", "")
        skip_types = ("bucket-replication", "site-replication", "tiering",
                       "cluster-replication", "cluster-site-replication", "replication")
        if conn_type in skip_types:
            # These use the blue cluster handles — don't override
            continue

        computed_src, computed_tgt = compute_handles(
            source_node, target_node, source_is_cluster, target_is_cluster
        )

        current_src = edge.get("source_handle")
        current_tgt = edge.get("target_handle")

        src_changed = current_src != computed_src
        tgt_changed = current_tgt != computed_tgt

        if src_changed or tgt_changed:
            fixes.append({
                "edge_id": edge.get("id", "?"),
                "source": source_id,
                "target": target_id,
                "old_src": current_src,
                "new_src": computed_src,
                "old_tgt": current_tgt,
                "new_tgt": computed_tgt,
                "src_changed": src_changed,
                "tgt_changed": tgt_changed,
            })
            if not dry_run:
                if computed_src is not None:
                    edge["source_handle"] = computed_src
                elif "source_handle" in edge:
                    del edge["source_handle"]

                if computed_tgt is not None:
                    edge["target_handle"] = computed_tgt
                elif "target_handle" in edge:
                    del edge["target_handle"]

    return fixes


def check_prometheus(template, filepath, dry_run=True):
    """Check if Prometheus nodes have metrics edges to MinIO, add if missing."""
    filename = os.path.basename(filepath)
    nodes = get_node_map(template)
    edges = template.get("edges", [])
    cluster_ids = {c["id"] for c in template.get("clusters", [])}

    # Find prometheus and minio nodes
    prom_nodes = [nid for nid, n in nodes.items() if n.get("component") in ("prometheus",)]
    minio_nodes = [nid for nid, n in nodes.items()
                   if n.get("component") in ("minio", "minio-aistore", "minio-aistor")]
    # Also check clusters (they have MinIO inside)
    minio_clusters = [cid for cid in cluster_ids]

    if not prom_nodes:
        return []

    added = []
    for prom_id in prom_nodes:
        # Check if any edge connects a minio/cluster to this prometheus
        has_metrics = False
        for edge in edges:
            if edge.get("target") == prom_id and edge.get("connection_type") in ("metrics", "metrics-query"):
                has_metrics = True
                break
            if edge.get("source") == prom_id and edge.get("connection_type") in ("metrics", "metrics-query"):
                has_metrics = True
                break

        if has_metrics:
            added.append({"prom_id": prom_id, "status": "linked"})
            continue

        # Find closest minio node to link
        minio_candidates = minio_nodes + minio_clusters
        if not minio_candidates:
            added.append({"prom_id": prom_id, "status": "no_minio"})
            continue

        # Pick the first minio node
        minio_id = minio_candidates[0]
        minio_node = nodes[minio_id]
        prom_node = nodes[prom_id]
        minio_is_cluster = minio_id in cluster_ids

        src_handle, tgt_handle = compute_handles(
            minio_node, prom_node, minio_is_cluster, False
        )

        # Build edge matching existing template patterns
        new_edge = {
            "id": f"e-{minio_id}-{prom_id}-metrics",
            "source": minio_id,
            "target": prom_id,
            "connection_type": "metrics",
            "network": "default",
            "auto_configure": True,
            "label": "Metrics",
        }
        if src_handle:
            new_edge["source_handle"] = src_handle
        if tgt_handle:
            new_edge["target_handle"] = tgt_handle

        added.append({
            "prom_id": prom_id,
            "minio_id": minio_id,
            "status": "added",
            "edge": new_edge,
        })

        if not dry_run:
            edges.append(new_edge)

    return added


def main():
    parser = argparse.ArgumentParser(description="Fix template connection handles")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--template", help="Fix a single template by ID")
    parser.add_argument("--fix-prometheus", action="store_true", help="Also add missing prometheus edges")
    args = parser.parse_args()

    label = "dry run" if args.dry_run else "APPLYING"
    print(f"fix_template_connections.py — {label}")
    print("=" * 60)

    template_files = sorted(glob.glob(os.path.join(TEMPLATES_DIR, "*.yaml")))
    if args.template:
        template_files = [f for f in template_files if args.template in os.path.basename(f)]
        if not template_files:
            print(f"No template matching '{args.template}'")
            sys.exit(1)

    total_templates_to_update = 0
    total_edges_to_fix = 0

    for filepath in template_files:
        filename = os.path.basename(filepath)
        template = load_template(filepath)
        if not template:
            continue

        fixes = analyse_template(template, filepath, dry_run=args.dry_run)

        if fixes:
            total_templates_to_update += 1
            total_edges_to_fix += len(fixes)
            print(f"\n{filename}")
            for fix in fixes:
                src_status = f"{fix['old_src']} → {fix['new_src']}    ← FIX" if fix["src_changed"] else f"{fix['old_src']}  (correct)"
                tgt_status = f"{fix['old_tgt']} → {fix['new_tgt']}    ← FIX" if fix["tgt_changed"] else f"{fix['old_tgt']}  (correct)"
                print(f"  edge: {fix['source']} → {fix['target']}")
                print(f"    sourceHandle: {src_status}")
                print(f"    targetHandle: {tgt_status}")
            print(f"  {len(fixes)} edge(s) to fix")
        else:
            pass  # No output for clean templates

        if not args.dry_run and fixes:
            save_template(filepath, template)

    print(f"\n{'=' * 60}")
    print(f"Templates to update: {total_templates_to_update}")
    print(f"Total edges to fix:  {total_edges_to_fix}")

    if args.dry_run and total_edges_to_fix > 0:
        print("Run without --dry-run to apply.")

    # Prometheus pass
    if args.fix_prometheus:
        print(f"\n{'=' * 60}")
        print("Prometheus orphan check")
        print("=" * 60)

        for filepath in template_files:
            filename = os.path.basename(filepath)
            template = load_template(filepath)
            if not template:
                continue

            results = check_prometheus(template, filepath, dry_run=args.dry_run)
            for r in results:
                if r["status"] == "linked":
                    print(f"  {filename:45s} — prometheus linked ✓")
                elif r["status"] == "no_minio":
                    print(f"  {filename:45s} — no MinIO node found")
                elif r["status"] == "added":
                    print(f"  {filename:45s} — prometheus NOT linked → adding metrics edge ({r['minio_id']} → {r['prom_id']})")

            if not args.dry_run:
                save_template(filepath, template)


if __name__ == "__main__":
    main()
