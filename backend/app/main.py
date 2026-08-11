import asyncio
import json
import re
import uuid
from collections.abc import Generator
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import inspect, text, func, select
from sqlalchemy.orm import Session
from .config import get_settings
from .database import Base, engine, get_db
from . import models, schemas
from .services.context import build_chapter_context, build_story_context
from .services.llm import DeepSeekProvider, parse_json_response
from .services.runs import run_stream
from .services.llm import OpenAICompatibleProvider
from .services.model_configs import current_user_id, decrypt_key, encrypt_key, mark_test, owned_config_or_404, read_config, resolve_model_config, safe_url_label, validate_base_url

Base.metadata.create_all(bind=engine)

def run_lightweight_migrations():
    """Keep local SQLite projects compatible without requiring a migration tool for this MVP."""
    inspector = inspect(engine)
    if "characters" not in inspector.get_table_names(): return
    existing = {column["name"] for column in inspector.get_columns("characters")}
    additions = {"appearance": "TEXT DEFAULT ''", "is_main_character": "BOOLEAN DEFAULT 0", "importance": "INTEGER DEFAULT 3", "current_location": "VARCHAR(200) DEFAULT ''", "current_goal": "TEXT DEFAULT ''", "current_emotion_or_state": "TEXT DEFAULT ''", "arc_or_growth": "TEXT DEFAULT ''", "status": "VARCHAR(20) DEFAULT 'draft'"}
    with engine.begin() as conn:
        for name, definition in additions.items():
            if name not in existing: conn.execute(text(f"ALTER TABLE characters ADD COLUMN {name} {definition}"))
        table_additions = {
            "novels": {"default_writing_model_config_id":"VARCHAR(36)","default_outline_model_config_id":"VARCHAR(36)","default_review_model_config_id":"VARCHAR(36)","writing_temperature_override":"FLOAT","outline_temperature_override":"FLOAT","review_temperature_override":"FLOAT"},
            "chapters": {"memory_stale": "BOOLEAN DEFAULT 0"},
            "chapter_summaries": {"is_stale": "BOOLEAN DEFAULT 0"},
            "timeline_events": {"is_stale": "BOOLEAN DEFAULT 0"},
            "agent_runs": {"model_config_id":"VARCHAR(36)","provider_type":"VARCHAR(50) DEFAULT 'deepseek'","api_base_url_label":"VARCHAR(255) DEFAULT ''","temperature":"FLOAT DEFAULT 0.7","max_output_tokens":"INTEGER"},
        }
        existing_tables=set(inspector.get_table_names())
        for table, columns in table_additions.items():
            if table not in existing_tables: continue
            have={column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in have: conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
run_lightweight_migrations()
app = FastAPI(title="NovelWriter API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def novel_or_404(novel_id: int, db: Session) -> models.Novel:
    item = db.get(models.Novel, novel_id)
    if not item: raise HTTPException(404, "小说不存在")
    return item

def scoped_or_404(model, novel_id: int, item_id: int, db: Session):
    item = db.get(model, item_id)
    if not item or item.novel_id != novel_id: raise HTTPException(404, "资源不存在，或不属于当前小说")
    return item

def update_entity(item, values: dict):
    for key, value in values.items():
        if value is not None: setattr(item, key, value)

def word_count(text: str) -> int: return len("".join(text.split()))

def normalize_memory_extraction(data: dict, chapter: models.Chapter) -> dict:
    """Keep incomplete model JSON useful as editable memory, never as confirmed canon."""
    normalized = dict(data)
    key_events = normalized.get("key_events") if isinstance(normalized.get("key_events"), list) else []
    key_events = [str(item).strip() for item in key_events if str(item).strip()]

    timelines: list[dict] = []
    for item in normalized.get("timeline_events") if isinstance(normalized.get("timeline_events"), list) else []:
        if isinstance(item, dict) and str(item.get("content", "")).strip():
            timelines.append({key: str(item.get(key, "")).strip() for key in ("time_description", "location", "content", "participants")})
        elif str(item).strip():
            timelines.append({"time_description": f"第{chapter.sequence}章", "location": "待确定", "content": str(item).strip(), "participants": ""})

    facts: list[dict] = []
    for item in normalized.get("facts") if isinstance(normalized.get("facts"), list) else []:
        if isinstance(item, dict) and str(item.get("content", "")).strip():
            facts.append({"fact_type": str(item.get("fact_type", "plot")).strip() or "plot", "content": str(item["content"]).strip()})
        elif str(item).strip():
            facts.append({"fact_type": "plot", "content": str(item).strip()})

    warnings = normalized.get("extraction_warnings") if isinstance(normalized.get("extraction_warnings"), list) else []
    if key_events and not timelines:
        for event in key_events[:8]:
            year = re.search(r"(?:19|20)\d{2}(?:年)?", event)
            timelines.append({"time_description": year.group(0) if year else f"第{chapter.sequence}章", "location": "待确定", "content": event, "participants": ""})
        warnings.append("模型未返回时间线，系统已依据关键事件生成可编辑的时间线草稿。")
    if key_events and not facts:
        facts = [{"fact_type": "plot", "content": event} for event in key_events[:8]]
        warnings.append("模型未返回事实，系统已依据关键事件生成可编辑的剧情事实草稿。")
    normalized["key_events"] = key_events
    normalized["timeline_events"] = timelines
    normalized["facts"] = facts
    normalized["extraction_warnings"] = warnings
    return normalized

def save_outline_snapshot(db: Session, novel: models.Novel, reason: str):
    if novel.master_outline:
        db.add(models.OutlineRevision(novel_id=novel.id, content=novel.master_outline, reason=reason))


@app.get("/health")
def health(): return {"ok": True}

@app.get("/api/model-configs", response_model=list[schemas.ModelConfigRead])
def list_model_configs(x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    user_id=current_user_id(x_user_id)
    return [read_config(x) for x in db.scalars(select(models.ModelConfig).where(models.ModelConfig.user_id == user_id).order_by(models.ModelConfig.updated_at.desc())).all()]

@app.post("/api/model-configs", response_model=schemas.ModelConfigRead, status_code=201)
def create_model_config(data: schemas.ModelConfigCreate, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    user_id=current_user_id(x_user_id); base=validate_base_url(data.api_base_url)
    if data.is_default: db.query(models.ModelConfig).filter_by(user_id=user_id, is_default=True).update({"is_default":False})
    item=models.ModelConfig(id=str(uuid.uuid4()),user_id=user_id,display_name=data.display_name,provider_type=data.provider_type,api_base_url=base,api_key_encrypted=encrypt_key(data.api_key),model_id=data.model_id,default_temperature=data.default_temperature,max_output_tokens=data.max_output_tokens,enabled=data.enabled,is_default=data.is_default,supported_tasks=data.supported_tasks)
    db.add(item);db.commit();db.refresh(item);return read_config(item)

@app.patch("/api/model-configs/{config_id}", response_model=schemas.ModelConfigRead)
def update_model_config(config_id: str, data: schemas.ModelConfigUpdate, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    user_id=current_user_id(x_user_id); item=owned_config_or_404(db,config_id,user_id); values=data.model_dump(exclude_unset=True)
    if "api_base_url" in values: values["api_base_url"]=validate_base_url(values["api_base_url"])
    if "api_key" in values: values["api_key_encrypted"]=encrypt_key(values.pop("api_key"))
    if values.get("is_default"):
        db.query(models.ModelConfig).filter_by(user_id=user_id,is_default=True).update({"is_default":False})
    update_entity(item,values);db.commit();db.refresh(item);return read_config(item)

@app.delete("/api/model-configs/{config_id}")
def delete_model_config(config_id: str, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    item=owned_config_or_404(db,config_id,current_user_id(x_user_id));db.delete(item);db.commit();return {"deleted":config_id}

@app.post("/api/model-configs/{config_id}/test", response_model=schemas.ModelConfigRead)
async def test_model_config(config_id: str, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    item=owned_config_or_404(db,config_id,current_user_id(x_user_id))
    try:
        provider=OpenAICompatibleProvider(item.api_base_url,decrypt_key(item.api_key_encrypted));await provider.generate([{"role":"user","content":"Reply with OK."}],item.model_id,0,max_output_tokens=8)
        mark_test(item,"success","连接成功")
    except Exception:
        mark_test(item,"failed","模型连接失败，请检查 API URL、模型名称或 Key")
    db.commit();db.refresh(item);return read_config(item)


def run_or_404(run_id: str, db: Session) -> models.AgentRun:
    item = db.get(models.AgentRun, run_id)
    if not item: raise HTTPException(404, "运行记录不存在")
    return item

@app.get("/api/novels/{novel_id}/agent-runs", response_model=list[schemas.AgentRunRead])
def list_agent_runs(novel_id: int, chapter_id: int | None = None, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db)
    statement = select(models.AgentRun).where(models.AgentRun.novel_id == novel_id)
    if chapter_id is not None: statement = statement.where(models.AgentRun.chapter_id == chapter_id)
    return db.scalars(statement.order_by(models.AgentRun.updated_at.desc()).limit(50)).all()

@app.get("/api/agent-runs/{run_id}", response_model=schemas.AgentRunRead)
def get_agent_run(run_id: str, db: Session = Depends(get_db)): return run_or_404(run_id, db)

@app.get("/api/agent-runs/{run_id}/events", response_model=list[schemas.AgentRunEventRead])
def get_agent_run_events(run_id: str, db: Session = Depends(get_db)):
    run_or_404(run_id, db); return db.scalars(select(models.AgentRunEvent).where(models.AgentRunEvent.run_id == run_id).order_by(models.AgentRunEvent.sequence)).all()

@app.post("/api/novels/{novel_id}/agent-runs/stream")
async def start_agent_run(novel_id: int, data: schemas.AgentRunCreate, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db)
    if data.chapter_id: scoped_or_404(models.Chapter, novel_id, data.chapter_id, db)
    supported = {"generate_outline", "improve_outline", "improve_outline_master", "improve_outline_batch", "plan_chapters", "derive_story_plan", "suggest_outline", "improve_chapter_outline", "generate_chapter", "extract_memory", "validate_chapter"}
    if data.task_type not in supported: raise HTTPException(422, "不支持的 Agent 任务类型")
    user_id=current_user_id(x_user_id)
    config=resolve_model_config(db,user_id,novel,data.task_type,data.model_config_id)
    group="writing" if data.task_type=="generate_chapter" else "outline" if data.task_type in {"generate_outline","improve_outline","improve_outline_master","improve_outline_batch","plan_chapters","derive_story_plan","suggest_outline","improve_chapter_outline"} else "review"
    override=getattr(novel,f"{group}_temperature_override")
    temperature=data.temperature if data.temperature is not None else (override if override is not None else (config.default_temperature if config else 0.7))
    max_tokens=data.max_output_tokens if data.max_output_tokens is not None else (config.max_output_tokens if config else None)
    provider=OpenAICompatibleProvider(config.api_base_url,decrypt_key(config.api_key_encrypted)) if config else DeepSeekProvider()
    run = models.AgentRun(id=str(uuid.uuid4()), novel_id=novel.id, chapter_id=data.chapter_id, task_type=data.task_type, input_snapshot=data.input, model_name=config.model_id if config else get_settings().deepseek_model, model_config_id=config.id if config else None, provider_type=config.provider_type if config else "deepseek", api_base_url_label=safe_url_label(config.api_base_url) if config else "deepseek", temperature=temperature, max_output_tokens=max_tokens, status="queued")
    db.add(run); db.commit(); db.refresh(run)
    return StreamingResponse(run_stream(db, novel, run, provider=provider), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})

@app.post("/api/agent-runs/{run_id}/cancel")
def cancel_agent_run(run_id: str, db: Session = Depends(get_db)):
    run = run_or_404(run_id, db)
    if run.status not in {"queued", "building_context", "running", "interrupted"}: raise HTTPException(409, "该运行当前不可停止")
    run.status = "cancelled"; db.commit(); record = models.AgentRunEvent(run_id=run.id, sequence=(db.scalar(select(func.max(models.AgentRunEvent.sequence)).where(models.AgentRunEvent.run_id == run.id)) or 0)+1, event_type="status", payload={"stage":"cancelled","message":"用户停止了运行，当前草稿已保留"}); db.add(record); db.commit(); return {"id":run.id,"status":run.status,"partial_output":run.partial_output}

@app.post("/api/agent-runs/{run_id}/resume/stream")
async def resume_agent_run(run_id: str, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    run = run_or_404(run_id, db); novel = novel_or_404(run.novel_id, db)
    if run.status not in {"interrupted", "cancelled", "failed", "paused"}: raise HTTPException(409, "仅中断、暂停、失败或取消的运行可恢复")
    if not run.partial_output and run.task_type == "generate_chapter": raise HTTPException(409, "没有可恢复的正文草稿，请重新从头生成")
    config=owned_config_or_404(db,run.model_config_id,current_user_id(x_user_id)) if run.model_config_id else None
    if config and not config.enabled: raise HTTPException(422,"原模型已停用，请选择其他模型后重新生成")
    provider=OpenAICompatibleProvider(config.api_base_url,decrypt_key(config.api_key_encrypted)) if config else DeepSeekProvider()
    run.status = "queued"; run.error_message = None; db.commit()
    return StreamingResponse(run_stream(db, novel, run, provider=provider, resume=True), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})

@app.get("/api/novels/{novel_id}/token-usage")
def token_usage(novel_id: int, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db)
    rows = db.scalars(select(models.TokenUsage).where(models.TokenUsage.novel_id == novel_id)).all()
    return {"runs": len(rows), "input_tokens_estimated": sum(x.input_tokens_estimated for x in rows), "output_tokens": sum(x.output_tokens_actual or 0 for x in rows), "total_tokens": sum(x.total_tokens or 0 for x in rows), "compressed_runs": sum(1 for x in rows if x.compressed)}

@app.get("/api/novels", response_model=list[schemas.NovelRead])
def list_novels(db: Session = Depends(get_db)):
    return db.scalars(select(models.Novel).order_by(models.Novel.updated_at.desc())).all()

@app.post("/api/novels", response_model=schemas.NovelRead, status_code=201)
def create_novel(data: schemas.NovelCreate, db: Session = Depends(get_db)):
    item = models.Novel(**data.model_dump(exclude_none=True)); db.add(item); db.commit(); db.refresh(item); return item

@app.get("/api/novels/{novel_id}", response_model=schemas.NovelRead)
def get_novel(novel_id: int, db: Session = Depends(get_db)): return novel_or_404(novel_id, db)

@app.patch("/api/novels/{novel_id}", response_model=schemas.NovelRead)
def update_novel(novel_id: int, data: schemas.NovelUpdate, x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    item = novel_or_404(novel_id, db); values = data.model_dump(exclude_unset=True)
    user_id=current_user_id(x_user_id)
    for field in ("default_writing_model_config_id","default_outline_model_config_id","default_review_model_config_id"):
        if values.get(field): owned_config_or_404(db,values[field],user_id)
    if "master_outline" in values and values["master_outline"] != item.master_outline: save_outline_snapshot(db, item, "manual_save")
    update_entity(item, values); db.commit(); db.refresh(item); return item

@app.delete("/api/novels/{novel_id}", status_code=204)
def delete_novel(novel_id: int, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db)
    run_ids = [x for x in db.scalars(select(models.AgentRun.id).where(models.AgentRun.novel_id == novel_id)).all()]
    if run_ids:
        db.query(models.AgentRunEvent).filter(models.AgentRunEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(models.ContextSnapshot).filter(models.ContextSnapshot.run_id.in_(run_ids)).delete(synchronize_session=False)
    for model in (models.TokenUsage, models.AgentRun, models.OutlineNode, models.ChapterSummary, models.TimelineEvent, models.CanonFact, models.Character, models.GenerationJob, models.OutlineRevision, models.Chapter): db.query(model).filter(model.novel_id == novel_id).delete()
    db.query(models.Novel).filter(models.Novel.id == novel_id).delete(); db.commit()

@app.get("/api/novels/{novel_id}/workspace")
def workspace(novel_id: int, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db)
    return {"novel": schemas.NovelRead.model_validate(novel), "chapters": [schemas.ChapterRead.model_validate(x) for x in db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel_id).order_by(models.Chapter.sequence)).all()], "outline_nodes": [schemas.OutlineRead.model_validate(x) for x in db.scalars(select(models.OutlineNode).where(models.OutlineNode.novel_id == novel_id).order_by(models.OutlineNode.sort_order)).all()], "characters": [schemas.CharacterRead.model_validate(x) for x in db.scalars(select(models.Character).where(models.Character.novel_id == novel_id)).all()], "timeline": [schemas.TimelineRead.model_validate(x) for x in db.scalars(select(models.TimelineEvent).where(models.TimelineEvent.novel_id == novel_id)).all()], "facts": [schemas.FactRead.model_validate(x) for x in db.scalars(select(models.CanonFact).where(models.CanonFact.novel_id == novel_id)).all()]}

@app.get("/api/novels/{novel_id}/outline-revisions", response_model=list[schemas.OutlineRevisionRead])
def outline_revisions(novel_id: int, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db)
    return db.scalars(select(models.OutlineRevision).where(models.OutlineRevision.novel_id == novel_id).order_by(models.OutlineRevision.created_at.desc()).limit(12)).all()

@app.post("/api/novels/{novel_id}/outline-revisions/{revision_id}/restore", response_model=schemas.NovelRead)
def restore_outline_revision(novel_id: int, revision_id: int, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db); revision = scoped_or_404(models.OutlineRevision, novel_id, revision_id, db)
    save_outline_snapshot(db, novel, "before_restore"); novel.master_outline = revision.content; db.commit(); db.refresh(novel); return novel

@app.delete("/api/novels/{novel_id}/outline-revisions/{revision_id}", status_code=204)
def delete_outline_revision(novel_id: int, revision_id: int, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db)
    revision = scoped_or_404(models.OutlineRevision, novel_id, revision_id, db)
    db.delete(revision); db.commit()


@app.get("/api/novels/{novel_id}/chapters", response_model=list[schemas.ChapterRead])
def chapters(novel_id: int, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db); return db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel_id).order_by(models.Chapter.sequence)).all()

def normalize_chapter_sequences(db: Session, novel_id: int):
    """Keep a novel's visible chapter numbers contiguous and deterministic."""
    chapters = db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel_id).order_by(models.Chapter.sequence, models.Chapter.id)).all()
    for sequence, chapter in enumerate(chapters, 1):
        chapter.sequence = sequence
    return chapters

def next_chapter_sequence(db: Session, novel_id: int) -> int:
    return (db.scalar(select(func.max(models.Chapter.sequence)).where(models.Chapter.novel_id == novel_id)) or 0) + 1

@app.post("/api/novels/{novel_id}/chapters", response_model=schemas.ChapterRead, status_code=201)
def create_chapter(novel_id: int, data: schemas.ChapterCreate, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db)
    requested = data.sequence if data.sequence > 0 else next_chapter_sequence(db, novel_id)
    if db.scalar(select(models.Chapter.id).where(models.Chapter.novel_id == novel_id, models.Chapter.sequence == requested)):
        requested = next_chapter_sequence(db, novel_id)
    item = models.Chapter(novel_id=novel_id, **{**data.model_dump(), "sequence": requested})
    item.actual_words = word_count(item.content); db.add(item); db.commit(); db.refresh(item); return item

@app.get("/api/novels/{novel_id}/chapters/{chapter_id}", response_model=schemas.ChapterRead)
def get_chapter(novel_id: int, chapter_id: int, db: Session = Depends(get_db)): return scoped_or_404(models.Chapter, novel_id, chapter_id, db)

@app.patch("/api/novels/{novel_id}/chapters/{chapter_id}", response_model=schemas.ChapterRead)
def update_chapter(novel_id: int, chapter_id: int, data: schemas.ChapterUpdate, db: Session = Depends(get_db)):
    item = scoped_or_404(models.Chapter, novel_id, chapter_id, db)
    values = data.model_dump(exclude_unset=True)
    content_changed = "content" in values and values["content"] != item.content
    was_confirmed = item.status == "confirmed"
    update_entity(item, values)
    if was_confirmed and content_changed:
        # Never silently erase confirmed canon.  Only generated drafts become stale
        # and can later be deliberately replaced after the user reviews a preview.
        item.status = "changed_pending_confirmation"
        item.memory_stale = True
        db.query(models.ChapterSummary).filter_by(novel_id=novel_id, chapter_id=chapter_id).update({"is_stale": True})
        db.query(models.TimelineEvent).filter_by(novel_id=novel_id, source_chapter_id=chapter_id, confirmed=False).update({"is_stale": True})
        db.query(models.CanonFact).filter_by(novel_id=novel_id, source_chapter_id=chapter_id, status="draft").update({"status": "obsolete"})
    item.actual_words = word_count(item.content)
    db.commit(); db.refresh(item); return item

@app.delete("/api/novels/{novel_id}/chapters/{chapter_id}")
def delete_chapter(novel_id: int, chapter_id: int, db: Session = Depends(get_db)):
    chapter = scoped_or_404(models.Chapter, novel_id, chapter_id, db)
    was_confirmed = chapter.status == "confirmed"
    db.query(models.OutlineNode).filter_by(novel_id=novel_id, chapter_id=chapter_id).update({"chapter_id": None})
    db.query(models.ChapterSummary).filter_by(novel_id=novel_id, chapter_id=chapter_id).delete()
    db.query(models.TimelineEvent).filter_by(novel_id=novel_id, source_chapter_id=chapter_id).delete()
    db.query(models.CanonFact).filter_by(novel_id=novel_id, source_chapter_id=chapter_id).delete()
    db.query(models.GenerationJob).filter_by(novel_id=novel_id, chapter_id=chapter_id).delete()
    run_ids = [x for x in db.scalars(select(models.AgentRun.id).where(models.AgentRun.novel_id == novel_id, models.AgentRun.chapter_id == chapter_id)).all()]
    if run_ids:
        db.query(models.AgentRunEvent).filter(models.AgentRunEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(models.ContextSnapshot).filter(models.ContextSnapshot.run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(models.TokenUsage).filter_by(novel_id=novel_id, chapter_id=chapter_id).delete()
    db.query(models.AgentRun).filter_by(novel_id=novel_id, chapter_id=chapter_id).delete()
    db.delete(chapter); db.flush()
    normalize_chapter_sequences(db, novel_id)
    db.commit(); return {"deleted": chapter_id, "was_confirmed": was_confirmed, "message": "章节及其直接关联的摘要、提取数据和 AI 任务已删除。建议重新校验后续章节。"}


def crud_routes(prefix, model, create_schema, update_schema, read_schema):
    @app.get(prefix, response_model=list[read_schema])
    def list_items(novel_id: int, db: Session = Depends(get_db)):
        novel_or_404(novel_id, db); return db.scalars(select(model).where(model.novel_id == novel_id)).all()
    @app.post(prefix, response_model=read_schema, status_code=201)
    def create_item(novel_id: int, data: create_schema, db: Session = Depends(get_db)):
        novel_or_404(novel_id, db)
        for chapter_field in ("source_chapter_id", "chapter_id"):
            if getattr(data, chapter_field, None): scoped_or_404(models.Chapter, novel_id, getattr(data, chapter_field), db)
        if model is models.OutlineNode and getattr(data, "parent_id", None): scoped_or_404(models.OutlineNode, novel_id, data.parent_id, db)
        item = model(novel_id=novel_id, **data.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
    @app.patch(prefix + "/{item_id}", response_model=read_schema)
    def update_item(novel_id: int, item_id: int, data: update_schema, db: Session = Depends(get_db)):
        item = scoped_or_404(model, novel_id, item_id, db)
        values = data.model_dump(exclude_unset=True)
        for chapter_field in ("source_chapter_id", "chapter_id"):
            if values.get(chapter_field): scoped_or_404(models.Chapter, novel_id, values[chapter_field], db)
        if model is models.OutlineNode and values.get("parent_id"): scoped_or_404(models.OutlineNode, novel_id, values["parent_id"], db)
        update_entity(item, values); db.commit(); db.refresh(item); return item
    @app.delete(prefix + "/{item_id}", status_code=204)
    def delete_item(novel_id: int, item_id: int, db: Session = Depends(get_db)):
        scoped_or_404(model, novel_id, item_id, db); db.query(model).filter_by(id=item_id, novel_id=novel_id).delete(); db.commit()

crud_routes("/api/novels/{novel_id}/characters", models.Character, schemas.CharacterCreate, schemas.CharacterUpdate, schemas.CharacterRead)
crud_routes("/api/novels/{novel_id}/timeline", models.TimelineEvent, schemas.TimelineCreate, schemas.TimelineUpdate, schemas.TimelineRead)
crud_routes("/api/novels/{novel_id}/facts", models.CanonFact, schemas.FactCreate, schemas.FactUpdate, schemas.FactRead)
crud_routes("/api/novels/{novel_id}/outline", models.OutlineNode, schemas.OutlineCreate, schemas.OutlineUpdate, schemas.OutlineRead)


def job(db, novel_id, job_type, chapter_id=None, params=None):
    item = models.GenerationJob(novel_id=novel_id, chapter_id=chapter_id, job_type=job_type, input_params=params or {}, model_name=get_settings().deepseek_model); db.add(item); db.commit(); db.refresh(item); return item

async def json_job(db, novel, job_type, prompt, chapter_id=None, params=None):
    item = job(db, novel.id, job_type, chapter_id, params)
    try:
        raw = await DeepSeekProvider().generate([{"role": "system", "content": "你是严谨的中文长篇小说创作助手。只输出合法 JSON，不要 markdown。"}, {"role": "user", "content": prompt}], get_settings().deepseek_model, response_format={"type": "json_object"})
        result = parse_json_response(raw); item.status = "completed"; item.result = result; db.commit(); return {"job_id": item.id, "result": result}
    except Exception as exc:
        item.status = "failed"; item.error_message = str(exc); db.commit(); raise HTTPException(502, str(exc))


@app.post("/api/novels/{novel_id}/ai/outline")
async def generate_outline(novel_id: int, data: schemas.GenerateOutlineRequest, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db)
    story_context = build_story_context(db, novel)
    prompt = f"{story_context}\n为《{novel.title}》生成可编辑总纲和章节规划。题材：{data.genre or novel.genre}；主旨：{data.theme or novel.theme}；目标字数：{data.target_words}；章节数：{data.chapter_count}。主要主角为最高优先级约束。返回 {{\"master_outline\":\"...\",\"chapters\":[{{\"sequence\":1,\"title\":\"...\",\"outline\":\"...\"}}]}}。"
    return await json_job(db, novel, "generate_outline", prompt, params=data.model_dump())

@app.post("/api/novels/{novel_id}/ai/improve-outline")
async def improve_outline(novel_id: int, data: schemas.ImproveOutlineRequest, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db)
    chapters = db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel_id).order_by(models.Chapter.sequence)).all()
    chapter_state = "\n".join(f"第{c.sequence}章《{c.title}》[{c.status}]：{c.outline or '无大纲'}；已有正文：{'是' if c.content.strip() else '否'}" for c in chapters)
    context = build_story_context(db, novel)
    prompt = f"""{context}
【当前完整大纲】{novel.master_outline or '暂无'}
【已有章节与锁定状态】\n{chapter_state or '暂无'}
【用户最新改进要求】{data.improvement_request}
请提出改进预览，绝不能直接覆盖数据库。已确认章节或已有正文的剧情是既成事实，默认仅优化后续草稿章节；若确实建议修改已确认章节，必须放入 warnings 并说明影响原因。返回 JSON：{{"change_summary":"...","reasoning_summary":"...","affected_chapters":[1],"warnings":["..."],"outline":{{"title":"...","content":"改进后的完整总纲","chapters":[{{"chapter_number":1,"title":"...","outline":"...","change_type":"modified|unchanged|new"}}]}}}}。"""
    return await json_job(db, novel, "improve_outline", prompt, params=data.model_dump())

@app.post("/api/novels/{novel_id}/ai/apply-outline-improvement")
def apply_outline_improvement(novel_id: int, data: schemas.ApplyOutlineImprovementRequest, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db)
    # A missing/empty `content` field is a common partial LLM response.  Never let
    # it erase a user's already-saved master outline when they apply chapter rows.
    incoming_outline = data.master_outline.strip() if isinstance(data.master_outline, str) else None
    if incoming_outline and incoming_outline != novel.master_outline:
        save_outline_snapshot(db, novel, "before_ai_improvement"); novel.master_outline = incoming_outline
    applied, skipped = [], []
    selected = set(data.apply_chapter_numbers if data.apply_chapter_numbers is not None else [int(row.get("chapter_number", row.get("sequence", -1))) for row in data.chapters])
    normalize_chapter_sequences(db, novel_id)
    existing = {chapter.sequence: chapter for chapter in db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel_id)).all()}
    processed: set[int] = set()
    for row in data.chapters:
        number = int(row.get("chapter_number", row.get("sequence", 0)))
        if number <= 0 or number not in selected or number in processed: continue
        processed.add(number)
        chapter = existing.get(number)
        if chapter and chapter.status == "confirmed": skipped.append(number); continue
        if chapter:
            chapter.title = str(row.get("title", chapter.title)); chapter.outline = str(row.get("outline", chapter.outline)); applied.append(number)
        elif number > 0:
            chapter = models.Chapter(novel_id=novel_id, sequence=number, title=str(row.get("title", f"第{number}章")), outline=str(row.get("outline", "")), status="draft")
            db.add(chapter); existing[number] = chapter; applied.append(number)
    db.commit(); return {"applied_chapters": applied, "skipped_confirmed_chapters": skipped, "master_outline_preserved": bool(data.master_outline is not None and not incoming_outline)}

@app.post("/api/novels/{novel_id}/ai/apply-story-plan")
def apply_story_plan(novel_id: int, data: schemas.ApplyStoryPlanRequest, db: Session = Depends(get_db)):
    """Persist an outline-derived plan as editable drafts, never as canon."""
    novel_or_404(novel_id, db)
    events_created, arcs_created = 0, 0
    for raw in data.timeline_events:
        item = raw if isinstance(raw, dict) else {"content": str(raw)}
        content = str(item.get("content") or item.get("event") or "").strip()
        if not content:
            continue
        db.add(models.TimelineEvent(
            novel_id=novel_id,
            time_description=str(item.get("time_description") or item.get("chapter_range") or "章节规划").strip(),
            location=str(item.get("location") or "待确定").strip(),
            content=content,
            participants=str(item.get("participants") or "").strip(),
            confirmed=False,
        ))
        events_created += 1
    for raw in data.character_arcs:
        item = raw if isinstance(raw, dict) else {"arc": str(raw)}
        name = str(item.get("name") or item.get("character") or "未指明人物").strip()
        arc = str(item.get("arc") or item.get("arc_or_growth") or item.get("content") or "").strip()
        turning_points = item.get("turning_points") or item.get("key_turning_points") or []
        if isinstance(turning_points, list):
            turns = "；".join(str(point).strip() for point in turning_points if str(point).strip())
        else:
            turns = str(turning_points).strip()
        if not arc:
            continue
        detail = f"{name}：{arc}" + (f"\n关键转折：{turns}" if turns else "")
        db.add(models.CanonFact(novel_id=novel_id, fact_type="character_arc", content=detail, status="draft"))
        arcs_created += 1
    db.commit()
    return {"timeline_events_created": events_created, "character_arcs_created": arcs_created, "message": "已保存为草稿；确认后才会作为后续创作的强约束。"}

@app.post("/api/novels/{novel_id}/ai/plan-chapters")
async def plan_chapters(novel_id: int, data: schemas.PlanChaptersRequest, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db)
    prompt = (f"基于小说总纲生成 {data.chapter_count} 个章节的可编辑规划，不直接写入数据库。总纲：{novel.master_outline}。额外要求：{data.requirements}。每章约 {data.chapter_words} 字。"
              + '返回 {"chapters":[{"sequence":1,"title":"...","outline":"...","target_words":' + str(data.chapter_words) + '}]}。')
    return await json_job(db, novel, "plan_chapters", prompt, params=data.model_dump())

@app.post("/api/novels/{novel_id}/ai/apply-plan", response_model=list[schemas.ChapterRead])
def apply_plan(novel_id: int, payload: dict, db: Session = Depends(get_db)):
    novel_or_404(novel_id, db); rows = payload.get("chapters", [])
    if not isinstance(rows, list): raise HTTPException(422, "chapters 必须是数组")
    normalize_chapter_sequences(db, novel_id)
    existing = {chapter.sequence: chapter for chapter in db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel_id)).all()}
    changed, seen = [], set()
    for fallback, row in enumerate(rows, 1):
        number = int(row.get("sequence", fallback) or fallback)
        if number <= 0 or number in seen: continue
        seen.add(number)
        item = existing.get(number)
        if item and item.status == "confirmed": continue
        if item:
            item.title = str(row.get("title", item.title)); item.outline = str(row.get("outline", item.outline)); item.target_words = row.get("target_words", item.target_words)
        else:
            item = models.Chapter(novel_id=novel_id, sequence=number, title=str(row.get("title", "未命名章节")), outline=str(row.get("outline", "")), target_words=row.get("target_words"), status="draft")
            db.add(item); existing[number] = item
        changed.append(item)
    db.commit()
    for item in changed: db.refresh(item)
    return changed

