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
            "请直接输出完整章节正文，不写前言或标题。"
        )
        return AgentInstruction(context=state.context, prompt=prompt, expects_json=False)
