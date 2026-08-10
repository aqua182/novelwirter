from sqlalchemy.orm import Session

from .. import models
from .base import AgentInstruction, NovelAgent
from .memory import NovelMemoryService


class WriterAgent(NovelAgent):
    """The only role that receives the novel's writing-style prompt."""

    name = "writer"
    task_types = frozenset({"generate_chapter"})

    def __init__(self, memory: NovelMemoryService):
        self.memory = memory

    def build_instruction(
        self, db: Session, novel: models.Novel, run: models.AgentRun
    ) -> AgentInstruction:
        chapter = db.get(models.Chapter, run.chapter_id) if run.chapter_id else None
        if not chapter or chapter.novel_id != novel.id:
            raise ValueError("章节不属于当前小说")
        if not chapter.outline.strip():
            raise ValueError("章节大纲为空，请先填写或生成建议大纲。")
        state = self.memory.for_run(db, novel, chapter, include_writing_style=True)
        prompt = (
            f"【当前章节】第{chapter.sequence}章《{chapter.title}》\n"
            f"章节大纲：{chapter.outline}\n"
            f"写作要求：{chapter.writing_requirements}\n"
            f"补充要求：{run.input_snapshot.get('style_hint', '')}\n"
            f"目标字数：{run.input_snapshot.get('target_words') or chapter.target_words or 2500}\n"
            "只推进本章大纲所覆盖的时间与事件：不能把近场上下文、历史摘要或未来章节的事件当作本章正在发生的内容；若信息不足，保守地写当前场景，不编造跨章转折。"
            "保持叙事语言与当前章节大纲/既有正文一致，人物行为、地点和时间须连贯。不要复述上一章正文，不跳到未来结局。"
            "输出必须是可读、连贯的正式小说段落：禁止断词、无意义连字符串、词语堆砌或占位文本。若无法在目标字数内保持质量，可自然收束并提前结束，绝不能为了凑字数降低可读性。"
            "请直接输出完整章节正文，不写前言或标题。"
        )
        return AgentInstruction(context=state.context, prompt=prompt, expects_json=False)
