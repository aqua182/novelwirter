from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NovelBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    genre: str | None = None
    theme: str | None = None
    target_words: int | None = Field(default=None, ge=0)
    default_style: str | None = None
    master_outline: str | None = None
class NovelCreate(NovelBase): pass
class NovelUpdate(NovelBase): title: str | None = Field(default=None, min_length=1, max_length=200)
class NovelRead(NovelBase, ORMModel):
    id: int; created_at: datetime; updated_at: datetime


class OutlineBase(BaseModel):
    parent_id: int | None = None; chapter_id: int | None = None; node_type: str = "chapter"; title: str; content: str = ""; sort_order: int = 0
class OutlineCreate(OutlineBase): pass
class OutlineUpdate(OutlineBase): title: str | None = None
class OutlineRead(OutlineBase, ORMModel): id: int; novel_id: int


class ChapterBase(BaseModel):
    sequence: int = 1; title: str = "未命名章节"; outline: str = ""; content: str = ""; writing_requirements: str = ""; target_words: int | None = Field(default=None, ge=0); status: str = "draft"
class ChapterCreate(ChapterBase): pass
class ChapterUpdate(ChapterBase):
    sequence: int | None = None; title: str | None = None; outline: str | None = None; content: str | None = None; writing_requirements: str | None = None; target_words: int | None = None; status: str | None = None
class ChapterRead(ChapterBase, ORMModel): id: int; novel_id: int; actual_words: int; created_at: datetime; updated_at: datetime


class CharacterBase(BaseModel):
    name: str; profile: str = ""; goal: str = ""; personality: str = ""; relationships: str = ""; current_status: str = ""; confirmed: bool = False
    is_main_character: bool = False; importance: int = Field(default=3, ge=1, le=5); current_location: str = ""; current_goal: str = ""; current_emotion_or_state: str = ""; arc_or_growth: str = ""; status: str = "draft"
class CharacterCreate(CharacterBase): pass
class CharacterUpdate(CharacterBase): name: str | None = None
class CharacterRead(CharacterBase, ORMModel): id: int; novel_id: int

class TimelineBase(BaseModel):
    time_description: str = ""; location: str = ""; content: str; participants: str = ""; source_chapter_id: int | None = None; confirmed: bool = False
class TimelineCreate(TimelineBase): pass
class TimelineUpdate(TimelineBase): content: str | None = None
class TimelineRead(TimelineBase, ORMModel): id: int; novel_id: int

class FactBase(BaseModel):
    fact_type: str = "world"; content: str; source_chapter_id: int | None = None; status: str = "draft"
class FactCreate(FactBase): pass
class FactUpdate(FactBase): content: str | None = None
class FactRead(FactBase, ORMModel): id: int; novel_id: int

class SummaryRead(ORMModel):
    id: int; novel_id: int; chapter_id: int; summary: str; key_events: str; foreshadowing: str; unresolved_conflicts: str

class GenerateOutlineRequest(BaseModel): theme: str = ""; genre: str = ""; target_words: int = 100000; chapter_count: int = 20; style: str = ""
class ImproveOutlineRequest(BaseModel):
    improvement_request: str = Field(min_length=1)
    chapter_count: int | None = Field(default=None, ge=1, le=200)
class ImproveChapterOutlineRequest(BaseModel): improvement_request: str = Field(min_length=1)
class ApplyOutlineImprovementRequest(BaseModel):
    master_outline: str | None = None
    chapters: list[dict] = Field(default_factory=list)
    apply_chapter_numbers: list[int] | None = None
class OutlineRevisionRead(ORMModel): id: int; novel_id: int; content: str; reason: str; created_at: datetime
class PlanChaptersRequest(BaseModel): requirements: str = ""; chapter_count: int = Field(ge=1, le=200); chapter_words: int = Field(default=3000, ge=100); style: str = ""
class GenerateChapterRequest(BaseModel): style_hint: str = ""; target_words: int | None = None
class Issue(BaseModel): type: str; severity: str; description: str; suggestion: str
class ValidationResult(BaseModel): passed: bool; issues: list[Issue]
