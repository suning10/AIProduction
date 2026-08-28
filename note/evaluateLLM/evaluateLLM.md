# Summary

## how to evaluate a LLM / Agent

Common Steps:  \
1. Fetch Traces
2. Define Scores 
3. LLM as Judge 
4. Report 

Use Langfuse  \
Step 1: Set up LangFuse
- opneAI build-in
- Decorators [decorator](#decorators)
- use callback, see [graph](../../app/core/langgraph/graph.py) line 598
  - call back set up [callback](../../app/core/observability.py) 

Step 2: Define Scores
- each metrics have its own prompt (for llm to judge)
  - see [prompt](../../evals/metrics)
  - helpfulness, relevancy, conciseness, hallucination(how much make up), toxicity

Step 3: Use LLM as judge




### decorators
```python
from langfuse.decorators import observe, langfuse_context
from langfuse.openai import openai

@observe()  # Traces this function
def call_llm(prompt: str):
    response = openai.OpenAI().chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

@observe()  # Parent trace
def my_pipeline(user_input: str):
    # Add metadata
    langfuse_context.update_current_trace(
        user_id="user_123",
        session_id="session_abc",
        tags=["production"]
    )
    
    result = call_llm(user_input)
    return result

# Run it
output = my_pipeline("What is AI?")
```

### LLM as judge
```python
        num_retries = 3
        for _ in range(num_retries):
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=settings.EVALUATION_LLM,
                    messages=[
                        {"role": "system", "content": metric_system_prompt},
                        {"role": "user", "content": f"Input: {input}\nGeneration: {output}"},
                    ],
                    response_format=ScoreSchema,
                )
                return response.choices[0].message.parsed
```