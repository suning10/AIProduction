# Summary

## how to save token

- why:
  - load too many tools
    - to solve: dynamically load tools
    - retrieve and bind pattern
      - LangChian: tools select middleware
      - LangGraph, use conditional node
        - let LLM analyze questions first, then load tools dynamically
      - MCP
        - list tools and choose tools needed

  - API returns too many data
    - returned JSON contains too many data
    - LLM consumes token to process it
    - To solve
      - Let LLM run in a sandbox environment
      - write query and summarize its findings

  - Long conversation
    - save older messages into vector db
      - used when needed
    - only save recent messages
