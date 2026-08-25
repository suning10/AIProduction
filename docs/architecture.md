# Architecture

## System overview

```mermaid
graph TB
    Client["Client\n(HTTP / SSE)"]

    subgraph FastAPI["FastAPI Application"]
        MW["Middleware\n(rate limit, metrics,\nlogging context, profiling)"]
        Auth["Auth\n(JWT)"]
        API["API Routes\n/chat, /chat/stream\n/auth/*, /health"]
    end

    subgraph Agent["LangGraph Agent"]
        Graph["StateGraph\n(plan → chat ⇄ tool_call,\nor plan → worker × N → synthesize)"]
        Checkpointer["AsyncPostgresSaver\n(conversation state)"]
    end

    subgraph Services["Services"]
        LLM["LLM Service\n(fallback + retry)"]
        Memory["Memory Service\n(mem0 + cache)"]
        Tools["Tools\n(concurrent execution)"]
    end

    subgraph Storage["Storage"]
        PG[("PostgreSQL\n+ pgvector")]
        Cache["Valkey/Redis\n(optional)"]
    end

    subgraph Observability["Observability"]
        Langfuse["Langfuse\n(LLM traces)"]
        Prometheus["Prometheus\n+ Grafana"]
        Logs["structlog\n(JSON / console)"]
    end

    Client --> MW --> Auth --> API
    API --> Graph
    Graph --> LLM --> Langfuse
    Graph --> Tools
    Graph --> Memory --> Cache
    Graph <--> Checkpointer
    Memory --> PG
    Checkpointer --> PG
    API --> Prometheus
    API --> Logs
```

## Request lifecycle

```mermaid
sequenceDiagram
    participant C as Client
    participant MW as Middleware
    participant A as Auth
    participant G as LangGraph
    participant Mem as Memory
    participant L as LLM
    participant T as Tools

    C->>MW: POST /chat (Bearer token)
    MW->>MW: rate limit, metrics, request ID
    MW->>A: verify JWT → session
    A->>G: invoke graph

    par concurrent
        G->>G: aget_state (resume check)
        G->>Mem: search relevant memories
    end

    G->>L: chat node — system prompt + context + messages
    L-->>G: response with tool_calls?

    alt has tool calls
        G->>T: execute tools concurrently
        T-->>G: tool results
        G->>L: chat node again with tool results
        L-->>G: final response
    end

    G-->>A: response messages
    G-)Mem: add memories (background task)
    A-->>C: JSON response
```

## Agent graph

Every turn starts at a lead agent (`plan`) that classifies the query as simple or complex, then either runs the single-agent loop directly or fans out to a parallel worker swarm:

```mermaid
graph TB
    START --> plan
    plan -->|simple| chat
    plan -->|"complex: Send × N"| worker1[worker]
    plan -->|"complex: Send × N"| worker2[worker]
    plan -->|"complex: Send × N"| workerN["worker ..."]
    chat -->|tool_calls present| tool_call
    tool_call --> chat
    chat -->|no tool_calls| END
    worker1 --> synthesize
    worker2 --> synthesize
    workerN --> synthesize
    synthesize --> END
```

- **`plan` node (lead agent)** — a cheap structured-output call (`gpt-5.4-nano`) classifies the query as `"simple"` or `"complex"`. Simple (the common case) routes straight to `chat`, unchanged from before. Complex decomposes the query into independent subtasks and dynamically fans out to one `worker` branch per subtask via LangGraph's `Send` API. Classification errors fail open to the simple path rather than failing the request.
- **`chat` node** — builds the system prompt, calls the LLM, returns a `Command` routing to `tool_call` or `END`. Bounded by `MAX_TOOL_CALLS_PER_TURN` tool-call rounds; once reached, it's called again with tools omitted so the model must answer with what it has instead of looping forever.
- **`tool_call` node** — executes all tool calls concurrently, feeds results back to `chat`.
- **`worker` node** — runs one subtask to completion by directly calling the same `chat`/`tool_call` methods in a local loop (not as separate graph steps), so N workers execute concurrently without interfering with each other's state. Workers get every tool except `ask_human` (pausing one branch of a parallel swarm to ask the user is a known LangGraph sharp edge) and a smaller `MAX_TOOL_CALLS_PER_WORKER` budget. Each worker's answer is appended to `subtask_results`, a state field merged across parallel branches via an `operator.add` reducer.
- **`synthesize` node** — runs once all worker branches converge, combining every `subtask_results` entry into one final answer.
- **Streaming** — only `chat` and `synthesize` token output reaches the client (`get_stream_response` filters on `metadata["langgraph_node"]`); `plan`'s classification and worker execution happen server-side.
- **Checkpointer** — `AsyncPostgresSaver` persists the full `GraphState` per `thread_id` (session), enabling resume on interrupts and multi-turn memory. `tool_call_count`, `subtasks`, and `subtask_results` are reset to empty at the start of each fresh (non-resumed) turn.

## Key design decisions

**Memory search and state check run concurrently.** On every non-resumed request, `aget_state` (to check for interrupts) and `memory.search` (to fetch relevant memories) run in parallel with `asyncio.gather`, saving 200–500ms per request.

**Tool calls execute concurrently.** When the LLM returns multiple tool calls in one response, they all execute in parallel via `asyncio.gather`.

**System prompt cached at module load.** `system.md` is read once at startup. Per-request cost is only `.format()` with the user's name, current datetime, and retrieved memories — no file I/O.

**LLM fallback is time-bounded.** The entire fallback loop (retries × models) is wrapped in `asyncio.wait_for(timeout=LLM_TOTAL_TIMEOUT)` to prevent indefinite hangs.

**Username flows through session, not per-request DB lookup.** The user's display name is copied to `Session.username` at session creation time. Chat requests read it from the already-loaded session object — zero extra queries.

**Session titles are generated with zero added latency.** On the first message of an unnamed session, the API atomically claims the session with a placeholder name (a truncated version of the user's message), then fires a background `asyncio.Task` to call a fast nano model with structured output. The main chat response is returned immediately — title generation runs concurrently. An atomic `UPDATE … WHERE name = ''` in Postgres ensures exactly one worker wins the claim even under concurrent requests.

## Component responsibilities

| Component | File | Responsibility |
|---|---|---|
| LangGraph Agent | `app/core/langgraph/graph.py` | Orchestrates the conversation loop |
| LLM Service | `app/services/llm/` | Model registry, retries, circular fallback, structured output |
| Memory Service | `app/services/memory.py` | mem0 semantic memory + cache |
| Session Naming | `app/services/session_naming.py` | Background LLM title generation for new sessions |
| Database Service | `app/services/database.py` | User/session CRUD |
| Cache Service | `app/core/cache.py` | Valkey/Redis with in-memory fallback |
| Middleware | `app/core/middleware.py` | Metrics, logging context, profiling |
| Auth | `app/api/v1/auth.py` | JWT creation, session management |
