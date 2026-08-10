import asyncio
import json
import math
import re
import uuid
from datetime import datetime, timezone
from collections.abc import AsyncGenerator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from .. import models
from .context import build_chapter_context, build_story_context
from .llm import DeepSeekProvider, parse_json_response


def now(): return datetime.now(timezone.utc)
def estimate_tokens(text: str) -> int: return max(1, math.ceil(len(text) / 2))

def requested_chapter_count(payload: dict) -> int | None:
    """Read an explicit target, including a natural-language request such as “预计 100 章”."""
    value = payload.get("chapter_count")
    try:
        if value is not None and 1 <= int(value) <= 200: return int(value)
    except (TypeError, ValueError): pass
    text = str(payload.get("improvement_request", ""))
    match = re.search(r"(?:预计|预期|计划|规划|扩展为|总计|共)\s*(\d{1,3})\s*章", text)
    return int(match.group(1)) if match and 1 <= int(match.group(1)) <= 200 else None

def chapter_length_instruction(count: int | None) -> str:
    if not count: return "每章大纲应简洁、具体。"
    limit = 55 if count >= 80 else 85 if count >= 40 else 160
    return f"为避免长篇规划被输出长度截断，每章 outline 最多 {limit} 个汉字，只写关键转折、冲突与推进；后续可逐章展开。"

def annotate_outline_count(run: models.AgentRun, result: dict):
    expected = requested_chapter_count(run.input_snapshot)
    rows = result.get("outline", {}).get("chapters", []) if run.task_type == "improve_outline" else result.get("chapters", [])
    if not expected or not isinstance(rows, list): return
    actual = len(rows)
    if actual == expected: return
    warning = f"目标为 {expected} 章，但模型实际返回 {actual} 章。本次建议未补齐目标章节，请调整模型最大输出 Token 后重新生成。"
    if run.task_type == "improve_outline": result.setdefault("warnings", []).append(warning)
    else: result.setdefault("warnings", []).append(warning)

def record_event(db: Session, run: models.AgentRun, event_type: str, payload: dict):
    sequence = (db.scalar(select(models.AgentRunEvent.sequence).where(models.AgentRunEvent.run_id == run.id).order_by(models.AgentRunEvent.sequence.desc()).limit(1)) or 0) + 1
    db.add(models.AgentRunEvent(run_id=run.id, sequence=sequence, event_type=event_type, payload=payload)); db.commit()

def event(run: models.AgentRun, event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'run_id': run.id, 'event_type': event_type, 'timestamp': now().isoformat(), 'data': data}, ensure_ascii=False)}\n\n"

