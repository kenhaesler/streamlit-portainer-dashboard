# LLM Context Management Strategies

Large language models (LLMs) such as the ones exposed through Ollama have fixed context windows. When you exceed that window the model begins to forget older tokens or fails altogether. The strategies below outline architectural approaches that keep a conversation productive without constantly hitting the limit.

## 1. Build a Retrieval Layer for Long-Term Memory
- **Structured storage**: Persist prior interactions or domain documents in a vector store (FAISS, ChromaDB, LanceDB) or even a relational database when metadata is more important than semantic search.
- **Hybrid retrieval**: Combine vector similarity with keyword or metadata filters so you only surface the most relevant chunks for the current user prompt.
- **Chunking guidance**: Pre-split documents into 500–1500 token passages, store embeddings per chunk, and keep references back to the source so you can cite or refresh data later.

At runtime, turn the user prompt (plus optional conversation summary) into a search query, pull only the top `k` chunks, and compose a prompt template that injects those snippets. This keeps the live conversation inside the context window while still giving the assistant deep knowledge.

## 2. Summarise Conversation History
- **Rolling summary**: Keep a running synopsis of the chat that you update every few turns. Store the full history separately for audit purposes, but only feed the latest summary and the last few raw turns back to the model.
- **Map–reduce summarisation**: For very long histories, summarise in stages—summaries of each segment followed by a higher-level synthesis. Updating the top-level summary only when the topic shifts reduces computation.
- **User intent extraction**: Track explicit goals, preferences, or constraints in structured fields (e.g., JSON) derived from the conversation. Inject just those fields into later prompts instead of lengthy dialogue.

## 3. Use Tooling and Function Calling
- **External tools**: Offload calculations, lookups, or data transforms to deterministic services or scripts. The LLM only receives the results, which are much shorter than raw datasets.
- **Function-call planning**: Let the model emit structured intents (tool name + arguments). The orchestrator executes the tool and feeds the response back. This breaks tasks into smaller, context-friendly exchanges.

## 4. Stage Requests Across Multiple Prompts
- **Hierarchical prompting**: First ask the model to outline an approach, then feed the outline (or pieces of it) into follow-up prompts for expansion. Each step stays within the window.
- **Iterative refinement**: Instead of sending an entire document, iteratively ask the model to improve or comment on individual sections. Maintain state in your application logic.

## 5. Guardrails and Budgeting
- **Token accounting**: Estimate prompt sizes before sending them. Libraries such as `tiktoken` can predict token counts so you can trim or summarise proactively.
- **Adaptive truncation**: If a prompt risks overflow, fall back to a shorter set of retrieved chunks or more aggressive summarisation.
- **User feedback**: Inform users when the system had to drop context, and offer links to the archived full history when appropriate.

## 6. Streaming and Incremental Generation
- **Chunked output processing**: Stream model output and, if needed, summarise intermediate results while the generation is still running.
- **Stateful pipelines**: Combine summarised prior steps with new user input to iteratively refine the final answer without re-sending the entire history each time.

## 7. Persistent Knowledge Bases
When users frequently refer to the same documents or project state, ingest them once into your retrieval layer. Teach the application to refresh embeddings whenever the source changes, and to cite sources so the model’s answers remain auditable.

---

Implementing even two or three of these patterns will usually keep your Ollama-powered assistant under the context limit while delivering more consistent answers.

## Where to Start: Strategies You Can DIY

If you are wondering which ideas deliver the fastest payoff without introducing heavy infrastructure, focus on the following:

1. **Summarise conversation history** – Storing a rolling summary plus the last few verbatim turns can live entirely inside your application code and a lightweight database (even SQLite). Implementing this pattern usually takes only a small helper function to maintain the summary and a guard that trims the raw transcript.
2. **Stage requests across multiple prompts** – Prompt decomposition is an orchestration problem, not a tooling one. You can experiment with multi-step prompting today by adding new controller logic that sends an outline prompt, captures the reply, and issues follow-up prompts for each section.
3. **Token budgeting guardrails** – Libraries such as `tiktoken` or `transformers` can estimate token counts locally. A quick pre-flight check before each call lets you short-circuit or trigger summarisation without any backend changes.

These tactics require minimal external dependencies yet provide significant relief from context pressure. Retrieval-augmented generation, persistent knowledge bases, and sophisticated tool-calling often demand additional services (vector databases, message queues, secure credential handling), so plan for more engineering effort before adopting them.
