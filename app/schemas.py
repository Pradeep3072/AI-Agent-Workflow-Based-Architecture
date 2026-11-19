from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AppointmentCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = Field(min_length=5, max_length=320)
    resource_key: str = Field(default="default", min_length=1, max_length=100)
    starts_at_utc: datetime

    @field_validator("starts_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at_utc must include a timezone, such as Z or +00:00")
        return value


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_name: str
    customer_email: str
    resource_key: str
    starts_at_utc: datetime
    status: str
    created_at: datetime

    @field_validator("starts_at_utc")
    @classmethod
    def label_stored_time_as_utc(cls, value: datetime) -> datetime:
        # SQLite drops timezone metadata, so restore the UTC label on responses.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TicketCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = Field(min_length=5, max_length=320)
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_name: str
    customer_email: str
    subject: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=36)


class ChatReply(BaseModel):
    conversation_id: str
    intent: str
    workflow: str
    message: str
    completed: bool = False
