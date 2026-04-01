# ⚡ SupplyMind — Multi-Agent Procurement System

> An intelligent procurement assistant that manages your entire supply chain through conversation — from stock monitoring to supplier discovery, RFQ sending, quote analysis, and delivery verification.

---

## What It Does

SupplyMind replaces the manual back-and-forth of procurement with a smart conversational assistant. Talk to it the way you'd talk to a colleague — it handles the complexity behind the scenes.

**Some things you can say:**
- *"Check M8 Screws"*
- *"Find suppliers for Electric Motors"*
- *"Send RFQs to low-risk suppliers only, 500 units, 7 days delivery"*
- *"Check inbox for quotes"*
- *"Analyze the quotes"*
- *"Approve it"*

---

## Core Capabilities

** Inventory Intelligence**
Checks your stock levels and predicts future demand using historical order data. Tells you what to order, how much, and how urgently.

** Supplier Discovery**
Finds suppliers through live web search or pulls from your approved vendor history. Scores each supplier on quality, ISO certifications, years in business, and reliability.

** RFQ Automation**
Drafts and sends professional Request for Quotation emails to multiple suppliers at once. You can filter by supplier quality, count, or name. Unfinished RFQs are saved so you can resume later.

** Inbox Monitoring**
Watches your Gmail inbox for supplier replies. Automatically reads, classifies, and extracts pricing and delivery details from quote emails — no copy-pasting needed.

** Quote Comparison & Purchase Orders**
Compares all quotes on price, delivery speed, and quality. Picks the best supplier, explains why, and generates a formal Purchase Order — all in one step.

** Document Verification**
Upload a delivery note and invoice image. The system uses AI vision to extract the data and cross-checks it against the original PO (3-way matching) to catch any discrepancies before payment.

** Stakeholder Notifications**
Your team gets email updates at every key step — RFQ sent, quote received, PO approved, delivery verified — automatically.

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up your credentials
Create a `.env` file in the project root:
```
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
GMAIL_USER=your.email@gmail.com
GMAIL_APP_PASSWORD=your_gmail_app_password
STAKEHOLDER_EMAIL=stakeholder@company.com
```

### 3. Run the web interface
```bash
streamlit run app.py
```

### 4. Or use the terminal interface
```bash
python cli.py
```

---

## A Complete Workflow Example

```
You:       "Check bearings stock"
System:    Analyses inventory + forecasts demand
           → "Low stock. Recommend ordering 450 units. Find suppliers?"

You:       "Yes"
System:    Searches web / approved vendor history
           → Shows 5 ranked suppliers with quality scores

You:       "Send to low risk suppliers only"
System:    Drafts and sends RFQ emails
           → Your team gets a notification

           (Suppliers reply to your Gmail...)

You:       "Check inbox"
System:    Reads and parses all quote emails automatically
           → Shows each supplier's price and delivery

You:       "Analyze quotes"
System:    Compares all quotes, selects best, generates PO
           → "Approve purchase order from Supplier X for ₹31,700?"

You:       "Approve"
System:    Saves PO, notifies your team
```

---

## Interface Pages

| Page | What it shows |
|------|---------------|
| **Dashboard** | Live metrics — stock health, active orders, recent activity |
| **Chat Interface** | The main conversational assistant |
| **Inventory Monitor** | Full stock table with filters and search |
| **Procurement Pipeline** | All RFQs (sent & pending), collected quotes, purchase orders |
| **Document Verification** | Upload delivery notes and invoices for 3-way matching |
| **Configurations** | Email settings, approval thresholds, company details |

---

## Data Storage

Everything stays local. No external databases. All records are stored as files in the `data/` folder:

| File | Contents |
|------|----------|
| `current_inventory.csv` | Stock levels and reorder points |
| `purchase_orders.json` | All generated POs |
| `quotes_collected.json` | Parsed supplier quotes |
| `sent_rfqs.json` | Record of all sent RFQs |
| `pending_rfqs.json` | Saved RFQs for later |
| `supplier_history.json` | Approved vendor performance history |
| `notification_logs.json` | Stakeholder notification audit trail |

---
