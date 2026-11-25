from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from google.genai import types

from app.database import get_db
from app.models import Appointment, LegacyConversation, SupportTicket
from app.schemas import (
    AppointmentCreate,
    AppointmentRead,
    ChatReply,
    ChatRequest,
    TicketCreate,
    TicketRead,
)
router = APIRouter(prefix="/api/v1")


@router.post("/chat", response_model=ChatReply)
async def chat(
    request: ChatRequest,
    http_request: Request,
    database: Session = Depends(get_db),
) -> ChatReply:
    """Create or resume an ADK session and execute the root workflow."""
    session_service = http_request.app.state.adk_session_service
    runner = http_request.app.state.adk_runner
    user_id = "local_user"
    app_name = http_request.app.state.adk_app_name

    if request.conversation_id:
        session = await session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=request.conversation_id,
        )
        if session is None:
            legacy = database.get(LegacyConversation, request.conversation_id)
            if legacy is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")

            initial_state = {}
            if legacy.active_workflow == "appointment_booking":
                initial_state = {
                    "active_workflow": "appointment_booking",
                    "booking": legacy.state,
                    "last_intent": "booking",
                    "last_workflow": "appointment_booking",
                    "turn_completed": False,
                }
            elif legacy.active_workflow == "support_ticket":
                initial_state = {
                    "active_workflow": "support_ticket",
                    "ticket": legacy.state,
                    "last_intent": "support_ticket",
                    "last_workflow": "support_ticket",
                    "turn_completed": False,
                }

            session = await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=legacy.id,
                state=initial_state,
            )
    else:
        session = await session_service.create_session(app_name=app_name, user_id=user_id)

    message = types.Content(
        role="user",
        parts=[types.Part(text=request.message)],
    )
    response_text = "The workflow completed without a text response."
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=message,
    ):
        if event.author != "user" and event.content and event.content.parts:
            text_parts = [part.text for part in event.content.parts if part.text]
            if text_parts:
                response_text = "".join(text_parts)

    updated_session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session.id,
    )
    state = updated_session.state if updated_session else {}
    return ChatReply(
        conversation_id=session.id,
        intent=state.get("last_intent", "unknown"),
        workflow=state.get("last_workflow", "clarification"),
        message=response_text,
        completed=state.get("turn_completed", False),
    )


@router.post(
    "/appointments",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_appointment(
    request: AppointmentCreate,
    database: Session = Depends(get_db),
) -> Appointment:
    """Book a resource at a time, returning 409 if it is already taken."""
    starts_at_utc = request.starts_at_utc.astimezone(timezone.utc).replace(tzinfo=None)
    appointment = Appointment(
        customer_name=request.customer_name,
        customer_email=request.customer_email,
        resource_key=request.resource_key,
        starts_at_utc=starts_at_utc,
    )
    database.add(appointment)
    try:
        database.commit()
    except IntegrityError as error:
        database.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That resource is already booked for this time.",
        ) from error
    database.refresh(appointment)
    return appointment


@router.post(
    "/tickets",
    response_model=TicketRead,
    status_code=status.HTTP_201_CREATED,
)
def create_ticket(
    request: TicketCreate,
    database: Session = Depends(get_db),
) -> SupportTicket:
    """Create a support ticket and return its generated ID."""
    ticket = SupportTicket(**request.model_dump())
    database.add(ticket)
    database.commit()
    database.refresh(ticket)
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: str, database: Session = Depends(get_db)) -> SupportTicket:
    """Look up a ticket by its ID."""
    ticket = database.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )
    return ticket
