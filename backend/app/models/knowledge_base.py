from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("folder_id", "knowledge_base_name", name="uq_kb_folder_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    knowledge_base_name: Mapped[str] = mapped_column(String(128), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("kb_folders.folder_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    folder: Mapped["KBFolder | None"] = relationship(
        "KBFolder",
        back_populates="knowledge_bases",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.knowledge_base_id}, name={self.knowledge_base_name})>"


# Avoid circular import at module level
from app.models.document import Document  # noqa: E402, F401
from app.models.kb_folder import KBFolder  # noqa: E402, F401
