from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class KBFolder(Base):
    __tablename__ = "kb_folders"
    __table_args__ = (
        UniqueConstraint("parent_folder_id", "folder_name", name="uq_kb_folder_sibling_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    folder_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_folder_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("kb_folders.folder_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    parent: Mapped[KBFolder | None] = relationship(
        "KBFolder",
        remote_side="KBFolder.folder_id",
        back_populates="children",
    )
    children: Mapped[list[KBFolder]] = relationship(
        "KBFolder",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    knowledge_bases: Mapped[list[KnowledgeBase]] = relationship(
        "KnowledgeBase",
        back_populates="folder",
    )

    def __repr__(self) -> str:
        return (
            f"<KBFolder(id={self.folder_id}, name={self.folder_name}, "
            f"parent={self.parent_folder_id}, depth={self.depth})>"
        )


from app.models.knowledge_base import KnowledgeBase  # noqa: E402, F401