def task_prompt(db: Session, novel: models.Novel, run: models.AgentRun) -> tuple[str, str, bool]:
    payload = run.input_snapshot; task = run.task_type
    chapter = db.get(models.Chapter, run.chapter_id) if run.chapter_id else None
    if chapter and chapter.novel_id != novel.id: raise ValueError("章节不属于当前小说")
    context = build_chapter_context(db, novel, chapter) if chapter else build_story_context(db, novel)
    if task == "generate_chapter":
        if not chapter or not chapter.outline.strip(): raise ValueError("章节大纲为空，请先填写或生成建议大纲。")
        return context, f"【当前章节】第{chapter.sequence}章《{chapter.title}》\n章节大纲：{chapter.outline}\n写作要求：{chapter.writing_requirements}\n补充要求：{payload.get('style_hint','')}\n目标字数：{payload.get('target_words') or chapter.target_words or 2500}\n请直接输出完整章节正文，不写前言或标题。", False
    if task == "suggest_outline":
        return context, f"为第{chapter.sequence}章提出可编辑章节大纲。返回 {{\"title\":\"...\",\"outline\":\"...\"}}。", True
    if task == "improve_chapter_outline":
        return context, f"第{chapter.sequence}章《{chapter.title}》现有大纲：{chapter.outline}\n用户改进要求：{payload.get('improvement_request','')}。不能直接覆盖数据库。返回 {{\"change_summary\":\"...\",\"reasoning_summary\":\"...\",\"warnings\":[\"...\"],\"title\":\"...\",\"outline\":\"...\"}}。", True
    if task == "generate_outline":
        count = requested_chapter_count(payload) or 12
        return context, f"为《{novel.title}》生成可编辑总纲和章节规划。题材：{payload.get('genre') or novel.genre}；主旨：{payload.get('theme') or novel.theme}；目标字数：{payload.get('target_words') or novel.target_words}；目标章节数：{count}；文风：{payload.get('style') or novel.default_style}。主要主角是最高优先级约束。必须返回恰好 {count} 个 chapters，sequence 从 1 连续到 {count}，不得宣称生成了未包含的章节。{chapter_length_instruction(count)} 返回 {{\"master_outline\":\"...\",\"chapters\":[{{\"sequence\":1,\"title\":\"...\",\"outline\":\"...\"}}]}}。", True
    if task == "improve_outline":
        chapters = db.scalars(select(models.Chapter).where(models.Chapter.novel_id == novel.id).order_by(models.Chapter.sequence)).all()
        known = "\n".join(f"第{c.sequence}章《{c.title}》[{c.status}]：{c.outline}；已有正文：{'是' if c.content else '否'}" for c in chapters)
        count = requested_chapter_count(payload)
        count_requirement = f"目标共 {count} 章：必须返回恰好 {count} 个章节，chapter_number 从 1 连续到 {count}，不得在说明中声称生成了未包含的章节。{chapter_length_instruction(count)}" if count else "章节数量以当前规划为准；不得在说明中声称生成了未包含的章节。"
        return context, f"当前总纲：{novel.master_outline}\n已有章节：{known}\n用户改进要求：{payload.get('improvement_request','')}。{count_requirement}\n已确认章节和已有正文是既成事实，默认只调整后续草稿章节。返回 {{\"change_summary\":\"...\",\"reasoning_summary\":\"...\",\"affected_chapters\":[1],\"warnings\":[\"...\"],\"outline\":{{\"content\":\"...\",\"chapters\":[{{\"chapter_number\":1,\"title\":\"...\",\"outline\":\"...\",\"change_type\":\"modified\"}}]}}}}。", True
    if task == "plan_chapters":
        return context, f"基于总纲规划 {payload.get('chapter_count',12)} 个可编辑章节。要求：{payload.get('requirements','')}；单章目标：{payload.get('chapter_words',3000)}。返回 {{\"chapters\":[{{\"sequence\":1,\"title\":\"...\",\"outline\":\"...\"}}]}}。", True
    if task == "extract_memory":
        return context, f"从第{chapter.sequence}章正文提取结构化记忆。正文：{chapter.content}\n返回 {{\"summary\":\"...\",\"key_events\":[\"...\"],\"foreshadowing\":[\"...\"],\"unresolved_conflicts\":[\"...\"],\"timeline_events\":[],\"facts\":[]}}。", True
    if task == "validate_chapter":
        return context, f"校验第{chapter.sequence}章。大纲：{chapter.outline}\n正文：{chapter.content}\n只返回问题，不改写正文。返回 {{\"passed\":true,\"issues\":[{{\"type\":\"timeline_conflict\",\"severity\":\"medium\",\"description\":\"...\",\"suggestion\":\"...\"}}]}}。", True
    raise ValueError(f"不支持的任务类型：{task}")

def snapshot_context(db: Session, novel: models.Novel, run: models.AgentRun, context: str, prompt: str) -> tuple[models.ContextSnapshot, dict]:
    settings = get_settings(); estimated = estimate_tokens(context + prompt); level = 0; compressed: list[str] = []; warnings: list[str] = []
    if estimated >= settings.context_token_budget * settings.context_warning_threshold:
        level = 1; warnings.append("上下文接近安全预算，优先保留已确认主角、设定和当前章节。")
        compressed.append("低优先级历史正文将以章节摘要代替")
    if estimated > settings.context_token_budget:
        level = 2; warnings.append("上下文超过预算，已压缩低优先级历史内容。")
        compressed.append("旧章节正文替换为剧情摘要")
    snapshot = models.ContextSnapshot(id=str(uuid.uuid4()), novel_id=novel.id, run_id=run.id, summary="本次运行的可恢复上下文快照", confirmed_canon_snapshot={"context_excerpt": context[:6000]}, character_state_snapshot={"included": "已确认主要主角及人物状态"}, timeline_snapshot={"included": "已确认时间线"}, unresolved_plot_snapshot={"included": "章节摘要、伏笔与未解冲突"}, recent_chapter_snapshot={"included": "最近两章内容或结尾片段"}, retrieval_snapshot={"included": "关键词相关历史摘要"}, estimated_tokens=estimated, compression_level=level)
    db.add(snapshot); run.context_snapshot_id = snapshot.id; db.commit()
    return snapshot, {"included_items": ["已确认主角设定", "已确认世界观与时间线", "当前章节要求", "最近两章内容", "相关历史摘要"], "compressed_items": compressed, "estimated_tokens": estimated, "token_budget": settings.context_token_budget, "warnings": warnings}

