# Workflow Agent: System Design

## Purpose

Workflow Agent is a chatbot that routes a user's message to one of three useful outcomes:

1. Book an appointment safely.
2. Create and track a support ticket.
3. Answer a question from approved knowledge sources, with source references. Sources can be uploaded documents or submitted web links.

The system should be understandable to develop and operate and protect user data. The initial deployment targets one application instance; we will revisit storage if deployment later requires multiple writers.

## Initial architecture

```text
User interface (Streamlit initially)
              |
              v
         FastAPI API
              |
     Intent and workflow router
       /          |          \
 Booking       Tickets       RAG
    |              |           |
    +--------------+-----------+
                   |
        SQLite / vector adapter
                   |
     Document and URL ingestion
                   |
       Extract / scrape, chunk,
        embed, and index content
                   |
         SQLite database

            Gemini provider

Redis and a background worker are added for shared short-lived state,
rate limits, and document or URL processing when those needs are implemented.
```

This is a logical design. In early development, the API, workflow code, and worker can run in a small number of processes. They do not need to be separate cloud services until deployment requirements justify that complexity.

## Proposed technology choices

| Area | Initial choice | Why |
| --- | --- | --- |
| Language | Python | Fits the proposed AI stack and supports fast iteration. |
| API | FastAPI | Provides typed request validation and a clear HTTP API. |
| User interface | Streamlit | Gets us a usable chat interface quickly while the API remains independently testable. |
| Workflow orchestration | Explicit Python workflow/router first | Makes booking and ticket rules easy to inspect; we can adopt LangGraph or ADK if stateful branching proves useful. |
| Relational data | SQLite | Keeps initial setup simple with a local database file for users, appointments, tickets, and source metadata. Transactions and constraints protect core records for the initial single-instance deployment. |
| Retrieval | SQLite with sqlite-vec if available, behind a replaceable vector-store adapter | Keeps the initial footprint simple. We will verify extension availability in the target environment; if it is unavailable, use a separate local vector index behind the same retrieval interface. |
| LLM | Google Gemini behind a provider interface | Uses the requested model while keeping provider-specific code isolated. |
| Cache/queue | Redis, when needed | Shared ephemeral state, rate limits, and queued document/URL ingestion jobs. It is not the source of truth for bookings or tickets. |
| Schema changes | Alembic | Applies and tracks database migrations safely. |
| Packaging | Docker for the app; Docker Compose when auxiliary services are needed | Gives developers a repeatable environment. SQLite does not require a database service. |

These are starting choices, not claims that every component is required on day one. We will keep interfaces modular and add infrastructure when a workflow needs it. The initial deployment uses one app instance and a persistent SQLite file; do not have multiple app instances write to one shared SQLite file.

## Core data and safety rules

- SQLite is the source of truth for users, appointments, tickets, and durable conversation records in the initial single-instance deployment.
- Appointment creation must be protected by a database constraint or transaction so concurrent requests cannot reserve the same slot.
- Ticket IDs must be unique, and ticket status changes must be persisted.
- RAG supports two source-ingestion paths: users upload documents, or submit a URL for page retrieval and scraping.
- Uploaded files and scraped pages go through ingestion before they become searchable: validate and extract content, normalize it, split it into chunks, generate embeddings, and store chunks plus metadata in the vector store.
- Each indexed chunk retains provenance: source type, original filename or URL, title when available, ingestion time, and relevant page/section information. Answers cite the supporting source.
- URL ingestion must only fetch publicly reachable web content, enforce URL/network safety checks, limit page size and crawl scope, and respect applicable site access rules. It must not fetch arbitrary internal network addresses.
- RAG answers must use retrieved approved content and say when the available material does not answer the question.
- Secrets such as Gemini credentials must come from environment configuration and must not be committed.
- Redis, if used, stores temporary/shared state; losing it must not erase a confirmed appointment or ticket.
- The SQLite file must live on persistent storage and be backed up. Adding Redis does not make a shared SQLite file suitable for multi-instance writes; revisit the database choice if that deployment becomes necessary.

## Initial API boundary

The API will expose versioned endpoints for:

- health/readiness checks;
- chat messages and workflow results;
- appointment availability and booking;
- ticket creation and status lookup;
- document upload and indexing status;
- URL submission and indexing status.

Request and response models will be explicit. The chat UI will call the API instead of directly owning business logic.

## Delivery phases

1. **Design:** settle user roles, workflow rules, and data model assumptions.
2. **Foundation:** create the Python package, configuration, FastAPI app, database models, migrations, and local Docker services.
3. **Business workflows:** implement appointment booking and ticket creation with durable rules.
4. **Knowledge workflow:** ingest uploaded documents and scraped web pages, retrieve relevant passages, and return grounded answers with source references.
5. **Chat interface and shared state:** connect the UI, add conversation persistence, and use Redis/worker jobs where justified.
6. **Hardening and deployment:** authentication/authorization, observability, security review, backups, deployment, and load evaluation.

## Open decisions to resolve during design

- Who are the expected users, and do they need accounts or different roles?
- What appointment resource is being booked, what defines a slot, and what are the cancellation/rescheduling rules?
- What support-ticket fields and status transitions are required?
- Which documents and websites are trusted for RAG, who can upload documents or submit URLs, and what file formats/page types are in scope?
- What initial deployment target and expected traffic should shape production sizing?

We can begin with safe defaults and revise these decisions as requirements become clear. Any assumption affecting business behavior will be called out before it is encoded in a workflow.
