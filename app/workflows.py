from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.orm import Session

from app.models import Appointment, Conversation, SupportTicket


class Intent(str, Enum):
    BOOKING = "booking"
    SUPPORT_TICKET = "support_ticket"
    KNOWLEDGE_QUESTION = "knowledge_question"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WorkflowReply:
    intent: Intent
    workflow: str
    message: str
    completed: bool = False


def classify_intent(message: str) -> Intent:
    """Choose a workflow using simple starter rules; Gemini can replace this later."""
    normalized = message.lower()

    if any(term in normalized for term in ("appointment", "book", "booking", "schedule")):
        return Intent.BOOKING

    if any(term in normalized for term in ("support ticket", "ticket", "problem", "issue")):
        return Intent.SUPPORT_TICKET

    question_starters = ("what ", "how ", "why ", "where ", "when ", "who ", "can ", "is ", "do ")
    if "?" in normalized or normalized.startswith(question_starters):
        return Intent.KNOWLEDGE_QUESTION

    return Intent.UNKNOWN


def route_message(message: str) -> WorkflowReply:
    """Route a message to a workflow and return its first response."""
    intent = classify_intent(message)

    if intent == Intent.BOOKING:
        return WorkflowReply(
            intent=intent,
            workflow="appointment_booking",
            message="I can help book an appointment. What resource and date/time do you prefer? Include the time zone.",
        )

    if intent == Intent.SUPPORT_TICKET:
        return WorkflowReply(
            intent=intent,
            workflow="support_ticket",
            message="I can create a support ticket. Please describe the issue, and include your name and email.",
        )

    if intent == Intent.KNOWLEDGE_QUESTION:
        return WorkflowReply(
            intent=intent,
            workflow="knowledge_qa",
            message="I routed this to knowledge Q&A. The document and web-page search workflow is not connected yet.",
        )

    return WorkflowReply(
        intent=intent,
        workflow="clarification",
        message="I can help book an appointment, create a support ticket, or answer a question from the knowledge base. Which do you need?",
    )


def start_appointment_workflow(conversation: Conversation) -> WorkflowReply:
    """Initialize the appointment workflow and ask for its first required value."""
    conversation.active_workflow = "appointment_booking"
    conversation.state = {"step": "customer_name", "booking": {}}
    return WorkflowReply(
        intent=Intent.BOOKING,
        workflow="appointment_booking",
        message="Let's book an appointment. What name should I put on the booking?",
    )


def start_ticket_workflow(conversation: Conversation) -> WorkflowReply:
    """Initialize ticket intake and ask for its first required value."""
    conversation.active_workflow = "support_ticket"
    conversation.state = {"step": "customer_name", "ticket": {}}
    return WorkflowReply(
        intent=Intent.SUPPORT_TICKET,
        workflow="support_ticket",
        message="I can create a support ticket. What name should I put on it?",
    )


