from datetime import datetime, timezone
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import ModelConfig, Novel


def current_user_id(x_user_id: str | None = None) -> str:
    """Minimal local-development identity boundary. Replace with authenticated identity in production."""
    return (x_user_id or "local-user").strip()[:100] or "local-user"

def cipher() -> Fernet:
    key = get_settings().model_config_encryption_key
    if not key: raise HTTPException(503, "尚未配置 MODEL_CONFIG_ENCRYPTION_KEY，无法安全保存模型 API Key")
    try: return Fernet(key.encode())
    except (ValueError, TypeError): raise HTTPException(503, "MODEL_CONFIG_ENCRYPTION_KEY 无效，请使用 Fernet 密钥")

def encrypt_key(value: str) -> str: return cipher().encrypt(value.encode()).decode()
def decrypt_key(value: str) -> str:
    try: return cipher().decrypt(value.encode()).decode()
    except InvalidToken: raise HTTPException(500, "模型密钥无法解密，请重新保存该模型配置")

def validate_base_url(value: str) -> str:
    url = value.rstrip("/"); parsed = urlparse(url)
    local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https" and parsed.hostname: return url
    if local and get_settings().allow_local_model_urls: return url
    raise HTTPException(422, "API Base URL 必须是 https:// 地址；仅在显式开发配置下允许 http://localhost")

def masked_key(value: str) -> str:
    try: raw = decrypt_key(value)
    except HTTPException: return "已加密"
    return (raw[:3] + "-****" + raw[-4:]) if len(raw) > 7 else "****"

def read_config(item: ModelConfig) -> dict:
    return {"id":item.id,"display_name":item.display_name,"provider_type":item.provider_type,"api_base_url":item.api_base_url,"api_key_masked":masked_key(item.api_key_encrypted),"model_id":item.model_id,"default_temperature":item.default_temperature,"max_output_tokens":item.max_output_tokens,"enabled":item.enabled,"is_default":item.is_default,"supported_tasks":item.supported_tasks or [],"last_tested_at":item.last_tested_at,"last_test_status":item.last_test_status,"last_test_message":item.last_test_message,"created_at":item.created_at,"updated_at":item.updated_at}

def owned_config_or_404(db: Session, config_id: str, user_id: str) -> ModelConfig:
    item = db.get(ModelConfig, config_id)
    if not item or item.user_id != user_id: raise HTTPException(404, "模型配置不存在")
    return item

def resolve_model_config(db: Session, user_id: str, novel: Novel, task_type: str, requested_id: str | None):
    group = "writing" if task_type == "generate_chapter" else "outline" if task_type in {"generate_outline","improve_outline","improve_outline_batch","plan_chapters","derive_story_plan","suggest_outline","improve_chapter_outline"} else "review"
    novel_id = getattr(novel, f"default_{group}_model_config_id")
    if requested_id:
        item = owned_config_or_404(db, requested_id, user_id)
        if not item.enabled: raise HTTPException(422, "选择的模型已停用，请选择其他模型")
    else:
        item = db.get(ModelConfig, novel_id) if novel_id else None
        if not item or item.user_id != user_id or not item.enabled:
            item = db.scalar(select(ModelConfig).where(ModelConfig.user_id == user_id, ModelConfig.enabled.is_(True), ModelConfig.is_default.is_(True)))
    if not item: return None
    # Older local configurations may still carry a restrictive task list from the
    # previous UI.  Story-plan extraction is an outline operation, so honor an
    # existing outline permission instead of unexpectedly blocking this new flow.
    allowed_tasks = {task_type}
    if task_type in {"derive_story_plan", "improve_outline_batch"}: allowed_tasks.add("improve_outline")
    if item.supported_tasks and not allowed_tasks.intersection(item.supported_tasks): raise HTTPException(422, "该模型未启用当前任务")
    return item

def safe_url_label(url: str) -> str:
    parsed = urlparse(url); return f"{parsed.scheme}://{parsed.hostname or ''}"

def mark_test(item: ModelConfig, status: str, message: str):
    item.last_tested_at=datetime.now(timezone.utc); item.last_test_status=status; item.last_test_message=message[:300]
