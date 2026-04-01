# SupplyMind — Technology Stack

## AI & Language Models

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **Groq API** | Cloud inference provider for all LLM calls — low-latency, high-throughput | All agents that need AI reasoning |
| **Llama 3.3 70B** | Primary reasoning model for intent classification, decision making, quote analysis, and conversational responses | Agent 0 (orchestrator), Agent 6 (decisions), Agent 9 (exceptions) |
| **Llama 3.1 8B** | Lightweight model for fast tasks — email body generation, RFQ drafting, structured data extraction | Agent 5 (RFQ generation), Agent 4 (supplier evaluation) |
| **Llama 3.2 90B Vision** | Multimodal model that reads images — extracts data from delivery notes, invoices, and scanned documents | Agent 8 (document verification) |

## Web Framework & UI

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **Streamlit** | Full-stack web framework — handles UI rendering, session state, routing, and real-time updates | `app.py` — the entire dashboard, chat interface, inventory monitor, procurement pipeline, and document verification tabs |
| **Plotly** | Interactive data visualization — charts, gauges, and graphs | Dashboard KPI cards, inventory trend charts, procurement pipeline visualizations |
| **Custom HTML/CSS/JS** | Premium chat interface styling, pill buttons, animations, and responsive layouts injected via `st.markdown` and `components.html` | Chat interface bubbles, follow-up pills, sidebar branding, welcome hero section |

## Email & Communication

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **Gmail SMTP** | Sends outbound emails — RFQs to suppliers, notifications to stakeholders, mismatch alerts | Agent 5 (RFQ dispatch), Agent 7 (notifications), Agent 9 (supplier communication) |
| **Gmail IMAP** | Reads incoming emails — polls the inbox for supplier quote responses | Agent 6 (quote collection from inbox) |
| **Email Templates (HTML)** | Professionally formatted email bodies for each notification type | `utils/template_manager.py` — 12 event-specific templates |

## Data Processing & Forecasting

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **Pandas** | Data manipulation — reads CSV inventory/order files, transforms and aggregates data | Agent 1 (data pipeline), Agent 2 (stock monitoring), Agent 3 (replenishment) |
| **NumPy** | Numerical computation — trend detection, statistical analysis | Agent 1C (forecasting), Agent 3 (order quantity calculation) |
| **scikit-learn** | Machine learning — linear regression for demand forecasting, MAPE evaluation | Agent 1C (model training and evaluation) |
| **statsmodels** | Time series analysis — exponential smoothing, autocorrelation for seasonality detection | Agent 1C (Holt-Winters forecasting) |

## Web Search & Supplier Discovery

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **Tavily API** | AI-powered web search — finds supplier websites and product pages | Agent 4 (supplier discovery) |
| **BeautifulSoup** | HTML parsing — extracts company details, contact info, and product data from supplier websites | Agent 4 (supplier profile extraction) |
| **Requests** | HTTP client — fetches supplier web pages for parsing | Agent 4 (web scraping) |

## Document Processing & Reporting

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **xhtml2pdf (pisa)** | Converts HTML reports to PDF — generates professional delivery quality reports | Agent 11 (quality report generation) |
| **Base64 encoding** | Embeds delivery note and invoice images directly into PDF reports | Agent 11 (document evidence section) |

## Agent Framework

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **CrewAI** | Agent orchestration framework — provides base agent structure, task management, and agent lifecycle | `base_agent.py` — BaseAgent class that Agent 0–5 extend |
| **Custom Agent Pattern** | Standalone agent classes for specialized workflows that don't need CrewAI overhead | Agents 6–11 (decision maker, communicator, verifier, exception handler, storage, reporter) |

## Configuration & Infrastructure

| Technology | Purpose | Where Used |
|-----------|---------|------------|
| **python-dotenv** | Loads environment variables from `.env` file — API keys, email credentials, feature flags | All agents and utilities at initialization |
| **JSON file storage** | Persistent data store — no database required. Stores POs, quotes, receipts, payments, supplier history, and notification logs | `data/` directory — 15+ JSON files managed by Agent 10 |
| **CSV files** | Input data format for inventory and historical orders | `data/current_inventory.csv`, `data/historical_orders.csv` |
| **Custom logging** | Structured logging with separate info and error log files | `utils/logger.py` — used by all agents for audit trail |

## Architecture Summary

```
User ──→ Streamlit UI ──→ Agent 0 (Master Orchestrator)
                              │
                              ├── Agent 1A/1B/1C (Data Pipeline)
                              ├── Agent 2 (Stock Monitor)
                              ├── Agent 3 (Replenishment Advisor)
                              ├── Agent 4 (Supplier Discovery)  ──→ Tavily + Web Scraping
                              ├── Agent 5 (RFQ Generator)       ──→ Gmail SMTP
                              ├── Agent 6 (Decision Maker)      ──→ Gmail IMAP
                              ├── Agent 7 (Communications)      ──→ Gmail SMTP
                              ├── Agent 8 (Document Verification)──→ Llama Vision
                              ├── Agent 9 (Exception Handler)
                              ├── Agent 10 (Data Storage)       ──→ JSON Files
                              └── Agent 11 (Report Generator)   ──→ PDF Generation
```
