from datetime import datetime, timezone
from enum import Enum

from google.adk import Context, Event, Workflow
from google.adk.workflow import START
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Appointment, SupportTicket


class Intent(str, Enum):
    BOOKING = "booking"
    SUPPORT_TICKET = "support_ticket"
    KNOWLEDGE_QUESTION = "knowledge_question"
    UNKNOWN = "unknown"


def _classify_message(message: str) -> Intent:
    """Select an intent with application-owned rules, without asking an LLM."""
    normalized = message.lower()

    if any(term in normalized for term in ("appointment", "book", "booking", "schedule")):
        return Intent.BOOKING
    if any(term in normalized for term in ("support ticket", "ticket", "problem", "issue")):
        return Intent.SUPPORT_TICKET

    question_starters = ("what ", "how ", "why ", "where ", "when ", "who ", "can ", "is ", "do ")
    if "?" in normalized or normalized.startswith(question_starters):
        return Intent.KNOWLEDGE_QUESTION
    return Intent.UNKNOWN


def select_workflow(ctx: Context, node_input: str) -> Event:
    """Route to the active workflow or classify a new user request."""
    active_workflow = ctx.state.get("active_workflow")
    ctx.state["turn_completed"] = False

    if active_workflow in {"appointment_booking", "support_ticket"}:
        route = active_workflow
    else:
        intent = _classify_message(node_input)
        ctx.state["last_intent"] = intent.value

        if intent == Intent.BOOKING:
            route = "appointment_booking"
            ctx.state["active_workflow"] = route
            ctx.state["booking"] = {"step": "start", "data": {}}
        elif intent == Intent.SUPPORT_TICKET:
            route = "support_ticket"
            ctx.state["active_workflow"] = route
            ctx.state["ticket"] = {"step": "start", "data": {}}
        elif intent == Intent.KNOWLEDGE_QUESTION:
            route = "knowledge_qa"
        else:
            route = "clarification"

    ctx.state["last_workflow"] = route
    return Event(route=route, output=node_input)


def appointment_workflow(ctx: Context, node_input: str) -> Event:
    """Collect booking details over turns and persist a confirmed appointment."""
    booking = ctx.state.get("booking", {"step": "start", "data": {}})
    data = booking["data"]
    answer = node_input.strip()
    step = booking["step"]

    if step == "start":
        ctx.state["booking"] = {"step": "customer_name", "data": data}
        return Event(message="Let's book an appointment. What name should I put on the booking?")

    if step == "customer_name":
        if not answer or len(answer) > 200:
            return Event(message="Please provide a name up to 200 characters.")
        data = {**data, "customer_name": answer}
        ctx.state["booking"] = {"step": "customer_email", "data": data}
        return Event(message="What email address should I use for the booking?")

    if step == "customer_email":
        if "@" not in answer or "." not in answer.split("@")[-1]:
            return Event(message="That email doesn't look valid. Please enter it again.")
        data = {**data, "customer_email": answer}
        ctx.state["booking"] = {"step": "resource_key", "data": data}
        return Event(message="Which resource should I book, such as a provider or room?")

    if step == "resource_key":
        if not answer or len(answer) > 100:
            return Event(message="Please provide a resource name up to 100 characters.")
        data = {**data, "resource_key": answer}
        ctx.state["booking"] = {"step": "starts_at_utc", "data": data}
        return Event(
            message="What date and time should I book? Use ISO format with a timezone, such as 2027-01-15T10:00:00Z."
        )

    if step == "starts_at_utc":
        try:
            requested_time = datetime.fromisoformat(answer.replace("Z", "+00:00"))
        except ValueError:
            return Event(message="I couldn't read that date and time. Please use ISO format with a timezone.")
        if requested_time.tzinfo is None or requested_time.utcoffset() is None:
            return Event(message="Please include a timezone, such as Z or +05:30.")

        database = SessionLocal()
        try:
            appointment = Appointment(
                customer_name=data["customer_name"],
                customer_email=data["customer_email"],
                resource_key=data["resource_key"],
                starts_at_utc=requested_time.astimezone(timezone.utc).replace(tzinfo=None),
            )
            database.add(appointment)
            database.commit()
        except IntegrityError:
            database.rollback()
            return Event(message="That slot is already booked. Please send a different date and time with a timezone.")
        finally:
            database.close()

        ctx.state["active_workflow"] = None
        ctx.state["booking"] = {}
        ctx.state["turn_completed"] = True
        ctx.state["last_appointment_id"] = appointment.id
        return Event(message=f"Appointment booked successfully. Your appointment ID is {appointment.id}.")

    ctx.state["active_workflow"] = None
    ctx.state["booking"] = {}
    ctx.state["turn_completed"] = True
    return Event(message="I lost the booking step. Please start a new appointment request.")


