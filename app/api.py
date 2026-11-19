from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Conversation, SupportTicket
from app.schemas import (
    AppointmentCreate,
    AppointmentRead,
    ChatReply,
    ChatRequest,
    TicketCreate,
    TicketRead,
)
from app.workflows import (
    Intent,
    WorkflowReply,
    continue_appointment_workflow,
    continue_ticket_workflow,
    route_message,
    start_appointment_workflow,
    start_ticket_workflow,
)


router = APIRouter(prefix="/api/v1")


@router.post("/chat", response_model=ChatReply)
def chat(request: ChatRequest, database: Session = Depends(get_db)) -> ChatReply:
    """Classify a new message or continue the workflow stored for its conversation."""
    conversation = None
    if request.conversation_id is not None:
        conversation = database.get(Conversation, request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    if conversation is not None and conversation.active_workflow == "appointment_booking":
        try:
            result = continue_appointment_workflow(conversation, request.message, database)
            database.commit()
        except IntegrityError:
            database.rollback()
            conversation = database.get(Conversation, request.conversation_id)
            result = WorkflowReply(
                intent=Intent.BOOKING,
                workflow="appointment_booking",
                message="That slot is already booked. Please send a different date and time in ISO format with a timezone.",
            )
            database.commit()
    elif conversation is not None and conversation.active_workflow == "support_ticket":
        result = continue_ticket_workflow(conversation, request.message, database)
        database.commit()
    else:
        result = route_message(request.message)
        conversation = Conversation()
        database.add(conversation)
        if result.intent == Intent.BOOKING:
            result = start_appointment_workflow(conversation)
        elif result.intent == Intent.SUPPORT_TICKET:
            result = start_ticket_workflow(conversation)
        database.commit()
        database.refresh(conversation)

    return ChatReply(
        conversation_id=conversation.id,
        intent=result.intent.value,
        workflow=result.workflow,
        message=result.message,
        completed=result.completed,
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