@app.post("/api/novels/{novel_id}/chapters/{chapter_id}/ai/suggest-outline")
async def suggest_outline(novel_id: int, chapter_id: int, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db); chapter = scoped_or_404(models.Chapter, novel_id, chapter_id, db)
    context = build_chapter_context(db, novel, chapter)
    return await json_job(db, novel, "suggest_outline", f"{context}\n为第{chapter.sequence}章提出一个可编辑的章节大纲。返回 {{\"title\":\"...\",\"outline\":\"...\"}}。", chapter.id)

@app.post("/api/novels/{novel_id}/chapters/{chapter_id}/ai/improve-outline")
async def improve_chapter_outline(novel_id: int, chapter_id: int, data: schemas.ImproveChapterOutlineRequest, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db); chapter = scoped_or_404(models.Chapter, novel_id, chapter_id, db)
    context = build_chapter_context(db, novel, chapter)
    prompt = f"""{context}
【当前章节】第{chapter.sequence}章《{chapter.title}》\n现有大纲：{chapter.outline}\n已有正文：{chapter.content[-2000:] or '无'}
【改进要求】{data.improvement_request}
返回预览 JSON，不能修改数据库：{{"change_summary":"...","reasoning_summary":"...","warnings":["..."],"title":"...","outline":"改进后的章节大纲"}}。若本章已确认或已有正文，只建议与既成剧情兼容的调整，并在 warnings 说明。"""
    return await json_job(db, novel, "improve_chapter_outline", prompt, chapter.id, data.model_dump())

