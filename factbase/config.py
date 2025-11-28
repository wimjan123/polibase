import os
from dataclasses import dataclass


@dataclass
class Config:
    host: str = os.getenv("FACTBASE_HOST", "0.0.0.0")
    port: int = int(os.getenv("FACTBASE_PORT", "5000"))
    out_dir: str = os.getenv("FACTBASE_OUT", "out")
    state_dir: str = os.getenv("FACTBASE_STATE", "state")
    logs_dir: str = os.getenv("FACTBASE_LOGS", "logs")
    user_agent: str = os.getenv(
        "FACTBASE_UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    rps: float = float(os.getenv("FACTBASE_RPS", "0.5"))
    concurrency: int = int(os.getenv("FACTBASE_CONCURRENCY", "2"))
    debug: bool = os.getenv("FACTBASE_DEBUG", "0") in ("1", "true", "True")
