from hashlib import sha256

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import PrivateDocument
from app.private_documents import preserve_private_document


def test_document_roundtrip_is_exact_and_import_is_idempotent() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    content = b'{"summary":"synthetic fixture"}\n'
    with Session(engine) as session, session.begin():
        preserve_private_document(session, "legacy/profile.json", content)
    with Session(engine) as session, session.begin():
        preserve_private_document(session, "legacy/profile.json", content)
    with Session(engine) as session:
        rows = list(session.scalars(select(PrivateDocument)))
        assert len(rows) == 1
        assert rows[0].content == content
        assert rows[0].content_sha256 == sha256(content).hexdigest()
    engine.dispose()


def test_changed_source_cannot_overwrite_archived_private_data() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        preserve_private_document(session, "legacy/profile.json", b"original fixture")
    with Session(engine) as session, pytest.raises(ValueError):
        preserve_private_document(session, "legacy/profile.json", b"changed fixture")
    with Session(engine) as session:
        assert session.scalar(select(PrivateDocument)).content == b"original fixture"
    engine.dispose()
