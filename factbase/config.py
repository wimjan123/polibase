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
        "FACTBASE_UA", "factbase-tool/0.1 (+https://rollcall.com/factbase)"
    )
    rps: float = float(os.getenv("FACTBASE_RPS", "1.0"))
    concurrency: int = int(os.getenv("FACTBASE_CONCURRENCY", "4"))
    debug: bool = os.getenv("FACTBASE_DEBUG", "0") in ("1", "true", "True")
