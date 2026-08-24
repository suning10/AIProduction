# Summary

## Agent Runs into Infinite Loop
1. how to detect 
   2. Three different types
      3. AAA -> Repetition
      4. ABA -> Oscillation 
      5. ABCABC -> Cycle
      6. keep trying a tool 

## Ways to Detect 
1. Action History Tracking [action](#action-history)
   2. AAA 
      3. compare last 
   4. ABA
      5. Using Sliding Window [-n:] 
         6. Oven[0::2]
         7. Odd [1::2]
   8. ABC
   
2. Semantic Similarity Detection - Embedding [semantic](#semantic-similarity-dection)
3. State Hash
   4. what to hash 
      5. tool name
      6. tool args (normalized) [normalize](#normalize-tools-args)

## how to mitigate

1. inject prompt 
   2. detect you are running into loop 
3. Backtrack 
   4. go back to last checkpoint and start a new route
5. Escalation 
   6. ask human review 


### decision see claude answer below [mitigate](#mitigate)
```markdown
Loop Detected
     │
     ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 1st detection  │ ──────────────────►│   Continue   │
│ Prompt inject  │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 2nd detection  │ ──────────────────►│   Continue   │
│ Block + reword │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 3rd detection  │ ──────────────────►│   Continue   │
│ Backtrack      │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 4th detection  │ ──────────────────►│   Continue   │
│ Supervisor LLM │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐
│  Hard Stop     │ ──► Return best answer so far
└────────────────┘
```
```markdown
Each Agent Step
      │
      ▼
┌─────────────────────────────────┐
│  Record action + state + result  │
└────────────┬────────────────────┘
             │
      ┌──────▼──────┐
      │ Hard limits? │ ──YES──► STOP immediately
      │ (max steps)  │
      └──────┬───────┘
             │ NO
      ┌──────▼──────────────┐
      │ Structural patterns? │ ──YES──► Inject correction prompt
      │ (repeat/oscillation) │          or force new strategy
      └──────┬──────────────┘
             │ NO
      ┌──────▼──────────┐
      │ Semantic repeat? │ ──YES──► Rephrase query / change tool
      └──────┬───────────┘
             │ NO
      ┌──────▼──────────┐
      │ Result stagnant? │ ──YES──► Escalate / ask clarification
      └──────┬───────────┘
             │ NO
             ▼
       Continue normally
```







### normalize tools args
```python
import json, hashlib, re

def normalize_tool_call(tool: str, args: dict) -> dict:
    """
    Normalize before hashing so semantically-same calls
    produce the same hash
    """
    normalized_args = {}

    for key, value in args.items():
        if isinstance(value, str):
            value = value.lower().strip()
            value = re.sub(r'\s+', ' ', value)      # collapse whitespace
            value = re.sub(r'[^\w\s]', '', value)   # remove punctuation
        elif isinstance(value, list):
            value = sorted([str(v).lower() for v in value])  # sort lists
        elif isinstance(value, dict):
            value = dict(sorted(value.items()))      # sort dict keys
        normalized_args[key] = value

    return {
        "tool": tool.lower(),
        "args": dict(sorted(normalized_args.items()))  # sort top-level keys
    }

# Example:
# search_web(query="Python Tutorials ")
# search_web(query="python tutorials")
# → same hash ✅

# search_web(query="Python Tutorials", limit=10)
# search_web(query="Python Tutorials", limit=5)
# → different hash ✅ (limit matters)
```

### Action History
```python
from collections import deque, Counter
from dataclasses import dataclass, field
from typing import Any

@dataclass
class AgentAction:
    tool: str
    args: dict
    result: Any = None
    timestamp: float = 0.0

class LoopDetector:
    def __init__(self, window_size: int = 10):
        self.history = deque(maxlen=window_size)
        self.window_size = window_size

    def record(self, action: AgentAction):
        self.history.append(action)

    def check_loops(self) -> dict:
        return {
            "exact_repeat":     self._detect_exact_repeat(),
            "oscillation":      self._detect_oscillation(),
            "cycle":            self._detect_cycle(),
            "same_tool_flood":  self._detect_same_tool_flood(),
        }

    def _detect_exact_repeat(self, threshold=3) -> bool:
        """Same tool + same args called N times"""
        if len(self.history) < threshold:
            return False
        last = list(self.history)[-threshold:]
        first = last[0]
        return all(
            a.tool == first.tool and a.args == first.args
            for a in last
        )

    def _detect_oscillation(self) -> bool:
        """A→B→A→B pattern"""
        h = [a.tool for a in self.history]
        if len(h) < 4:
            return False
        # Check last 6 actions for A,B,A,B,A,B pattern
        window = h[-6:]
        evens = window[0::2]
        odds  = window[1::2]
        return (
            len(set(evens)) == 1 and
            len(set(odds))  == 1 and
            evens[0] != odds[0]
        )

    def _detect_cycle(self, min_cycle_len=2, repeats=2) -> bool:
        """Detect repeating subsequences A→B→C→A→B→C"""
        tools = [a.tool for a in self.history]
        n = len(tools)
        for cycle_len in range(min_cycle_len, n // repeats + 1):
            pattern = tools[-cycle_len:]
            before  = tools[-(cycle_len * repeats):-cycle_len]
            if pattern == before:
                return True
        return False

    def _detect_same_tool_flood(self, threshold=0.8) -> bool:
        """One tool dominates > 80% of recent calls"""
        if len(self.history) < 5:
            return False
        tools = [a.tool for a in self.history]
        most_common_count = Counter(tools).most_common(1)[0][1]
        return (most_common_count / len(tools)) >= threshold
```

### Semantic Similarity Dection
```python
from sentence_transformers import SentenceTransformer
import numpy as np

class SemanticLoopDetector:
    def __init__(self, similarity_threshold=0.95):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.embeddings = []
        self.threshold = similarity_threshold

    def is_semantic_repeat(self, new_query: str, last_n=5) -> bool:
        """Check if query is semantically similar to recent ones"""
        new_emb = self.model.encode(new_query)

        for past_emb in self.embeddings[-last_n:]:
            similarity = np.dot(new_emb, past_emb) / (
                np.linalg.norm(new_emb) * np.linalg.norm(past_emb)
            )
            if similarity >= self.threshold:
                return True

        self.embeddings.append(new_emb)
        return False

# Usage
detector = SemanticLoopDetector()
queries = [
    "search for Python tutorials",
    "find Python learning resources",   # semantically same!
    "Python tutorial search",           # semantically same!
]
for q in queries:
    print(f"'{q}' is repeat: {detector.is_semantic_repeat(q)}")
```


# mitigate

## Mitigation Ladder (Escalating Responses)

```
Detection Severity     Response
──────────────────────────────────────────────────────
1st occurrence    →   Soft nudge (prompt injection)
2nd occurrence    →   Force strategy change
3rd occurrence    →   Backtrack to last good state
4th occurrence    →   Escalate to human / supervisor
Hard limit hit    →   Emergency stop, return best answer
```

---

## Strategy 1: Prompt Injection (Softest)

Tell the agent what it's doing wrong and what to try instead:

```python
LOOP_CORRECTION_PROMPTS = {
    "exact_repeat": """
⚠️ You have called `{tool}` with the same arguments {count} times.
The result is not changing. Do NOT call it again.

What you've tried: {history_summary}
What you must do now: Use a DIFFERENT approach entirely.
Available alternatives: {available_tools}
""",

    "oscillation": """
⚠️ You are alternating between `{tool_a}` and `{tool_b}` repeatedly.
This loop has occurred {count} times with no progress.

Break out by:
1. Combining results from both tools you already have
2. Trying a completely different tool: {other_tools}
3. Answering with partial information if stuck
""",

    "stagnation": """
⚠️ You have taken {count} steps but made no progress toward the goal.
Goal: {goal}
Progress so far: {progress_summary}

You must either:
- Decompose the goal differently
- Ask for clarification
- Return your best answer with what you have
""",
}

class PromptInjector:
    def inject(self,
               loop_type: str,
               context: dict,
               system_prompt: str) -> str:

        template = LOOP_CORRECTION_PROMPTS.get(loop_type, "")
        correction = template.format(**context)

        return f"""
{system_prompt}

{'─' * 50}
LOOP GUARD INTERVENTION:
{correction}
{'─' * 50}
"""

    def inject_into_messages(self,
                              messages: list,
                              loop_type: str,
                              context: dict) -> list:
        """Insert correction as a system message before last user message"""
        correction = LOOP_CORRECTION_PROMPTS.get(loop_type, "").format(**context)

        correction_message = {
            "role": "system",
            "content": f"[LOOP GUARD]: {correction}"
        }

        # Insert before the last user message
        insert_at = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if messages[i]["role"] == "user"),
            len(messages)
        )

        return messages[:insert_at] + [correction_message] + messages[insert_at:]
```

---

## Strategy 2: Force Strategy Change

Blacklist what's been tried and enforce alternatives:

```python
from enum import Enum

class ForceStrategy(Enum):
    BLOCK_TOOL         = "block_tool"
    REQUIRE_TOOL       = "require_tool"
    CHANGE_QUERY       = "change_query"
    CHANGE_APPROACH    = "change_approach"

class StrategyForcer:
    def __init__(self):
        self.blocked_tools:    set  = set()
        self.blocked_args:     list = []   # (tool, args) pairs
        self.required_next:    str | None  = None
        self.tried_strategies: list = []

    def block_current_approach(self, tool: str, args: dict):
        """Prevent exact repetition"""
        self.blocked_args.append((tool, json.dumps(args, sort_keys=True)))

    def block_tool_entirely(self, tool: str):
        """When a tool keeps failing, remove it"""
        self.blocked_tools.add(tool)

    def require_next_tool(self, tool: str):
        """Force agent to use a specific tool next"""
        self.required_next = tool

    def is_blocked(self, tool: str, args: dict) -> tuple[bool, str]:
        if tool in self.blocked_tools:
            return True, f"Tool '{tool}' is blocked (repeatedly failed)"

        args_key = json.dumps(args, sort_keys=True)
        if (tool, args_key) in self.blocked_args:
            return True, f"This exact call to '{tool}' was already tried"

        return False, ""

    def get_forced_tool(self) -> str | None:
        tool = self.required_next
        self.required_next = None  # consume it
        return tool

    def get_allowed_tools(self, all_tools: list) -> list:
        return [t for t in all_tools if t not in self.blocked_tools]


class QueryReformulator:
    """Automatically rephrase queries to break out of loops"""

    REFORMULATION_PROMPT = """
The following query failed to get useful results:
Original: "{original_query}"

Rewrite it {n} different ways. Be specific, use synonyms,
change the angle of the question:
Return as JSON list: ["query1", "query2", ...]
"""

    def __init__(self, llm_client):
        self.llm = llm_client
        self.used_queries: set = set()

    def reformulate(self, original: str, n: int = 3) -> list[str]:
        response = self.llm.complete(
            self.REFORMULATION_PROMPT.format(
                original_query=original, n=n
            )
        )
        candidates = json.loads(response)

        # Filter already-tried queries
        fresh = [q for q in candidates if q not in self.used_queries]
        self.used_queries.add(original)
        return fresh

    def next_query(self, original: str) -> str | None:
        fresh = self.reformulate(original, n=3)
        return fresh[0] if fresh else None
```

---

## Strategy 3: Backtracking

Roll back to the last known good checkpoint:

```python
import copy
from dataclasses import dataclass, field

@dataclass
class Checkpoint:
    step: int
    state: dict
    memory: dict
    messages: list
    result_so_far: any
    score: float = 0.0     # how "good" was this state

class BacktrackManager:
    def __init__(self, max_checkpoints: int = 5):
        self.checkpoints: list[Checkpoint] = []
        self.max_checkpoints = max_checkpoints

    def save(self, step: int, state: dict, memory: dict,
             messages: list, result: any, score: float = 0.0):

        checkpoint = Checkpoint(
            step=step,
            state=copy.deepcopy(state),
            memory=copy.deepcopy(memory),
            messages=copy.deepcopy(messages),
            result_so_far=copy.deepcopy(result),
            score=score,
        )
        self.checkpoints.append(checkpoint)

        # Keep only N checkpoints
        if len(self.checkpoints) > self.max_checkpoints:
            self.checkpoints.pop(0)

    def backtrack(self,
                  strategy: str = "last_good") -> Checkpoint | None:
        if not self.checkpoints:
            return None

        if strategy == "last":
            # Just go back one step
            return self.checkpoints[-1]

        elif strategy == "last_good":
            # Go back to highest scoring checkpoint
            return max(self.checkpoints, key=lambda c: c.score)

        elif strategy == "before_loop":
            # Go back to before the loop started (first checkpoint)
            return self.checkpoints[0]

        return self.checkpoints[-1]

    def backtrack_with_hint(self,
                             strategy: str = "last_good") -> dict | None:
        checkpoint = self.backtrack(strategy)
        if not checkpoint:
            return None

        return {
            "state":    checkpoint.state,
            "memory":   checkpoint.memory,
            "messages": checkpoint.messages + [{
                "role": "system",
                "content": (
                    f"[BACKTRACK] Restored to step {checkpoint.step}. "
                    "Previous approach failed. Try a different strategy."
                )
            }],
            "result_so_far": checkpoint.result_so_far,
        }
```

---

## Strategy 4: Escalation

When the agent can't solve it alone:

```python
from enum import Enum

class EscalationLevel(Enum):
    SELF_CORRECT    = 1   # agent tries to fix itself
    SUPERVISOR      = 2   # supervisor agent reviews
    HUMAN_IN_LOOP   = 3   # ask human for guidance
    HARD_STOP       = 4   # give up, return best answer

class EscalationHandler:
    def __init__(self, llm_client, human_callback=None):
        self.llm = llm_client
        self.human_callback = human_callback

    async def escalate(self,
                       level: EscalationLevel,
                       context: dict) -> dict:

        if level == EscalationLevel.SELF_CORRECT:
            return await self._self_correct(context)

        elif level == EscalationLevel.SUPERVISOR:
            return await self._supervisor_review(context)

        elif level == EscalationLevel.HUMAN_IN_LOOP:
            return await self._ask_human(context)

        elif level == EscalationLevel.HARD_STOP:
            return self._hard_stop(context)

    async def _self_correct(self, context: dict) -> dict:
        """Agent reflects on its own failure"""
        prompt = f"""
You are reviewing your own failed reasoning process.

Goal: {context['goal']}
Steps taken: {context['history_summary']}
Why it failed: {context['loop_type']} loop detected

Write a new plan that avoids the same mistakes.
Return JSON: {{"new_plan": [...], "reasoning": "..."}}
"""
        response = await self.llm.complete(prompt)
        return {"action": "retry", "plan": json.loads(response)}

    async def _supervisor_review(self, context: dict) -> dict:
        """Separate supervisor LLM reviews and decides"""
        prompt = f"""
You are a supervisor reviewing a stuck AI agent.

Agent goal:    {context['goal']}
Loop detected: {context['loop_type']}
History:       {context['history_summary']}
Best result:   {context['best_result_so_far']}

Decide what the agent should do next.
Options: retry_differently | decompose_goal | answer_partial | stop
Return JSON: {{"decision": "...", "instruction": "..."}}
"""
        response = await self.llm.complete(prompt)
        decision = json.loads(response)

        if decision["decision"] == "stop":
            return self._hard_stop(context)

        return {"action": "retry", "instruction": decision["instruction"]}

    async def _ask_human(self, context: dict) -> dict:
        """Pause and ask human for clarification"""
        if not self.human_callback:
            return self._hard_stop(context)

        question = (
            f"Agent is stuck on: '{context['goal']}'\n"
            f"It tried: {context['history_summary']}\n"
            f"What should it do? (or type 'stop')"
        )
        human_response = await self.human_callback(question)

        if human_response.lower() == "stop":
            return self._hard_stop(context)

        return {
            "action": "retry",
            "human_guidance": human_response
        }

    def _hard_stop(self, context: dict) -> dict:
        """Return whatever we have"""
        return {
            "action":  "stop",
            "result":  context.get("best_result_so_far"),
            "reason":  "loop_unresolved",
            "message": (
                f"Could not complete goal '{context['goal']}' after "
                f"{context['step_count']} steps. "
                f"Best result: {context.get('best_result_so_far', 'none')}"
            )
        }
```

---

## The Circuit Breaker: Composing All Strategies

```python
class AgentCircuitBreaker:
    """
    Coordinates all mitigation strategies with progressive escalation.
    Plug this into any agent's step() loop.
    """

    def __init__(self, llm_client, human_callback=None):
        self.injector    = PromptInjector()
        self.forcer      = StrategyForcer()
        self.backtracker = BacktrackManager()
        self.escalator   = EscalationHandler(llm_client, human_callback)
        self.reformulator = QueryReformulator(llm_client)

        self.loop_count  = 0          # consecutive loop detections
        self.all_tools: list = []

    async def handle(self,
                     detection: dict,
                     agent_context: dict) -> dict:
        """
        Call this when a loop is detected.
        Returns instructions for the agent's next action.
        """
        if not detection["should_stop"]:
            return {"action": "continue"}

        self.loop_count += 1
        issues    = detection["issues"]
        loop_type = issues[0] if issues else "unknown"

        print(f"[CircuitBreaker] Loop #{self.loop_count}: {issues}")

        # ── Level 1: Soft correction ────────────────────────────────
        if self.loop_count == 1:
            return self._level1_soft_correct(loop_type, agent_context)

        # ── Level 2: Force strategy change ──────────────────────────
        elif self.loop_count == 2:
            return self._level2_force_change(loop_type, agent_context)

        # ── Level 3: Backtrack ───────────────────────────────────────
        elif self.loop_count == 3:
            return self._level3_backtrack(agent_context)

        # ── Level 4: Escalate ────────────────────────────────────────
        elif self.loop_count == 4:
            return await self._level4_escalate(agent_context)

        # ── Level 5: Hard stop ───────────────────────────────────────
        else:
            return await self.escalator.escalate(
                EscalationLevel.HARD_STOP, agent_context
            )

    def _level1_soft_correct(self,
                              loop_type: str,
                              ctx: dict) -> dict:
        """Inject correction prompt, let agent self-correct"""
        new_messages = self.injector.inject_into_messages(
            messages=ctx["messages"],
            loop_type=loop_type,
            context={
                "tool":             ctx.get("last_tool"),
                "count":            self.loop_count,
                "history_summary":  ctx.get("history_summary"),
                "available_tools":  self.all_tools,
                "tool_a":           ctx.get("oscillating_a"),
                "tool_b":           ctx.get("oscillating_b"),
                "other_tools":      ctx.get("other_tools"),
                "goal":             ctx.get("goal"),
                "progress_summary": ctx.get("progress_summary"),
            }
        )
        return {
            "action":   "retry_with_new_messages",
            "messages": new_messages,
            "reason":   f"soft_correct:{loop_type}",
        }

    def _level2_force_change(self,
                              loop_type: str,
                              ctx: dict) -> dict:
        """Block current tool/args, optionally reformulate query"""
        # Block what's been tried
        self.forcer.block_current_approach(
            ctx["last_tool"], ctx["last_args"]
        )

        result = {
            "action":        "force_strategy",
            "blocked_tools": list(self.forcer.blocked_tools),
            "blocked_args":  self.forcer.blocked_args,
            "reason":        "force_change",
        }

        # Try reformulating the query
        if "query" in ctx.get("last_args", {}):
            new_query = self.reformulator.next_query(
                ctx["last_args"]["query"]
            )
            if new_query:
                result["forced_args"] = {**ctx["last_args"],
                                          "query": new_query}

        # Force a different tool if oscillating
        if loop_type == "LOOP_OSCILLATION":
            other = self.forcer.get_allowed_tools(self.all_tools)
            if other:
                result["forced_tool"] = other[0]

        return result

    def _level3_backtrack(self, ctx: dict) -> dict:
        """Roll back to last good state"""
        restored = self.backtracker.backtrack_with_hint("last_good")

        if not restored:
            return {
                "action": "retry_with_new_messages",
                "messages": ctx["messages"],
                "reason": "backtrack_failed_no_checkpoint",
            }

        # Reset loop count since we're starting fresh
        self.loop_count = 0

        return {
            "action":   "backtrack",
            "restored": restored,
            "reason":   "backtrack_to_last_good",
        }

    async def _level4_escalate(self, ctx: dict) -> dict:
        """Bring in supervisor or human"""
        return await self.escalator.escalate(
            EscalationLevel.SUPERVISOR, ctx
        )
```

---

## Wiring It Into Your Agent Loop

```python
class LoopResilientAgent:
    def __init__(self, llm_client, tools: dict):
        self.llm          = llm_client
        self.tools        = tools
        self.detector     = AgentLoopGuard(max_steps=30)
        self.breaker      = AgentCircuitBreaker(llm_client)
        self.breaker.all_tools = list(tools.keys())
        self.messages     = []
        self.memory       = {}
        self.step         = 0

    async def run(self, goal: str) -> str:
        self.messages = [{"role": "user", "content": goal}]

        while True:
            # ── Agent decides next action ────────────────────────────
            response   = await self.llm.complete(self.messages)
            tool, args = self._parse_tool_call(response)

            # ── Execute tool ─────────────────────────────────────────
            blocked, reason = self.breaker.forcer.is_blocked(tool, args)
            if blocked:
                self.messages.append({
                    "role":    "system",
                    "content": f"[BLOCKED] {reason}. Try another approach."
                })
                continue

            result = await self.tools[tool](**args)
            self.step += 1

            # ── Save checkpoint every N steps ────────────────────────
            if self.step % 3 == 0:
                self.breaker.backtracker.save(
                    step=self.step,
                    state={"tool": tool, "args": args},
                    memory=self.memory,
                    messages=self.messages,
                    result=result,
                    score=self._score_progress(result, goal),
                )

            # ── Detect loops ─────────────────────────────────────────
            from_detector = self.detector.step(
                AgentAction(tool=tool, args=args, result=result),
                state={"goal": goal, "tool": tool, "args": args,
                       "memory": self.memory},
                result=result,
            )

            # ── Mitigate if looping ───────────────────────────────────
            if from_detector["should_stop"]:
                ctx = {
                    "goal":              goal,
                    "last_tool":         tool,
                    "last_args":         args,
                    "messages":          self.messages,
                    "history_summary":   self._summarize_history(),
                    "best_result_so_far": self._best_result(),
                    "step_count":        self.step,
                }
                mitigation = await self.breaker.handle(from_detector, ctx)

                if mitigation["action"] == "stop":
                    return mitigation["result"]                 # ← exit

                elif mitigation["action"] == "backtrack":
                    restored = mitigation["restored"]
                    self.messages = restored["messages"]        # ← restore
                    self.memory   = restored["memory"]

                elif mitigation["action"] == "force_strategy":
                    if "forced_args" in mitigation:
                        args = mitigation["forced_args"]
                    if "forced_tool" in mitigation:
                        tool = mitigation["forced_tool"]

                elif mitigation["action"] == "retry_with_new_messages":
                    self.messages = mitigation["messages"]      # ← new prompt

                continue  # retry with mitigated state

            # ── Check if done ─────────────────────────────────────────
            if self._is_complete(result, goal):
                return result

            # ── Append result and continue ────────────────────────────
            self.messages.append({
                "role":    "tool",
                "content": str(result),
            })
```

---

## Decision Flow Summary

```
Loop Detected
     │
     ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 1st detection  │ ──────────────────►│   Continue   │
│ Prompt inject  │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 2nd detection  │ ──────────────────►│   Continue   │
│ Block + reword │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 3rd detection  │ ──────────────────►│   Continue   │
│ Backtrack      │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐      resolved      ┌──────────────┐
│ 4th detection  │ ──────────────────►│   Continue   │
│ Supervisor LLM │                    └──────────────┘
└────────┬───────┘
         │ still looping
         ▼
┌────────────────┐
│  Hard Stop     │ ──► Return best answer so far
└────────────────┘
```

---

## Quick Reference

| Detection | Best Mitigation | Why |
|---|---|---|
| Exact repeat | Block args + reformulate query | Same call = same result |
| Oscillation | Block both tools, force third | Breaking the A↔B cycle |
| Stagnation | Backtrack + new plan | Progress is flat |
| Cycle (A→B→C) | Supervisor review | Complex, needs judgment |
| Max steps hit | Hard stop | Time/cost protection |
| Result empty | Widen query scope | Too narrow search |
| Result unchanged | Change data source | Source has no answer |