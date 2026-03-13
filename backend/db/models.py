import uuid
from sqlalchemy import Column, String, Integer, Float, BigInteger, Text, Boolean, ForeignKey, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, DeclarativeBase
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String(50), nullable=False, default="QUEUED")
    progress = Column(Integer, nullable=False, default=0)
    pipeline_stage = Column(String(50))
    params = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    assets = relationship("Asset", back_populates="job", cascade="all, delete-orphan")
    transcripts = relationship("Transcript", back_populates="job", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    mimetype = Column(String(100))
    size_bytes = Column(BigInteger)
    duration_seconds = Column(Float)
    sample_rate = Column(Integer)
    channels = Column(Integer)
    input_path = Column(String(500))
    archival_path = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="assets")


class Speaker(Base):
    __tablename__ = "speakers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    is_trusted = Column(Boolean, nullable=False, default=False)
    match_confidence = Column(Float)
    avatar_id = Column(Integer)  # index into default avatar set (0-99), null = auto-assign
    custom_avatar = Column(String(500))  # filename of uploaded custom avatar, overrides avatar_id
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    segments = relationship("Segment", back_populates="speaker")
    embeddings = relationship("Embedding", back_populates="speaker", cascade="all, delete-orphan")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    raw_text = Column(Text, nullable=False, default="")
    title = Column(String(500))
    summary = Column(Text)
    language = Column(String(10))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    job = relationship("Job", back_populates="transcripts")
    segments = relationship("Segment", back_populates="transcript", cascade="all, delete-orphan",
                           order_by="Segment.start_time")
    tags = relationship("Tag", back_populates="transcript", cascade="all, delete-orphan")


class Segment(Base):
    __tablename__ = "segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transcript_id = Column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    segment_index = Column(Integer)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    word_timings = Column(JSONB)
    speaker_id = Column(UUID(as_uuid=True), ForeignKey("speakers.id", ondelete="SET NULL"))
    original_speaker_label = Column(String(50))
    emotion = Column(String(50))
    emotion_confidence = Column(Float)
    speech_events = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transcript = relationship("Transcript", back_populates="segments")
    speaker = relationship("Speaker", back_populates="segments")
    embeddings = relationship("Embedding", back_populates="segment")


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    speaker_id = Column(UUID(as_uuid=True), ForeignKey("speakers.id", ondelete="CASCADE"), nullable=False)
    segment_id = Column(UUID(as_uuid=True), ForeignKey("segments.id", ondelete="SET NULL"))
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))
    embedding = Column(Vector(192), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    speaker = relationship("Speaker", back_populates="embeddings")
    segment = relationship("Segment", back_populates="embeddings")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transcript_id = Column(UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    tag = Column(String(100), nullable=False)
    source = Column(String(50), nullable=False, default="llm")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transcript = relationship("Transcript", back_populates="tags")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    model_config = Column(JSONB, nullable=False, default=dict)
    api_token = Column(String(255))
    hf_token = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("id = 1", name="settings_singleton"),
    )
