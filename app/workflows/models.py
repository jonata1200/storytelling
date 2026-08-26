from uuid import UUID

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DependencyKind
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ArtifactDependency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "artifact_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "upstream_artifact_id",
            "downstream_artifact_id",
            "dependency_kind",
            name="uq_artifact_dependency_edge",
        ),
    )

    upstream_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id"), nullable=False, index=True
    )
    downstream_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id"), nullable=False, index=True
    )
    dependency_kind: Mapped[DependencyKind] = mapped_column(
        Enum(DependencyKind, name="dependency_kind"),
        default=DependencyKind.DERIVED_FROM,
        nullable=False,
    )
