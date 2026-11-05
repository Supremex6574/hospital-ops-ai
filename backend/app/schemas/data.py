from datetime import datetime

from pydantic import BaseModel


class UploadOut(BaseModel):
    id: int
    filename: str
    uploaded_at: datetime | None
    rows_total: int
    rows_valid: int
    rows_dropped: int
    duplicates_removed: int
    missing_filled: int
    status: str

    model_config = {"from_attributes": True}


class UploadResult(BaseModel):
    upload: UploadOut
    report: dict
