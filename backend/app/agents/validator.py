from sqlalchemy.orm import Session

from .. import models
from .base import AgentInstruction, NovelAgent
from .memory import NovelMemoryService


class ValidatorAgent(NovelAgent):
    """A read-only critic. It shares canon memory but never receives writing style."""

    name = "validator"
    task_types = frozenset({"validate_chapter"})

    def __init__(self, memory: NovelMemoryService):
        self.memory = memory

    def build_instruction(
        self, db: Session, novel: models.Novel, run: models.AgentRun
    ) -> AgentInstruction:
        chapter = db.get(models.Chapter, run.chapter_id) if run.chapter_id else None
        if not chapter or chapter.novel_id != novel.id:
            raise ValueError("章节不属于当前小说")
        state = self.memory.for_run(db, novel, chapter, include_writing_style=False)
        prompt = (
            f"校验第{chapter.sequence}章。大纲：{chapter.outline}\n"
            f"正文：{chapter.content}\n"
            "检查人物地点、状态、关系、时间线、已确认设定及是否偏离大纲。"
            "不得改写正文，只返回问题。"
            "返回 {\"passed\":true,\"issues\":[{\"type\":\"timeline_conflict\","
            "\"severity\":\"medium\",\"description\":\"...\",\"suggestion\":\"...\"}]}。"
        )
        return AgentInstruction(context=state.context, prompt=prompt, expects_json=True)
