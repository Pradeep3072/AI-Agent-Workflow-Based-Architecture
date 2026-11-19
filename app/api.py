from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, SupportTicket
from app.schemas import (
    AppointmentCreate,
    AppointmentRead,
    TicketCreate,
    TicketRead,
)


router = APIRouter(prefix="/api/v1")


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
