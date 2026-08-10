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
    default_writing_model_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    default_outline_model_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    default_review_model_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    writing_temperature_override: Mapped[float | None] = mapped_column(nullable=True)
    outline_temperature_override: Mapped[float | None] = mapped_column(nullable=True)
    review_temperature_override: Mapped[float | None] = mapped_column(nullable=True)


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


class AgentRun(Timestamped, Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    context_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    partial_output: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(100))
    model_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provider_type: Mapped[str] = mapped_column(String(50), default="deepseek")
    api_base_url_label: Mapped[str] = mapped_column(String(255), default="")
    temperature: Mapped[float] = mapped_column(default=0.7)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextSnapshot(Base):
    __tablename__ = "context_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    confirmed_canon_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    character_state_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    unresolved_plot_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    recent_chapter_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    retrieval_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0)
    compression_level: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TokenUsage(Base):
    __tablename__ = "token_usages"
    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(100))
    input_tokens_estimated: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_budget: Mapped[int] = mapped_column(Integer, default=20000)
    compressed: Mapped[bool] = mapped_column(Boolean, default=False)
    compressed_token_savings: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelConfig(Timestamped, Base):
    __tablename__ = "model_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(50), default="openai_compatible")
    api_base_url: Mapped[str] = mapped_column(String(500))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(200))
    default_temperature: Mapped[float] = mapped_column(default=0.7)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    supported_tasks: Mapped[list] = mapped_column(JSON, default=list)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
