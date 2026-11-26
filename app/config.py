import os
from pathlib import Path
import yaml
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

class ServiceConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000

class DatabaseConfig(BaseModel):
    url: str = ""

class QueueConfig(BaseModel):
    redis_url: str = "redis://localhost:6379"
    queue_name: str = "ingest_tasks"

class IngestConfig(BaseModel):
    raw_dir: str = "./data/raw"
    processed_dir: str = "./data/processed"
    chunks_dir: str = "./data/chunks"
    allowed_extensions: list[str] = [".md"]

class SplitConfig(BaseModel):
    headers: list[str] = ["##", "###"]
    chunk_min_size: int = 200
    chunk_max_size: int = 600
    overlap_size: int = 80

class EmbedConfig(BaseModel):
    model_name: str = "BAAI/bge-small-zh-v1.5"
    device: str = "cpu"
    batch_size: int = 16
    prefix_template: str = "{source} | {chapter} | {content}"

class VectorStoreConfig(BaseModel):
    persist_dir: str = "./data/chroma_db"
    collection_name: str = "enterprise_kb"

class RetrieveConfig(BaseModel):
    top_k: int = 5
    distance_threshold: float = 0.55

class LLMConfig(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    temperature: float = 0.1
    max_tokens: int = 800

class Config(BaseModel):
    service: ServiceConfig = ServiceConfig()
    database: DatabaseConfig = DatabaseConfig()
    queue: QueueConfig = QueueConfig()
    ingest: IngestConfig = IngestConfig()
    split: SplitConfig = SplitConfig()
    embed: EmbedConfig = EmbedConfig()
    vector_store: VectorStoreConfig = VectorStoreConfig()
    retrieve: RetrieveConfig = RetrieveConfig()
    llm: LLMConfig = LLMConfig()


def load_config(path: str = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        return Config()
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    # 环境变量替换
    def _resolve_env(obj):
        if isinstance(obj, dict):
            return {k: _resolve_env(v) for k, v in obj.items()}
        elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            env_var = obj[2:-1]
            return os.environ.get(env_var, "")
        return obj

    raw = _resolve_env(raw)
    return Config(**raw)


config = load_config(BASE_DIR / "config.yaml")