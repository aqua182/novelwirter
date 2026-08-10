from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from ..models import Novel, Chapter, Character, TimelineEvent, CanonFact, ChapterSummary


def _compact(items: list[str], limit: int = 12) -> str:
    return "\n".join(f"- {x}" for x in items[:limit] if x)


def build_story_context(db: Session, novel: Novel) -> str:
    confirmed_characters = db.scalars(select(Character).where(Character.novel_id == novel.id, or_(Character.confirmed.is_(True), Character.status == "confirmed")).order_by(Character.is_main_character.desc(), Character.importance.desc())).all()
    confirmed_events = db.scalars(select(TimelineEvent).where(TimelineEvent.novel_id == novel.id, TimelineEvent.confirmed.is_(True))).all()
    confirmed_facts = db.scalars(select(CanonFact).where(CanonFact.novel_id == novel.id, CanonFact.status == "confirmed")).all()
    mains = [c for c in confirmed_characters if c.is_main_character]
    chars = _compact([f"{c.name}：设定：{c.profile}；外貌：{c.appearance}；目标：{c.current_goal or c.goal}；性格：{c.personality}；关系：{c.relationships}；当前位置：{c.current_location}；当前状态/情绪：{c.current_emotion_or_state or c.current_status}；成长弧：{c.arc_or_growth}" for c in mains], 8)
    others = _compact([f"{c.name}：{c.profile}；状态：{c.current_status}" for c in confirmed_characters if not c.is_main_character])
    events = _compact([f"{e.time_description} / {e.location}：{e.content}（{e.participants}）" for e in confirmed_events])
    facts = _compact([f"[{f.fact_type}] {f.content}" for f in confirmed_facts])
    return f"""【固定设定】
书名：{novel.title}
题材：{novel.genre or '未设定'}
主旨：{novel.theme or '未设定'}
默认文风：{novel.default_style or '未设定'}
总纲：{novel.master_outline or '未设定'}
【第一优先级：已确认主要主角（不得无依据改动核心设定）】\n{chars or '暂无'}
【第二优先级：其他已确认人物】\n{others or '暂无'}
【已确认时间线】\n{events or '暂无'}
【已确认世界观与剧情事实】\n{facts or '暂无'}"""


def build_chapter_context(db: Session, novel: Novel, chapter: Chapter) -> str:
    base = build_story_context(db, novel)
    previous = db.scalars(select(Chapter).where(Chapter.novel_id == novel.id, Chapter.sequence < chapter.sequence).order_by(Chapter.sequence.desc()).limit(2)).all()
    summaries = db.scalars(select(ChapterSummary).where(ChapterSummary.novel_id == novel.id).order_by(ChapterSummary.chapter_id.desc()).limit(8)).all()
    keywords = set((chapter.outline + " " + chapter.title).lower().split())
    memory = [s for s in summaries if keywords.intersection((s.summary + s.key_events + s.unresolved_conflicts).lower().split())] or summaries[:4]
    prior = _compact([f"第{x.sequence}章《{x.title}》结尾：{x.content[-1200:]}" for x in reversed(previous)])
    recall = _compact([f"第{s.chapter_id}章摘要：{s.summary}；伏笔：{s.foreshadowing}；未解冲突：{s.unresolved_conflicts}" for s in memory])
    return base + f"""
【近场上下文（最近两章）】\n{prior or '暂无'}
【相关历史记忆】\n{recall or '暂无'}"""
