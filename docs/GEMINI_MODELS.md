# Gemini configuration

Checked against the official Gemini API docs and this API account on 2026-09-13.
One backend `GEMINI_API_KEY` supports Freya's Gemini features. Separate
`GEMINI_AGENT_API_KEY` and `GEMINI_MEMORY_API_KEY` are optional quota isolation.

| Role | Default |
| --- | --- |
| Missions, agents, browser, vision, Trading Lab | `gemini-3.5-flash` |
| Verification, context drafts, memory extraction, browser fallback | `gemini-3.5-flash-lite` |
| Conversational voice | `gemini-3.1-flash-live-preview` |
| Existing retrieval memory embeddings | `gemini-embedding-001` |

Gemini 3.8 Flash is the newest listed Flash model and was visible to this API
account, but repeated live generation attempts returned HTTP 503 high-demand
errors. Gemini 3.5 Flash successfully returned a locally validated chart analysis,
so it is the working default. Explicit model overrides remain available.

Configuration loading migrates moving Flash aliases and known retired model IDs
in model fields without rewriting personal configuration or prompt text. Supported
explicit pins such as Gemini 2.5 Flash remain valid; Google has not announced its
shutdown. New model defaults also apply to installations without a trading section.

The embedding model stays unchanged to preserve the meaning of stored vectors.
Google lists its earliest shutdown as May 14, 2028. Switching to embedding-2 needs
a separate full reindex, not just a model-name replacement.

Trading analysis defaults to Gemini in HTTP, voice and the UI. OpenAI requires an
explicitly configured model and backend API key and explicit selection. No Gemini
failure triggers OpenAI. Offline lessons remain an explicit no-AI option.
Public market data requests still use the market-data source; they are not AI
provider requests. Trading images use the same Gemini multimodal model.

References:

- [Gemini model catalog](https://ai.google.dev/gemini-api/docs/models)
- [Deprecations and shutdown schedule](https://ai.google.dev/gemini-api/docs/deprecations)
- [Thinking configuration](https://ai.google.dev/gemini-api/docs/thinking)
- [Live API](https://ai.google.dev/gemini-api/docs/live-api)
