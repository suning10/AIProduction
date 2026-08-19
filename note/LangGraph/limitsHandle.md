# Summary

## how to handle recursive call limits
- can't have tool call iteratively
- langgraph have a limit of 25 round

### Two Solutions
- add recursive_limits in config(RunnableConfig)
- add count, append user message

Claude's Plan

```text
- app/core/config.py — new MAX_TOOL_CALLS_PER_TURN setting (env-overridable, defaults to 5).
- app/schemas/graph.py — GraphState.tool_call_count tracks tool-call rounds within a turn.
  - app/core/langgraph/graph.py:
   - _tool_call increments tool_call_count each round.
    - _chat checks the count against the cap; once reached, it appends a user-role nudge ("summarize your findings, don't call more tools") and routes the LLM call through model_name=..., which bypasses bind_tools entirely — the
  model literally has no tool schema for that call, so it can't emit tool_calls, and goto is forced to END.
    - get_response/get_stream_response reset tool_call_count: 0 on fresh turns (not on interrupt-resume, so a human-in-the-loop pause doesn't lose its budget).
```

```text
  Then call the LLM. Two design choices to flag:

  - Prompt-only (your literal ask) — keep tools bound, add the nudge, hope the model complies, and still force goto=END regardless of what comes back.
    - Risk: if the model ignores the nudge and emits tool_calls anyway, we'd either have to execute one more round (defeating the cap) or discard an AIMessage that has tool_calls with no matching ToolMessage — that's an invalid
  message sequence and will break the next turn when the full history gets replayed to OpenAI (tool_calls must be followed by tool results).
  - Prompt + mechanical guarantee (what I'd recommend) — same nudge message, but also make this one call via llm_service.call(messages, model_name=model_name) instead of the default self.llm_service.call(messages). Passing model_name
  routes through LLMService's "override path" (service.py:267-286), which builds the model fresh from LLMRegistry without bind_tools ever being applied — so the model has no tool schema and structurally cannot return tool_calls. The
  nudge message then does its intended job (steering what it says), while the missing tool schema guarantees that it can't call a tool, avoiding the dangling-tool-call problem entirely. Always goto=END after this call.
```
