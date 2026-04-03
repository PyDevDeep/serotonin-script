# 🧠 Serotonin Script

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![Taskiq](https://img.shields.io/badge/Taskiq-Async--Native-orange.svg)
![RAG](https://img.shields.io/badge/RAG-LlamaIndex%2FQdrant-red.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

> AI-driven medical content engine using RAG (LlamaIndex/Qdrant), FastAPI, and Taskiq for automated multi-platform publishing with physician style preservation.

---

## 🎯 Overview

**Serotonin Script** is an autonomous system for generating and distributing medically-accurate content across social platforms. It leverages **RAG (Retrieval-Augmented Generation)** to ensure medical precision while preserving the unique authorial voice of healthcare professionals.

### Key Capabilities
- **Style Preservation**: Vector-based retrieval of physician's writing patterns
- **Medical Accuracy**: Fact-checking against clinical guidelines (PubMed, protocols)
- **Multi-Platform Publishing**: Automated distribution to Telegram, X (Twitter), Threads
- **Async-First Architecture**: High-performance task processing via Taskiq + Redis
- **Slack-Native UX**: Draft approval workflow with interactive Block Kit UI

---

## 🛠 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **API Framework** | FastAPI | Async-native REST API |
| **Task Queue** | [Taskiq](https://github.com/taskiq-python/taskiq) + Redis | Background job processing |
| **AI Engine** | Claude 3.5 Sonnet / GPT-4o | Content generation with fallback |
| **Vector Store** | Qdrant | Semantic search for style/knowledge |
| **RAG Framework** | LlamaIndex | Retrieval-augmented generation pipeline |
| **Orchestration** | n8n | Workflow automation & scheduling |
| **Database** | PostgreSQL + Alembic | Relational data with migrations |
| **Monitoring** | Prometheus + Grafana + Loki | Metrics, dashboards, logs |

---

## 📁 Project Structure
```text
seratonin_script/
├── backend/
│   ├── api/                    # FastAPI routes & middleware
│   ├── services/               # Business logic orchestration
│   ├── agents/                 # LangChain agents + tools
│   ├── rag/                    # LlamaIndex indexing & retrieval
│   ├── integrations/           # External APIs (LLMs, social platforms, PubMed)
│   ├── workers/                # Taskiq async workers
│   └── tests/                  # Unit, integration, E2E tests
├── knowledge_base/             # Training data for RAG
│   ├── doctor_style/           # Physician's articles & posts
│   └── medical_guidelines/     # Clinical protocols (PDFs)
├── slack_app/                  # Slack Block Kit UI & handlers
├── orchestration/n8n/          # Workflow definitions
├── database/migrations/        # Alembic schema versions
├── infra/docker/               # Docker Compose + monitoring configs
└── docs/                       # Architecture & ADRs
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)
- Slack workspace (for approval workflow)
- API keys: Anthropic/OpenAI, Telegram, X, Threads

### Installation
```bash
# Clone repository
git clone https://github.com/PyDevDeep/serotonin-script.git
cd serotonin-script

# Configure environment
cp .env.example .env
# Edit .env with your API keys and credentials

# Start all services
docker-compose up --build
```

### Service URLs
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **n8n**: http://localhost:5678
- **Grafana**: http://localhost:3000

---

## 📖 Usage

### 1. Index Knowledge Base
```bash
# Ingest physician's writing samples + medical guidelines into Qdrant
python scripts/index_knowledge_base.py
```

### 2. Generate Draft (via Slack)
```
/draft anxiety management tips
```

**Workflow**:
1. Slack command triggers n8n webhook
2. n8n calls `POST /draft` with topic
3. Backend enqueues Taskiq task `generate_draft`
4. Worker:
   - Retrieves similar physician posts (style matching)
   - Fetches relevant medical facts (knowledge retrieval)
   - Generates draft via Claude 3.5 Sonnet
5. Slack receives Block Kit card with draft + action buttons

### 3. Approve & Publish

Click **"Publish to Telegram"** button in Slack:
- Taskiq task `publish_post` executes
- Content posted to configured channels
- Slack notification confirms success

---

## 🔧 Development

### Run Tests
```bash
# Unit tests
make test-unit

# Integration tests (requires running containers)
make test-integration

# Full test suite
make test
```

### Local Backend Development
```bash
# Install dependencies
poetry install

# Run API server
poetry run uvicorn backend.api.main:app --reload

# Run Taskiq worker
poetry run taskiq worker backend.workers.broker:broker
```

### Database Migrations
```bash
# Generate migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

---

## 📊 Monitoring

- **Metrics**: http://localhost:3000/d/backend_metrics
- **LLM Costs**: http://localhost:3000/d/llm_costs
- **Taskiq Jobs**: http://localhost:3000/d/taskiq_metrics

---

## 🗺️ Roadmap

- [x] **Phase 1**: Infrastructure & Dev Environment Setup
- [ ] **Phase 2**: RAG Pipeline Implementation (Doctor Style Matcher)
- [ ] **Phase 3**: Taskiq Workers for Background Generation
- [ ] **Phase 4**: Multi-Platform Publishing (Telegram, X, Threads)
- [ ] **Phase 5**: Scheduled Posting & Analytics Dashboard

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for detailed guidelines.

---

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **LlamaIndex** for RAG framework
- **Taskiq** for modern async task processing
- **Qdrant** for vector search capabilities
---

**Created by** [PyDevDeep](https://github.com/PyDevDeep)