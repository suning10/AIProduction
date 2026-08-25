# Tool-Call Loop Detection

## Overview

`_tool_call` (`app/core/langgraph/graph.py`) used to blindly execute whatever tool calls the model proposed, every round. The only guardrail was `MAX_TOOL_CALLS_PER_TURN`/`MAX_TOOL_CALLS_PER_WORKER` — a numeric ceiling that eventually forces a final answer, but does nothing to help the model notice *while still under budget* that it's stuck: calling the same tool with the same (or near-identical) args again, or oscillating between a small set of actions (A, B, A, B, ...). Every such repeat still costs a real external call (e.g. hitting DuckDuckGo again for the same query) for zero new information.

This adds action-history tracking so `_tool_call` recognizes when a proposed call has already been made — exactly or near-exactly — or is part of a repeating pattern, and short-circuits: reuse the cached result instead of re-executing, and append a corrective note so the model has a concrete signal to try something different, before it ever has to hit the numeric cap.

Applies to **both** the simple single-agent path and swarm workers (`docs/agent-swarm.md`) for free, since `_worker` calls `_tool_call` directly rather than duplicating its logic.

## What gets detected

| Pattern | Mechanism | Example |
|---|---|---|
| Exact repeat | Signature hash match | Same tool, byte-identical args, called twice |
| Near-duplicate | `difflib` string-similarity on args (≥ `TOOL_CALL_SIMILARITY_THRESHOLD`) | `"AI news today"` vs `"AI news todayy"` (typo) |
| Oscillation / cycle | Periodicity check on the signature sequence | A, B, A, B (period 2) |

## Data model

`ToolCallRecord` (`app/schemas/graph.py`) — one entry per executed (or reused) call:

```python
class ToolCallRecord(BaseModel):
    name: str
    args: dict
    signature: str
    result: str
```

`GraphState.action_history: list[ToolCallRecord]` accumulates these for the current turn (or, inside a worker, the current subtask run). No reducer annotation is needed — like `tool_call_count`, only `_tool_call` ever writes this field, one round at a time, so default replace-on-write semantics are correct. It's reset to `[]` at the start of every fresh (non-resumed) turn in `get_response`/`get_stream_response`, alongside `tool_call_count`/`subtasks`/`subtask_results`.

## Detection logic

Three small, dependency-free helpers in `app/utils/graph.py`:

```python
def compute_call_signature(name: str, args: dict) -> str:
    """Stable short hash of a canonicalized (tool name, args) pair."""
    canonical = json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

```python
def find_duplicate_call(name, args, history, similarity_threshold) -> Optional[ToolCallRecord]:
    """Exact signature match, or difflib ratio >= threshold, against same-tool history entries."""
```

```python
def detect_cycle(history, max_period=3, min_repeats=2) -> Optional[int]:
    """Checks periods 1-3 for a pattern repeated min_repeats times at the tail of the signature sequence."""
```

`find_duplicate_call` only compares args across calls to the *same tool name* — comparing a search query against an `ask_human` question wouldn't be meaningful. It compares the entire serialized args dict as one string, which works well for tools with a single string-ish field (`duckduckgo_search_tool`'s `query`, `ask_human`'s `question`); a tool with several unrelated fields would get noisier scores — a known limitation, not solved here.

`detect_cycle` requires 2 full repetitions of a pattern at the tail of history before flagging, so a period-1 check (`min_repeats=2`) already catches "the exact same call twice," while period 2-3 catches short oscillations without being trigger-happy on coincidence.

## Wired into `_tool_call`

```python
async def _execute_tool(tool_call: dict) -> tuple[ToolMessage, ToolCallRecord]:
    name, args = tool_call["name"], tool_call["args"]
    duplicate = find_duplicate_call(name, args, history, settings.TOOL_CALL_SIMILARITY_THRESHOLD)

    if duplicate is not None:
        result = duplicate.result
        content = (
            "[Note: this call repeats one you already made — reusing the previous result "
            f"instead of calling the tool again. Try a different approach.]\n\n{result}"
        )
    else:
        result = await self.tools_by_name[name].ainvoke(args)
        content = result

    record = ToolCallRecord(name=name, args=args, signature=compute_call_signature(name, args), result=result)
    return ToolMessage(content=content, name=name, tool_call_id=tool_call["id"]), record
```

After all of a round's calls resolve, the accumulated history is checked for a cycle:

```python
cycle_period = detect_cycle(updated_history)
if cycle_period is not None:
    warning = "\n\n[Note: you're repeating the same sequence of tool calls. Stop calling tools and answer with your best response now.]"
    outputs = [ToolMessage(content=str(o.content) + warning, name=o.name, tool_call_id=o.tool_call_id) for o in outputs]
```

The cycle warning is appended to the *existing* real `ToolMessage`s for that round — matching real `tool_call_id`s — rather than injected as a synthetic extra message. OpenAI's API requires every `ToolMessage` to correspond to a `tool_call_id` from the immediately preceding assistant message; a fabricated extra message would break that contract on the next LLM call.

## Design decisions

- **On detection: skip + reuse cached result + nudge, not an immediate forced cutoff.** The model gets one clear signal and a chance to self-correct; `MAX_TOOL_CALLS_PER_TURN`/`_WORKER` remain the hard backstop if it doesn't.
- **Local `difflib` heuristic, not embeddings, for near-duplicates.** Both are effectively free in dollar terms (`text-embedding-3-small`, already used for mem0, costs fractions of a cent), but embeddings add a network round-trip and a new failure mode to every tool-call attempt on a user-facing path. `difflib` is instant, in-process, and catches the common case — typo/rewording-level duplicates — without that cost. Deep paraphrases with low string overlap but high semantic overlap (e.g. "AI news" vs "latest artificial intelligence updates") would slip through; upgrading to embeddings later is a contained change at the same call site if that turns out to matter in practice.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `TOOL_CALL_SIMILARITY_THRESHOLD` | `0.9` | Minimum `difflib` ratio (0-1) for two calls' args to count as near-duplicates. |

## Verification

- `make lint` / `make typecheck`.
- Mocked runtime dry run (no live LLM/DB needed): patch `agent.tools_by_name` with an `AsyncMock`, call `_tool_call` twice with identical `tool_call` args — assert the mock's `.ainvoke` fires once, and the second `ToolMessage.content` contains the reuse note. Repeat with a one-character typo in the args to exercise the similarity path.
- Same setup alternating two different calls across 4 rounds (A, B, A, B) — assert `detect_cycle` fires with `period=2` on round 4 and the oscillation note is present.
- `make dev`, exercise a query likely to make the model retry a search via `/chat` — check logs for `duplicate_tool_call_detected` / `tool_call_cycle_detected` and confirm the final answer still makes sense.
