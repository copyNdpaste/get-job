"""Transactional storage for legacy private documents; no filesystem exports."""

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.private_document import PrivateDocument


def preserve_private_document(session: Session, source_key: str, content: bytes) -> PrivateDocument:
    digest = sha256(content).hexdigest()
    document = session.scalar(
        select(PrivateDocument).where(PrivateDocument.source_key == source_key)
    )
    if document is None:
        document = PrivateDocument(source_key=source_key, content_sha256=digest, content=content)
        session.add(document)
    elif document.content_sha256 != digest or document.content != content:
        raise ValueError("A different private document already exists; no data was overwritten.")
    session.flush()
    return document
