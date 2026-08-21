# Summary

## use trimmed message 
- use to control max token allowed when passing to LLM 

```text
 Args:
        messages: Sequence of Message-like objects to trim.
        max_tokens: Max token count of trimmed messages.
        token_counter: Function or llm for counting tokens in a `BaseMessage` or a
            list of `BaseMessage`.

            If a `BaseLanguageModel` is passed in then
            `BaseLanguageModel.get_num_tokens_from_messages()` will be used. Set to
            `len` to count the number of **messages** in the chat history.

            You can also use string shortcuts for convenience:

            - `'approximate'`: Uses `count_tokens_approximately` for fast, approximate
                token counts.

            !!! note

                `count_tokens_approximately` (or the shortcut `'approximate'`) is
                recommended for using `trim_messages` on the hot path, where exact token
                counting is not necessary.
            strategy: Strategy for trimming.

            - `'first'`: Keep the first `<= n_count` tokens of the messages.
            - `'last'`: Keep the last `<= n_count` tokens of the messages.
        allow_partial: Whether to split a message if only part of the message can be
            included.

            If `strategy='last'` then the last partial contents of a message are
            included. If `strategy='first'` then the first partial contents of a
            message are included.
        end_on: The message type to end on.

            If specified then every message after the last occurrence of this type is
            ignored. If `strategy='last'` then this is done before we attempt to get the
            last `max_tokens`. If `strategy='first'` then this is done after we get the
            first `max_tokens`. Can be specified as string names (e.g. `'system'`,
            `'human'`, `'ai'`, ...) or as `BaseMessage` classes (e.g. `SystemMessage`,
            `HumanMessage`, `AIMessage`, ...). Can be a single type or a list of types.

        start_on: The message type to start on.

            Should only be specified if `strategy='last'`. If specified then every
            message before the first occurrence of this type is ignored. This is done
            after we trim the initial messages to the last `max_tokens`. Does not apply
            to a `SystemMessage` at index 0 if `include_system=True`. Can be specified
            as string names (e.g. `'system'`, `'human'`, `'ai'`, ...) or as
            `BaseMessage` classes (e.g. `SystemMessage`, `HumanMessage`, `AIMessage`,
            ...). Can be a single type or a list of types.

        include_system: Whether to keep the `SystemMessage` if there is one at index
            `0`.

            Should only be specified if `strategy="last"`.
        text_splitter: Function or `langchain_text_splitters.TextSplitter` for
            splitting the string contents of a message.

            Only used if `allow_partial=True`. If `strategy='last'` then the last split
            tokens from a partial message will be included. if `strategy='first'` then
            the first split tokens from a partial message will be included. Token
            splitter assumes that separators are kept, so that split contents can be
            directly concatenated to recreate the original text. Defaults to splitting
            on newlines.
```