@app.post("/api/novels/{novel_id}/chapters/{chapter_id}/ai/generate")
async def stream_chapter(novel_id: int, chapter_id: int, data: schemas.GenerateChapterRequest, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db); chapter = scoped_or_404(models.Chapter, novel_id, chapter_id, db); item = job(db, novel_id, "generate_chapter", chapter_id, data.model_dump())
    if not chapter.outline.strip():
        item.status = "failed"; item.error_message = "章节大纲为空，请先生成或填写建议大纲。"; db.commit(); raise HTTPException(422, item.error_message)
    context = build_chapter_context(db, novel, chapter, include_writing_style=True)
    prompt = f"{context}\n【当前章节】第{chapter.sequence}章《{chapter.title}》\n章节大纲：{chapter.outline}\n写作要求：{chapter.writing_requirements}\n补充文风：{data.style_hint}\n目标字数：{data.target_words or chapter.target_words or 2500}\n请直接输出完整章节正文，不写前言、标题或解释。"
    async def event_stream():
        chunks = []
        try:
            async for delta in DeepSeekProvider().stream([{"role":"system","content":"你是一位擅长连载长篇小说的中文作家，严格遵循确认设定。"}, {"role":"user","content":prompt}], get_settings().deepseek_model):
                chunks.append(delta); yield f"data: {json.dumps({'type':'delta','text':delta}, ensure_ascii=False)}\n\n"
            item.status = "completed"; item.result = {"preview_length": len(''.join(chunks))}; db.commit(); yield f"data: {json.dumps({'type':'done','job_id':item.id}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            item.status = "failed"; item.error_message = str(exc); db.commit(); yield f"data: {json.dumps({'type':'error','message':str(exc)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})

@app.post("/api/novels/{novel_id}/chapters/{chapter_id}/ai/validate", response_model=schemas.ValidationResult)
async def validate_chapter(novel_id: int, chapter_id: int, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db); chapter = scoped_or_404(models.Chapter, novel_id, chapter_id, db); context = build_chapter_context(db, novel, chapter)
    response = await json_job(db, novel, "validate_chapter", f"{context}\n【待校验章节】大纲：{chapter.outline}\n正文：{chapter.content}\n检查人物地点、状态、关系、时间线、已确认设定及是否偏离大纲。不得改写正文。返回 {{\"passed\":true/false,\"issues\":[{{\"type\":\"timeline_conflict\",\"severity\":\"high|medium|low\",\"description\":\"...\",\"suggestion\":\"...\"}}]}}。", chapter.id)
    return response["result"]

@app.post("/api/novels/{novel_id}/chapters/{chapter_id}/confirm")
async def confirm_chapter(novel_id: int, chapter_id: int, payload: dict | None = None, db: Session = Depends(get_db)):
    novel = novel_or_404(novel_id, db); chapter = scoped_or_404(models.Chapter, novel_id, chapter_id, db)
    prompt = f"提取以下章节的结构化记忆，供用户确认后成为设定。章节：{chapter.content}\n返回 {{\"summary\":\"...\",\"key_events\":[\"...\"],\"foreshadowing\":[\"...\"],\"unresolved_conflicts\":[\"...\"],\"timeline_events\":[{{\"time_description\":\"\",\"location\":\"\",\"content\":\"\",\"participants\":\"\"}}],\"facts\":[{{\"fact_type\":\"character_state|relationship|world|plot\",\"content\":\"...\"}}]}}。"
    if payload and isinstance(payload.get("extracted"), dict):
        data = payload["extracted"]
    else:
        response = await json_job(db, novel, "extract_memory", prompt, chapter.id)
        data = response["result"]
    if not isinstance(data, dict): raise HTTPException(502, "记忆提取结果格式不正确，请重试")
    data = normalize_memory_extraction(data, chapter)
    def entries(value): return value if isinstance(value, list) else []
    def joined(value): return "\n".join(str(item) for item in entries(value))
    mode = str((payload or {}).get("mode", "apply"))
    if mode not in {"preview", "apply"}: raise HTTPException(422, "不支持的记忆确认模式")

    stale_timeline = db.scalars(select(models.TimelineEvent).where(
        models.TimelineEvent.novel_id == novel_id,
        models.TimelineEvent.source_chapter_id == chapter_id,
        models.TimelineEvent.confirmed.is_(False),
        models.TimelineEvent.is_stale.is_(True),
    )).all()
    stale_facts = db.scalars(select(models.CanonFact).where(
        models.CanonFact.novel_id == novel_id,
        models.CanonFact.source_chapter_id == chapter_id,
        models.CanonFact.status == "obsolete",
    )).all()
    confirmed_timeline_count = db.scalar(select(func.count()).select_from(models.TimelineEvent).where(
        models.TimelineEvent.novel_id == novel_id,
        models.TimelineEvent.source_chapter_id == chapter_id,
        models.TimelineEvent.confirmed.is_(True),
    )) or 0
    confirmed_fact_count = db.scalar(select(func.count()).select_from(models.CanonFact).where(
        models.CanonFact.novel_id == novel_id,
        models.CanonFact.source_chapter_id == chapter_id,
        models.CanonFact.status == "confirmed",
    )) or 0
    stale_summary = db.scalar(select(models.ChapterSummary).where(
        models.ChapterSummary.chapter_id == chapter_id,
        models.ChapterSummary.is_stale.is_(True),
    ))
    if mode == "preview":
        return {
            "chapter_id": chapter_id,
            "status": "memory_preview",
            "extracted": data,
            "old": {
                "summary": stale_summary.summary if stale_summary else "",
                "summary_stale": bool(stale_summary),
                "draft_timeline": [{"id": x.id, "content": x.content, "time_description": x.time_description, "location": x.location} for x in stale_timeline],
                "draft_facts": [{"id": x.id, "fact_type": x.fact_type, "content": x.content} for x in stale_facts],
                "confirmed_timeline_count": confirmed_timeline_count,
                "confirmed_fact_count": confirmed_fact_count,
            },
            "new": {
                "summary": str(data.get("summary", "")),
                "timeline_events": entries(data.get("timeline_events")),
                "facts": entries(data.get("facts")),
                "warnings": entries(data.get("extraction_warnings")),
                "timeline_count": len(entries(data.get("timeline_events"))),
                "fact_count": len(entries(data.get("facts"))),
            },
            "message": "旧草稿记忆已标为过期。已确认时间线和事实不会被自动删除。",
        }

    replace_stale_drafts = bool((payload or {}).get("replace_stale_drafts", True))
    if replace_stale_drafts:
        # Only stale drafts are safe to remove automatically. Confirmed memory is kept.
        db.query(models.TimelineEvent).filter(
            models.TimelineEvent.novel_id == novel_id,
            models.TimelineEvent.source_chapter_id == chapter_id,
            models.TimelineEvent.confirmed.is_(False),
            models.TimelineEvent.is_stale.is_(True),
        ).delete(synchronize_session=False)
        db.query(models.CanonFact).filter(
            models.CanonFact.novel_id == novel_id,
            models.CanonFact.source_chapter_id == chapter_id,
            models.CanonFact.status == "obsolete",
        ).delete(synchronize_session=False)
    # ChapterSummary is one-to-one with its chapter. Updating it in place avoids a
    # delete/insert ordering conflict with the database's unique chapter_id index.
    old = db.scalar(select(models.ChapterSummary).where(models.ChapterSummary.chapter_id == chapter_id))
    summary_values = {
        "summary": str(data.get("summary", "")),
        "key_events": joined(data.get("key_events")),
        "foreshadowing": joined(data.get("foreshadowing")),
        "unresolved_conflicts": joined(data.get("unresolved_conflicts")),
        "is_stale": False,
    }
    if old:
        update_entity(old, summary_values)
    else:
        db.add(models.ChapterSummary(novel_id=novel_id, chapter_id=chapter_id, **summary_values))
    for item in entries(data.get("timeline_events")):
        fields = {k: str(item.get(k, "")) for k in ("time_description","location","content","participants")} if isinstance(item, dict) else {"time_description":"", "location":"", "content":str(item), "participants":""}
        if fields["content"]: db.add(models.TimelineEvent(novel_id=novel_id, source_chapter_id=chapter_id, confirmed=False, **fields))
    for item in entries(data.get("facts")):
        fact_type, content = (str(item.get("fact_type", "plot")), str(item.get("content", ""))) if isinstance(item, dict) else ("plot", str(item))
        if content: db.add(models.CanonFact(novel_id=novel_id, source_chapter_id=chapter_id, status="draft", fact_type=fact_type, content=content))
    chapter.status = "confirmed"
    chapter.memory_stale = False
    db.commit(); return {
        "chapter_id": chapter_id,
        "status": "confirmed",
        "extracted": data,
        "replaced_stale_drafts": replace_stale_drafts,
        "confirmed_memory_preserved": {"timeline": confirmed_timeline_count, "facts": confirmed_fact_count},
    }
