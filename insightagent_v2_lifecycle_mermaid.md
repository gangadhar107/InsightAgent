# Request Lifecycle

```mermaid
flowchart TD
    NewChat([New chat]) --> Ask[User asks a question]
    Ask --> Resolve[Resolve question<br/>rewrite using recent history]
    Resolve --> Ambig{Clear enough?}

    Ambig -->|No| Clarify[Ask clarification<br/>tappable options]
    Clarify --> Resolve

    Ambig -->|Yes| Route{Known metric?}

    Route -->|Yes, in catalog| Catalog[Use catalog SQL<br/>fixed definition]
    Route -->|No| Retrieve[Retrieve tables<br/>semantic search]
    Retrieve --> Generate[Generate SQL<br/>from retrieved tables]

    Catalog --> Validate[Validate SQL<br/>read-only, real tables]
    Generate --> Validate

    Validate -->|Fails, retry once| Generate
    Validate -->|Passes| Cost[Cost guard<br/>EXPLAIN check]
    Cost --> Execute[Execute query]
    Execute --> SelfCheck[Self-check<br/>answers the question?]
    SelfCheck --> Answer[Return answer<br/>number, chart, summary]

    Answer -.next question, same chat.-> Ask
```

## How to read it

- **Solid arrows** are one question's journey through the pipeline.
- **The dashed arrow** is the conversation continuing: after an answer, the
  next question re-enters at the top, where the resolve step now has the longer
  history to work with.
- **Two loops guard the model's output.** The clarification loop sends a vague
  question back to the user before answering. The validation loop bounces
  failed SQL back to generation exactly once.
- **Catalog SQL skips retrieval and generation** (it's a trusted, fixed
  definition) but still flows through validation and execution for a single
  execution path. It skips the self-check, since a blessed definition does not
  need its correctness re-verified.
```
