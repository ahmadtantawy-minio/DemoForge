import os


class Settings:
    minio_endpoint_g35: str = os.getenv("MINIO_ENDPOINT_G35", "")
    minio_endpoint_g4: str = os.getenv("MINIO_ENDPOINT_G4", "")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")

    kv_bucket_hot: str = os.getenv("KV_BUCKET_HOT", "kv-cache-hot")
    kv_bucket_warm: str = os.getenv("KV_BUCKET_WARM", "kv-cache-warm")
    kv_bucket_cold: str = os.getenv("KV_BUCKET_COLD", "kv-cache-cold")

    # Number of GPUs in the simulation
    gpu_count: int = int(os.getenv("GPU_COUNT", "2"))

    # Per-GPU capacities (each GPU has its own G1/G2/G3)
    # Tuned so 100 sessions at 32K cascade through all tiers including G3.5 and G4
    g1_capacity_gb: float = float(os.getenv("G1_CAPACITY_GB", "3"))
    g2_capacity_gb: float = float(os.getenv("G2_CAPACITY_GB", "3"))
    g3_capacity_gb: float = float(os.getenv("G3_CAPACITY_GB", "4"))

    # Shared tiers across all GPUs
    g35_capacity_gb: float = float(os.getenv("G35_CAPACITY_GB", "10"))
    g4_capacity_gb: float = float(os.getenv("G4_CAPACITY_GB", "50"))

    sim_default_users: int = int(os.getenv("SIM_DEFAULT_USERS", "100"))
    sim_default_context: int = int(os.getenv("SIM_DEFAULT_CONTEXT", "32768"))
    sim_default_scenario: str = os.getenv("SIM_DEFAULT_SCENARIO", "file-g4")


settings = Settings()
