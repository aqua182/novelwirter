from dataclasses import dataclass

from sqlalchemy.orm import Session

from .. import models
from ..services.context import build_chapter_context, build_story_context


@dataclass(frozen=True)
class NovelMemoryState:
    """An immutable, novel-scoped memory snapshot shared by controlled roles."""

    novel_id: int
    chapter_id: int | None
    context: str
    includes_writing_style: bool


class NovelMemoryService:
    """Builds shared state from persistent records instead of process-local chat memory."""

    def for_run(
        self,
        db: Session,
        novel: models.Novel,
        chapter: models.Chapter | None = None,
        *,
        include_writing_style: bool = False,
    ) -> NovelMemoryState:
        if chapter and chapter.novel_id != novel.id:
            raise ValueError("章节不属于当前小说")
        context = (
            build_chapter_context(
                db, novel, chapter, include_writing_style=include_writing_style
            )
            if chapter
            else build_story_context(db, novel, include_writing_style=include_writing_style)
        )
        return NovelMemoryState(
            novel_id=novel.id,
            chapter_id=chapter.id if chapter else None,
            context=context,
            includes_writing_style=include_writing_style,
        )
