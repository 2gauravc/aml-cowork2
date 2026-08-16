# LangSmith tracing

LangSmith is the CDD runtime observability system. It records LangGraph run and
node latency, errors, and nested OpenAI Responses API calls. It is not CDD
evidence and no LangSmith trace is stored in completed CDD state.

Tracing is opt-in. Configure the runtime environment:

```text
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=onbo
```

If `LANGSMITH_TRACING` is not truthy or `LANGSMITH_API_KEY` is absent, the
application uses normal LangGraph/OpenAI clients and emits no LangSmith trace.

CDD inputs, prompts, document extracts, and outputs can contain sensitive
customer data. Before enabling tracing outside development, configure and
approve LangSmith input/output/metadata redaction, access control, region, and
retention. Do not use trace data as compliance evidence or copy it into CDD
state.
