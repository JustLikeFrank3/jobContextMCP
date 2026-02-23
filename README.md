# Job Search MCP

This MCP server solves that by giving any AI assistant a set of tools it can call to retrieve all of that context instantly.

## Architecture

```mermaid
flowchart TD;
    A[User] -->|request| B[AI Assistant];
    B -->|call| C[Tool API];
    C -->|response| B;
    B -->|response| A;
```

```mermaid
flowchart TD;
    A[Frontend] --> B[Backend];
    B --> C[Database];
    C --> D[External APIs];
```

```mermaid
flowchart LR;
    A[User Input] --> B[Resume Parser];
    B --> C[Context Storage];
    D[Resume] --> B;
    C --> E[AI Assistant];
```

```mermaid
flowchart TD;
    A[Workspace] --> B[Projects];
    B --> C[Tools];
    C --> D[Files];
```

```mermaid
flowchart TD;
    A[User Preferences] --> B[Contextual Model];
    B --> C[Tone Adjustments];
```

```mermaid
flowchart TD;
    A[User Query] --> B[Retrieve Context];
    B --> C[AI Assistant];
    D[External Sources] --> B;
    C --> E[Output];
```

## Tools

Here is a list of tools available in the MCP. 

... (rest of README content)
