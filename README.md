# Job Search MCP

This MCP server solves that by giving any AI assistant a set of tools it can call to retrieve all of that context instantly.

## Architecture

```mermaid
graph TD;
A[Client] --> B[API Gateway];
B --> C[Microservice 1];
B --> D[Microservice 2];
C --> E[Database 1];
D --> F[Database 2];
```

```mermaid
sequenceDiagram;
    Client->>API Gateway: Request Job Search;
    API Gateway->>Microservice 1: Fetch Job Listings;
    API Gateway->>Microservice 2: Fetch Company Info;
    Microservice 1-->>API Gateway: Return Job Listings;
    Microservice 2-->>API Gateway: Return Company Info;
    API Gateway-->>Client: Return Combined Response;
```

```mermaid
stateDiagram-v2;
    [*] --> Searching;
    Searching --> Results;
    Results --> [*];
    Searching --> NoResults;
    NoResults --> [*];
```

```mermaid
flowchart TB;
    A[User] --> B{Choose Job Type};
    B -->|Tech| C[Fetch Tech Jobs];
    B -->|Non-Tech| D[Fetch Non-Tech Jobs];
    C --> E[Sort by Relevance];
    D --> E;
    E --> F[Display Results];
```

```mermaid
gantt;
    title A Gantt Diagram;
    dateFormat  YYYY-MM-DD;
    section Job Search
    Search Jobs    :active, 2026-02-23, 30d;
    Review Applications :after Search Jobs , 30d;
    Get Interviews       :after Review Applications  , 30d;
```

```mermaid
pie;
    title Job Applications Breakdown;
    "Applied": 40;
    "Interviewed": 30;
    "Rejected": 20;
    "Offer": 10;
```

## Getting Started

### Prerequisites

- Node.js
- npm

### Installation

1. Clone the repository.
2. Run `npm install`.  
3. Run `npm start` to start the server.

## Contributing

Please feel free to submit issues or pull requests to help us improve this project!