def continue_appointment_workflow(
    conversation: Conversation,
    message: str,
    database: Session,
) -> WorkflowReply:
    """Collect booking fields one at a time, then create the appointment record."""
    state = conversation.state
    booking = state["booking"]
    step = state["step"]
    answer = message.strip()

    if step == "customer_name":
        if not answer or len(answer) > 200:
            return _appointment_prompt("Please provide a name up to 200 characters.")
        booking["customer_name"] = answer
        conversation.state = {"step": "customer_email", "booking": dict(booking)}
        return _appointment_prompt("What email address should I use for the booking?")

    if step == "customer_email":
        if "@" not in answer or "." not in answer.split("@")[-1]:
            return _appointment_prompt("That email doesn't look valid. Please enter it again.")
        booking["customer_email"] = answer
        conversation.state = {"step": "resource_key", "booking": dict(booking)}
        return _appointment_prompt("Which resource should I book (for example, a provider or room)?")

    if step == "resource_key":
        if not answer or len(answer) > 100:
            return _appointment_prompt("Please provide a resource name up to 100 characters.")
        booking["resource_key"] = answer
        conversation.state = {"step": "starts_at_utc", "booking": dict(booking)}
        return _appointment_prompt(
            "What date and time should I book? Use ISO format with a timezone, such as 2027-01-15T10:00:00Z."
        )

    if step == "starts_at_utc":
        try:
            requested_time = datetime.fromisoformat(answer.replace("Z", "+00:00"))
        except ValueError:
            return _appointment_prompt("I couldn't read that date and time. Please use ISO format with a timezone.")
        if requested_time.tzinfo is None or requested_time.utcoffset() is None:
            return _appointment_prompt("Please include a timezone, such as Z or +05:30.")

        appointment = Appointment(
            customer_name=booking["customer_name"],
            customer_email=booking["customer_email"],
            resource_key=booking["resource_key"],
            starts_at_utc=requested_time.astimezone(timezone.utc).replace(tzinfo=None),
        )
        database.add(appointment)
        database.flush()
        conversation.active_workflow = None
        conversation.state = {"last_completed_workflow": "appointment_booking"}
        return WorkflowReply(
            intent=Intent.BOOKING,
            workflow="appointment_booking",
            message=f"Appointment booked successfully. Your appointment ID is {appointment.id}.",
            completed=True,
        )

    conversation.active_workflow = None
    conversation.state = {}
    return WorkflowReply(
        intent=Intent.UNKNOWN,
        workflow="clarification",
        message="I lost the current booking step. Please tell me if you want to book an appointment, create a ticket, or ask a question.",
    )


def continue_ticket_workflow(
    conversation: Conversation,
    message: str,
    database: Session,
) -> WorkflowReply:
    """Collect ticket fields over multiple messages and save the completed ticket."""
    state = conversation.state
    ticket_data = state["ticket"]
    step = state["step"]
    answer = message.strip()

    if step == "customer_name":
        if not answer or len(answer) > 200:
            return _ticket_prompt("Please provide a name up to 200 characters.")
        ticket_data["customer_name"] = answer
        conversation.state = {"step": "customer_email", "ticket": dict(ticket_data)}
        return _ticket_prompt("What email address should I use for the ticket?")

    if step == "customer_email":
        if "@" not in answer or "." not in answer.split("@")[-1]:
            return _ticket_prompt("That email doesn't look valid. Please enter it again.")
        ticket_data["customer_email"] = answer
        conversation.state = {"step": "subject", "ticket": dict(ticket_data)}
        return _ticket_prompt("What is a short subject for the ticket?")

    if step == "subject":
        if not answer or len(answer) > 200:
            return _ticket_prompt("Please provide a subject up to 200 characters.")
        ticket_data["subject"] = answer
        conversation.state = {"step": "description", "ticket": dict(ticket_data)}
        return _ticket_prompt("Please describe the problem in a little more detail.")

    if step == "description":
        if not answer or len(answer) > 5000:
            return _ticket_prompt("Please provide a description up to 5000 characters.")
        ticket = SupportTicket(
            customer_name=ticket_data["customer_name"],
            customer_email=ticket_data["customer_email"],
            subject=ticket_data["subject"],
            description=answer,
        )
        database.add(ticket)
        database.flush()
        conversation.active_workflow = None
        conversation.state = {"last_completed_workflow": "support_ticket"}
        return WorkflowReply(
            intent=Intent.SUPPORT_TICKET,
            workflow="support_ticket",
            message=f"Support ticket created successfully. Your ticket ID is {ticket.id}.",
            completed=True,
        )

    conversation.active_workflow = None
    conversation.state = {}
    return WorkflowReply(
        intent=Intent.UNKNOWN,
        workflow="clarification",
        message="I lost the current ticket step. Please tell me if you want to book an appointment, create a ticket, or ask a question.",
    )


def _appointment_prompt(message: str) -> WorkflowReply:
    return WorkflowReply(
        intent=Intent.BOOKING,
        workflow="appointment_booking",
        message=message,
    )


def _ticket_prompt(message: str) -> WorkflowReply:
    return WorkflowReply(
        intent=Intent.SUPPORT_TICKET,
        workflow="support_ticket",
        message=message,
    )