def support_ticket_workflow(ctx: Context, node_input: str) -> Event:
    """Collect support-ticket fields over turns and persist the completed ticket."""
    ticket_state = ctx.state.get("ticket", {"step": "start", "data": {}})
    data = ticket_state["data"]
    answer = node_input.strip()
    step = ticket_state["step"]

    if step == "start":
        ctx.state["ticket"] = {"step": "customer_name", "data": data}
        return Event(message="I can create a support ticket. What name should I put on it?")

    if step == "customer_name":
        if not answer or len(answer) > 200:
            return Event(message="Please provide a name up to 200 characters.")
        data = {**data, "customer_name": answer}
        ctx.state["ticket"] = {"step": "customer_email", "data": data}
        return Event(message="What email address should I use for the ticket?")

    if step == "customer_email":
        if "@" not in answer or "." not in answer.split("@")[-1]:
            return Event(message="That email doesn't look valid. Please enter it again.")
        data = {**data, "customer_email": answer}
        ctx.state["ticket"] = {"step": "subject", "data": data}
        return Event(message="What is a short subject for the ticket?")

    if step == "subject":
        if not answer or len(answer) > 200:
            return Event(message="Please provide a subject up to 200 characters.")
        data = {**data, "subject": answer}
        ctx.state["ticket"] = {"step": "description", "data": data}
        return Event(message="Please describe the problem in a little more detail.")

    if step == "description":
        if not answer or len(answer) > 5000:
            return Event(message="Please provide a description up to 5000 characters.")

        database = SessionLocal()
        try:
            ticket = SupportTicket(
                customer_name=data["customer_name"],
                customer_email=data["customer_email"],
                subject=data["subject"],
                description=answer,
            )
            database.add(ticket)
            database.commit()
        finally:
            database.close()

        ctx.state["active_workflow"] = None
        ctx.state["ticket"] = {}
        ctx.state["turn_completed"] = True
        ctx.state["last_ticket_id"] = ticket.id
        return Event(message=f"Support ticket created successfully. Your ticket ID is {ticket.id}.")

    ctx.state["active_workflow"] = None
    ctx.state["ticket"] = {}
    ctx.state["turn_completed"] = True
    return Event(message="I lost the ticket step. Please start a new support-ticket request.")


def knowledge_workflow(ctx: Context, node_input: str) -> Event:
    """Provide an honest placeholder until document and URL retrieval are added."""
    ctx.state["turn_completed"] = True
    return Event(message="Knowledge search is not connected yet. I can't answer from documents or web pages yet.")


def clarification_workflow(ctx: Context, node_input: str) -> Event:
    """Ask the user which supported workflow they want."""
    ctx.state["turn_completed"] = True
    return Event(
        message="I can help book an appointment, create a support ticket, or answer a question from the knowledge base. Which do you need?"
    )


root_agent = Workflow(
    name="workflow_agent",
    description="Routes requests to application-controlled appointment, support-ticket, and knowledge workflows.",
    edges=[
        (START, select_workflow),
        (
            select_workflow,
            {
                "appointment_booking": appointment_workflow,
                "support_ticket": support_ticket_workflow,
                "knowledge_qa": knowledge_workflow,
                "clarification": clarification_workflow,
            },
        ),
    ],
)
