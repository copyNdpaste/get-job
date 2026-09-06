from enum import StrEnum


class ApplicationStatus(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    INTERESTED = "interested"
    RESUME_PREPARING = "resume_preparing"
    APPLIED = "applied"
    DOCUMENT_PASSED = "document_passed"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class CrawlRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ExperienceType(StrEnum):
    ANY = "any"
    ENTRY = "entry"
    EXPERIENCED = "experienced"
    RANGE = "range"
    UNKNOWN = "unknown"


class JobGrade(StrEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    EXCLUDED = "Excluded"
