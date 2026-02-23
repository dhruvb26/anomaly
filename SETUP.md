# Setup

This guide will help you set up the Anomaly Detection system for multi-agent LLM execution locally.

## Architecture Overview

This project is a **TurboRepo monorepo** with two main applications:

- **`apps/api`** - Python FastAPI backend for anomaly detection using LangGraph agents
- **`apps/web`** - Next.js frontend for visualizing agent execution graphs and sentinel reports

The system models agent execution as a dynamic graph, storing it in Neo4j, with traces in LangSmith and payloads in Redis.

---

## Prerequisites

### Required Software

1. **Bun** (for frontend) - [Install Bun](https://bun.sh/)
2. **Python 3.13+** with **uv** (for backend) - [Install uv](https://docs.astral.sh/uv/)
3. **Docker** & **Docker Compose** (for databases)
4. **Ollama** (for local LLM models) - [Install Ollama](https://ollama.com/)

### Required API Keys

#### Backend Environment Variables (`apps/api/.env`)

```bash
# LangSmith - Agent tracing and observability
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_TRACING=true
LANGSMITH_WORKSPACE_ID=your_workspace_id
LANGSMITH_PROJECT=default

# LLM Providers
ANTHROPIC_API_KEY=your_anthropic_api_key        # For Claude Sonnet (main agent)
OPENAI_API_KEY=your_openai_api_key              # Optional, if using OpenAI models

# Tool Providers
COMPOSIO_API_KEY=your_composio_api_key          # For file operations, web browsing, code execution

# Security & Guardrails
TOGETHER_API_KEY=your_together_api_key          # For LlamaFirewall AlignmentCheck (uses Llama-4-Maverick-17B)

# Neo4j (Graph Database) - For persistent graph storage
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password
NEO4J_DATABASE=neo4j

# Local Databases (Docker)
DB_URI=postgresql://postgres:postgres@localhost:5433/langgraph
REDIS_URL=redis://localhost:6379
```

#### Frontend Environment Variables (`apps/web/.env`)

```bash
# LangSmith - For trace visualization in the UI
LANGSMITH_API_KEY=your_langsmith_api_key        # Same as backend
LANGSMITH_TRACING=true
LANGSMITH_WORKSPACE_ID=your_workspace_id        # Same as backend
LANGSMITH_PROJECT=default

# API Connection
LANGSMITH_API_URL=http://localhost:2024         # Backend API URL
NEXT_PUBLIC_LANGSMITH_API_URL=http://localhost:2024  # Exposed to browser

# LLM Providers (for server-side operations)
ANTHROPIC_API_KEY=your_anthropic_api_key        # Same as backend
OPENAI_API_KEY=your_openai_api_key              # Same as backend
COMPOSIO_API_KEY=your_composio_api_key          # Same as backend

# Database (for server-side queries)
POSTGRES_URL=postgresql://postgres:postgres@localhost:5433/langgraph

# Trigger.dev (for background job processing)
TRIGGER_SECRET_KEY=tr_dev_your_secret_key       # Get from trigger.dev dashboard
```

#### Where to Get API Keys

| Service | Purpose | Get API Key |
|---------|---------|-------------|
| **LangSmith** | Agent execution tracing and debugging | [smith.langchain.com](https://smith.langchain.com/) |
| **Anthropic** | Claude Sonnet 4.5 (main agent model) | [console.anthropic.com](https://console.anthropic.com/) |
| **Together AI** | AlignmentCheck scanner (Llama-4-Maverick-17B) | [api.together.xyz](https://api.together.xyz/) |
| **Composio** | Agent tools (file operations, browser, code executor) | [composio.dev](https://composio.dev/) |
| **Neo4j Aura** | Managed graph database (or run locally) | [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura/) |
| **Trigger.dev** | Background job processing for frontend | [trigger.dev](https://trigger.dev/) |
| **OpenAI** | Optional, if using GPT models | [platform.openai.com](https://platform.openai.com/) |

#### Unnecessary/Unused Environment Variables

The following environment variables may appear in example `.env` files but are **not currently used** in the codebase and can be safely omitted:

- `SUPERMEMORY_API_KEY` - Not referenced anywhere
- `DAYTONA_API_KEY` - Not referenced anywhere

#### Optional: Hugging Face Token

For **PromptGuard** (prompt injection detection), you need access to the gated model:

1. Request access at [huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)
2. Create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
3. Export it: `export HUGGING_FACE_HUB_TOKEN=your_token`

---

## Docker Services

The project uses Docker Compose to run local infrastructure. See `compose.yaml` in the root.

### Services

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    ports: "5433:5432"
    # Stores: LangGraph checkpoints, LangGraph memory store, Sentinel reports
    
  redis:
    image: redis:7-alpine
    ports: "6379:6379"
    # Stores: Full run payloads (inputs/outputs) to keep Neo4j lean
```

#### What Each Service Does

1. **PostgreSQL** (`pgvector/pgvector:pg17`)
   - **Port**: `5433` → `5432` (to avoid conflicts with system Postgres)
   - **Purpose**: 
     - LangGraph checkpoint storage (conversation state persistence)
     - LangGraph memory store (agent long-term memory)
     - Sentinel reports table (anomaly detection results)
   - **Why pgvector**: Includes vector extension for potential semantic search on reports
   - **Volume**: `pgdata` for data persistence across restarts

2. **Redis** (`redis:7-alpine`)
   - **Port**: `6379`
   - **Purpose**: Payload storage for agent runs
   - **Why Redis**: 
     - Fast key-value store for large JSON payloads
     - Keeps Neo4j graph database lean (only stores metadata, not full content)
     - Used by Sentinel to fetch edge content for security checks

### Starting Docker Services

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Stop services
docker compose down

# Stop and remove volumes (clears all data)
docker compose down -v
```

---

## Ollama Setup

The Sentinel system uses **IBM Granite Guardian 3.3** for jailbreak and hallucination detection via Ollama.

### Install and Run Ollama

```bash
# Install Ollama (macOS)
brew install ollama

# Start Ollama service
ollama serve

# In another terminal, pull the Guardian model
ollama pull ibm/granite3.3-guardian:8b
```

This model runs locally and is configured in `apps/api/config.yaml`:

```yaml
sentinel:
  guardian:
    enabled: true
    model: "ibm/granite3.3-guardian:8b"
    base_url: "http://localhost:11434"  # Default Ollama port
    confidence_threshold: 0.5
```

---

## Installation

### 1. Clone and Install Dependencies

```bash
# Install root dependencies (Bun)
bun install

# Install API dependencies (Python with uv)
cd apps/api
uv sync  # or: uv pip install -e .

# Install web dependencies
cd ../web
bun install
```

### 2. Setup Environment Variables

```bash
# Backend environment variables
cp apps/api/.env.example apps/api/.env
# Edit apps/api/.env with your actual keys

# Frontend environment variables
cp apps/web/.env.example apps/web/.env
# Edit apps/web/.env with your actual keys
# Note: Most values can be copied from apps/api/.env
```

### 3. Start Docker Services

```bash
# From project root
docker compose up -d
```

### 4. Verify Ollama is Running

```bash
ollama list  # Should show ibm/granite3.3-guardian:8b
```

---

## Running the Application

### Option 1: Run Everything (Recommended)

From the project root:

```bash
bun dev
```

This starts:
- **API** on `http://localhost:2024` (FastAPI with agent)
- **Web** on `http://localhost:3000` (Next.js frontend)
- **Trigger.dev** worker (for background jobs)

### Option 2: Run Services Individually

#### Start the API

```bash
cd apps/api
uv run main.py
# or: python main.py
```

API will be available at `http://localhost:2024`

#### Start the Web App

```bash
cd apps/web
bun dev
```

Web app will be available at `http://localhost:3000`

### Option 3: LangGraph Studio (Development/Debugging)

For interactive agent debugging with LangGraph Studio:

```bash
cd apps/api

# Make sure the package is installed in editable mode
uv pip install -e .

# Start LangGraph dev server
langgraph dev
# or: uv run langgraph dev
```

LangGraph Studio will be available at:
- **API**: `http://localhost:8123`
- **Studio UI**: Open LangGraph Studio desktop app and connect to `http://localhost:8123`

**Note**: The `langgraph.json` config is already set up to use module imports:

```json
{
  "graphs": {
    "agent": "src.agent.agent:graph"
  },
  "env": ".env",
  "dependencies": ["."]
}
```

---

## Project Structure

```
anomaly/
├── apps/
│   ├── api/                    # Python FastAPI backend
│   │   ├── src/
│   │   │   ├── agent/         # LangGraph agent definition
│   │   │   ├── graph/         # Graph building, inference, sentinel
│   │   │   ├── routes/        # FastAPI endpoints
│   │   │   ├── stores/        # Neo4j, Redis, Postgres clients
│   │   │   └── services/      # Ingestion, analysis services
│   │   ├── config.yaml        # Sentinel configuration
│   │   ├── langgraph.json     # LangGraph CLI config
│   │   └── main.py            # Server entry point
│   │
│   └── web/                    # Next.js frontend
│       ├── src/
│       │   ├── app/           # Next.js App Router pages
│       │   ├── components/    # React components
│       │   └── lib/           # Utilities, API clients
│       └── package.json
│
├── compose.yaml               # Docker services
├── package.json               # Root workspace config
└── turbo.json                 # TurboRepo pipeline
```

---

## Configuration

### Sentinel Configuration (`apps/api/config.yaml`)

Controls anomaly detection behavior:

```yaml
sentinel:
  guardian:
    enabled: true                           # Enable Granite Guardian checks
    model: "ibm/granite3.3-guardian:8b"    # Ollama model
    base_url: "http://localhost:11434"     # Ollama server
    confidence_threshold: 0.5               # Min confidence for anomaly

  firewall:
    enabled: true
    prompt_guard:
      enabled: true                         # PromptGuard 2 (requires HF token)
    alignment_check:
      enabled: true                         # Llama-4-Maverick (requires Together API)

  resource_baselines:
    enabled: true
    z_threshold: 2.5                        # Std deviations for resource anomalies
    min_samples: 3                          # Min historical runs for comparison
```

---

## Additional Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangSmith Tracing Guide](https://docs.smith.langchain.com/)
- [Neo4j Graph Database](https://neo4j.com/docs/)
- [Composio Tools](https://docs.composio.dev/)
- [LlamaFirewall Guide](https://meta-llama.github.io/PurpleLlama/LlamaFirewall/)
- [SentinelAgent Paper](./apps/api/2505.24201v1.pdf)

