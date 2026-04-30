import os


def _node_ids(node_count: int) -> list[str]:
    n = max(1, int(node_count))
    return [f"node-{chr(ord('a') + i)}" for i in range(n)]


class Settings:
    minio_endpoint_g35: str = os.getenv("MINIO_ENDPOINT_G35", "")
    minio_endpoint_g4: str = os.getenv("MINIO_ENDPOINT_G4", "")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")

    kv_bucket_hot: str = os.getenv("KV_BUCKET_HOT", "kv-cache-hot")
    kv_bucket_warm: str = os.getenv("KV_BUCKET_WARM", "kv-cache-warm")
    kv_bucket_cold: str = os.getenv("KV_BUCKET_COLD", "kv-cache-cold")

    # Topology: NODE_COUNT × GPUS_PER_NODE (e.g. 2 DGX × 8 H100 = 16 GPUs).
    node_count: int = int(os.getenv("NODE_COUNT", "2"))
    gpus_per_node: int = int(os.getenv("GPUS_PER_NODE", "8"))
    replica_count: int = int(os.getenv("REPLICA_COUNT", "8"))
    gpu_count: int = int(os.getenv("GPU_COUNT", str(int(os.getenv("NODE_COUNT", "2")) * int(os.getenv("GPUS_PER_NODE", "8")))))

    @property
    def node_ids(self) -> list[str]:
        return _node_ids(self.node_count)

    # Per-GPU capacities — NVIDIA H100 SXM (2024–2026), Memory Budget spec (GB).
    # G1 HBM total; KV allocator uses g1_kv_capacity_gb (after FP8 weights + overhead).
    g1_hbm_total_gb: float = float(os.getenv("G1_HBM_TOTAL_GB", "80"))
    g1_weights_gb_per_gpu: float = float(os.getenv("G1_WEIGHTS_GB_PER_GPU", "35"))
    g1_overhead_gb_per_gpu: float = float(os.getenv("G1_OVERHEAD_GB_PER_GPU", "4"))
    # Per-GPU KV slice (TP=2 replica leg); allocator uses × gpus_per_node per logical node.
    g1_kv_capacity_gb: float = float(
        os.getenv(
            "G1_KV_CAPACITY_GB",
            str(
                float(os.getenv("G1_HBM_TOTAL_GB", "80"))
                - float(os.getenv("G1_WEIGHTS_GB_PER_GPU", "35"))
                - float(os.getenv("G1_OVERHEAD_GB_PER_GPU", "4"))
            ),
        )
    )
    g2_capacity_gb: float = float(os.getenv("G2_CAPACITY_GB", "480"))
    g3_capacity_gb: float = float(os.getenv("G3_CAPACITY_GB", "3600"))

    @property
    def g1_kv_capacity_per_node_gb(self) -> float:
        return self.g1_kv_capacity_gb * float(self.gpus_per_node)

    @property
    def g2_capacity_per_node_gb(self) -> float:
        return self.g2_capacity_gb * float(self.gpus_per_node)

    @property
    def g3_capacity_per_node_gb(self) -> float:
        return self.g3_capacity_gb * float(self.gpus_per_node)

    @property
    def g1_hbm_total_per_node_gb(self) -> float:
        return self.g1_hbm_total_gb * float(self.gpus_per_node)

    @property
    def g1_weights_per_node_gb(self) -> float:
        return self.g1_weights_gb_per_gpu * float(self.gpus_per_node)

    @property
    def g1_overhead_per_node_gb(self) -> float:
        return self.g1_overhead_gb_per_gpu * float(self.gpus_per_node)

    # Shared tiers across all GPUs (G3.5 warm / G4 cold archive), GB (decimal: 1 TB = 1000 GB).
    g35_capacity_gb: float = float(os.getenv("G35_CAPACITY_GB", "500000"))  # 500 TB
    g4_capacity_gb: float = float(os.getenv("G4_CAPACITY_GB", "1000000"))  # 1 PB

    sim_default_users: int = int(os.getenv("SIM_DEFAULT_USERS", "130"))
    sim_default_context: int = int(os.getenv("SIM_DEFAULT_CONTEXT", "65536"))
    sim_default_scenario: str = os.getenv("SIM_DEFAULT_SCENARIO", "file-g4")


settings = Settings()