async def run_stream(db: Session, novel: models.Novel, run: models.AgentRun, provider=None, resume: bool = False) -> AsyncGenerator[str, None]:
    try:
        run.status = "building_context"; db.commit(); record_event(db, run, "status", {"stage":"building_context","message":"正在整理主要主角、时间线和最近章节内容"})
        yield event(run, "status", {"stage":"building_context","message":"正在整理主要主角、时间线和最近章节内容"})
        context, prompt, expects_json = task_prompt(db, novel, run)
        if resume and run.partial_output:
            prompt += f"\n【已生成文本】\n{run.partial_output}\n请从以上文本末尾自然续写，不要重复已有内容；若与已确认设定冲突，以已确认设定为准。"
        _, context_data = snapshot_context(db, novel, run, context, prompt)
        record_event(db, run, "context", context_data); yield event(run, "context", context_data)
        for warning in context_data["warnings"]: yield event(run, "warning", {"message": warning})
        run.status = "running"; db.commit(); record_event(db, run, "tool", {"message":"已读取小说设定、人物状态与相关记忆"}); yield event(run, "tool", {"message":"已读取小说设定、人物状态与相关记忆"})
        yield event(run, "status", {"stage":"running","message":"正在生成内容"})
        output = run.partial_output if resume else ""
        provider = provider or DeepSeekProvider()
        async for delta in provider.stream([{"role":"system","content":"你是严谨的中文小说创作助手。遵循已确认设定；只提供任务所要求的输出。"},{"role":"user","content":context + "\n" + prompt}], run.model_name, run.temperature, run.max_output_tokens):
            db.refresh(run)
            if run.status in {"cancelled", "paused"}:
                record_event(db, run, "status", {"stage":run.status,"message":"任务已由用户停止，草稿已保留"}); yield event(run,"done",{"status":run.status,"message":"已保留当前草稿"}); return
            output += delta
            yield event(run, "content_delta", {"field":"structured_output" if expects_json else "content","delta":delta})
            run.partial_output = output; db.commit()
        run.partial_output = output
        result = parse_json_response(output) if expects_json else {"content": output}
        if expects_json and run.task_type in {"generate_outline", "improve_outline", "plan_chapters"}: annotate_outline_count(run, result)
        usage = getattr(provider, "last_usage", None) or {}
        input_actual = usage.get("prompt_tokens")
        output_actual = usage.get("completion_tokens") or estimate_tokens(output)
        total_actual = usage.get("total_tokens") or ((input_actual or context_data["estimated_tokens"]) + output_actual)
        run.result = result; run.status = "completed"; run.completed_at = now(); db.add(models.TokenUsage(novel_id=novel.id, chapter_id=run.chapter_id, run_id=run.id, task_type=run.task_type, model_name=run.model_name, input_tokens_estimated=context_data["estimated_tokens"], input_tokens_actual=input_actual, context_budget=context_data["token_budget"], compressed=bool(context_data["compressed_items"]), compressed_token_savings=0, output_tokens_actual=output_actual, total_tokens=total_actual)); db.commit()
        record_event(db, run, "result", {"message":"AI 任务已完成"}); yield event(run, "result", result); yield event(run, "done", {"status":"completed"})
    except asyncio.CancelledError:
        run.status = "interrupted"; db.commit(); record_event(db, run, "status", {"stage":"interrupted","message":"连接中断，已保留可恢复草稿"}); raise
    except Exception as exc:
        run.status = "failed"; run.error_message = str(exc); db.commit(); record_event(db, run, "error", {"message":str(exc)}); yield event(run, "error", {"message":str(exc)}); yield event(run, "done", {"status":"failed"})
