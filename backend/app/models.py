from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Novel(Timestamped, Base):
    __tablename__ = "novels"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    theme: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    master_outline: Mapped[str] = mapped_column(Text, default="")


class OutlineNode(Timestamped, Base):
    __tablename__ = "outline_nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("outline_nodes.id"), nullable=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    node_type: Mapped[str] = mapped_column(String(20), default="chapter")
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Chapter(Timestamped, Base):
    __tablename__ = "chapters"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200), default="未命名章节")
    outline: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    writing_requirements: Mapped[str] = mapped_column(Text, default="")
    target_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_words: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")


class Character(Timestamped, Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    profile: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    relationships: Mapped[str] = mapped_column(Text, default="")
    current_status: Mapped[str] = mapped_column(Text, default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_main_character: Mapped[bool] = mapped_column(Boolean, default=False)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    current_location: Mapped[str] = mapped_column(String(200), default="")
    current_goal: Mapped[str] = mapped_column(Text, default="")
    current_emotion_or_state: Mapped[str] = mapped_column(Text, default="")
    arc_or_growth: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")


class TimelineEvent(Timestamped, Base):
    __tablename__ = "timeline_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    time_description: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text)
    participants: Mapped[str] = mapped_column(Text, default="")
    source_chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class ChapterSummary(Timestamped, Base):
    __tablename__ = "chapter_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), unique=True)
    summary: Mapped[str] = mapped_column(Text)
    key_events: Mapped[str] = mapped_column(Text, default="")
    foreshadowing: Mapped[str] = mapped_column(Text, default="")
    unresolved_conflicts: Mapped[str] = mapped_column(Text, default="")


class CanonFact(Timestamped, Base):
    __tablename__ = "canon_facts"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    fact_type: Mapped[str] = mapped_column(String(50), default="world")
    content: Mapped[str] = mapped_column(Text)
    source_chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    job_type: Mapped[str] = mapped_column(String(50))
    input_params: Mapped[dict] = mapped_column(JSON, default=dict)
    model_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutlineRevision(Base):
    __tablename__ = "outline_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(String(100), default="manual_save")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
