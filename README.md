# SiteSage

> **Don't search through websites. Ask them.**

SiteSage is an open-source, question-aware website search engine designed for deep content exploration, research transparency, and grounded question answering. Instead of relying on brute-force breadth-first search or delegating everything to an opaque, hallucination-prone Large Language Model, SiteSage combines an intelligent question-guided crawler, structural passage extraction, SQLite inverted indexing, and pure Python Okapi BM25 ranking with explainable field-level scoring.

Every single sentence in a SiteSage answer is directly tied to an exact supporting excerpt, section heading, and verified source URL. An optional AI Readability Polisher powered by the Google Gemini API can reorganize verified evidence into smooth prose, governed by a strict validator that immediately rejects any hallucinated facts, dropped citations, or altered numeric values.

---

## Table of Contents

- [User Interface & Walkthrough](#user-interface--walkthrough)
- [How It Works](#how-it-works)
  - [Pipeline Workflow](#pipeline-workflow)
  - [Architecture Diagram](#architecture-diagram)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Quick Start & Installation](#quick-start--installation)
  - [One-Click Launch (Recommended)](#one-click-launch-recommended)
  - [Manual Setup (Windows PowerShell)](#manual-setup-windows-powershell)
  - [Manual Setup (Linux / macOS)](#manual-setup-linux--macos)
  - [Docker Setup (Optional)](#docker-setup-optional)
- [Environment Configuration](#environment-configuration)
- [User Walkthrough](#user-walkthrough)
- [API Reference](#api-reference)
  - [Core REST Endpoints](#core-rest-endpoints)
  - [Server-Sent Events (SSE) Stream](#server-sent-events-sse-stream)
- [Architecture & Implementation Details](#architecture--implementation-details)
  - [Question-Aware Priority Crawler](#question-aware-priority-crawler)
  - [Passage Indexing & Structural Boundary Alignment](#passage-indexing--structural-boundary-alignment)
  - [Pure Python Okapi BM25 Ranking](#pure-python-okapi-bm25-ranking)
  - [Deterministic Evidence Extraction & Conflict Detection](#deterministic-evidence-extraction--conflict-detection)
  - [AI Readability Polish & Safety Guardrails](#ai-readability-polish--safety-guardrails)
  - [Why Custom BM25 Instead of Pure LLM Scraping?](#why-custom-bm25-instead-of-pure-llm-scraping)
- [Project Structure](#project-structure)
- [Automated Testing & Benchmark Evaluation](#automated-testing--benchmark-evaluation)
  - [Running the Pytest Suite](#running-the-pytest-suite)
  - [Running Benchmark Evaluation](#running-benchmark-evaluation)
  - [Evaluation Metrics & Benchmark Results](#evaluation-metrics--benchmark-results)
- [Security & Limitations](#security--limitations)
- [AI Tools & Acknowledgements](#ai-tools--acknowledgements)
- [Hackathon Submission Information](#hackathon-submission-information)
- [Future Improvements](#future-improvements)
- [License](#license)

---

## User Interface & Walkthrough

| Initial Search Interface | Form Populated with Preset Example |
| :---: | :---: |
| ![SiteSage Initial Homepage](screenshots/01_homepage.png) | ![Search Form Populated](screenshots/02_form_populated.png) |

| Live Crawl & Pipeline Dashboard | Verified Search Results & Traceable Citations |
| :---: | :---: |
| ![Live Crawl Dashboard](screenshots/03_live_crawl_dashboard.png) | ![Evidence-Supported Answer](screenshots/04_search_results.png) |

| Advanced Search Transparency (BM25 Breakdown) | Session History Drawer |
| :---: | :---: |
| ![BM25 Score Breakdown Table](screenshots/05_transparency_bm25_explainability.png) | ![Search History Drawer](screenshots/06_session_history_drawer.png) |

---

## How It Works

### Pipeline Workflow

1. **User Inquiry & Validation**: The user provides a seed website URL, a question, an optional crawl limit (up to 30 pages), and toggles optional AI Readability Polish.
2. **Question-Aware Crawling**: The crawler starts at the seed URL, inspects `robots.txt`, and uses a min-heap priority queue scored against question keywords to explore the most promising internal links first.
3. **HTML Cleaning & Leaf Text Extraction**: HTML content is stripped of noise tags (`<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`), extracting clean text exclusively from leaf text nodes (`NavigableString`) to avoid duplicated text.
4. **Passage Chunking & Heading Alignment**: Clean text is chunked into bounded passages along sentence boundaries (`config.MAX_PASSAGE_LENGTH = 500`), aligning sections to structural `<h1>`–`<h6>` headings.
5. **SQLite Inverted Indexing**: Passages, heading hierarchies, and token frequencies are persisted in SQLite (WAL mode) and mapped into an inverted index.
6. **Multi-Aspect Intent Decomposition**: Complex questions are deterministically split into searchable sub-facets (e.g. separating pricing inquiries from feature comparisons).
7. **Pure Python Okapi BM25 Ranking**: For each aspect, passages are ranked using Okapi BM25 with Lucene non-negative IDF, reinforced by additive boosts for title matches, section heading matches, document position, and crawl depth penalties.
8. **Deterministic Evidence Extraction**: Sentence-level claims are extracted, mapped to verbatim supporting quotes, and checked for contradictions and missing information.
9. **Optional AI Polish with Strict Fallback**: If requested, Google Gemini reformulates verified claims into flowing prose. A strict safety validator checks that all citations, facts, and figures remain intact; if validation fails or the API key is missing, SiteSage seamlessly reverts to the deterministic answer.
10. **Real-Time SSE Streaming**: Live progress metrics, stage transitions, and discovered URLs are streamed to the browser over Server-Sent Events (`/api/search/{session_id}/stream`) with full reconnection replay.

### Architecture Diagram

SiteSage runs a five-stage pipeline. Only the last stage uses an LLM, and it is optional.

```mermaid
flowchart LR
    A["Crawl"] --> B["Index"] --> C["Rank"] --> D["Extract"] --> E["Polish (optional)"] --> F["Cited answer"]
```

Detailed view (step numbers match [How It Works](#how-it-works)):

```mermaid
flowchart TD
    User(["Browser"]) -->|"URL + question"| API["FastAPI: POST /api/search"]
    API -->|"create session"| DB[("SQLite, WAL")]
    API --> Pipeline["Pipeline orchestrator"]
    Pipeline -.->|"10. SSE progress events"| User

    subgraph S1["Crawl (steps 2-3)"]
        Guard{"SSRF + same-origin guard"} --> Robots["robots.txt check"]
        Robots --> Queue["Keyword-biased priority queue"]
        Queue --> Fetch["Async HTTPX, max 3 concurrent"]
        Fetch --> Clean["HTML cleaning + leaf text extraction"]
    end

    subgraph S2["Index (steps 4-5)"]
        Chunk["Passage chunking + heading alignment"] --> Indexer["SiteIndexer"]
    end

    subgraph S3["Rank (steps 6-7)"]
        Decompose["Question aspect decomposition"] --> BM25["Okapi BM25"]
        BM25 --> Boosts["Boosts: title, heading, position, depth"]
    end

    subgraph S4["Extract (step 8)"]
        Claims["Claims + verbatim quotes"] --> Conflicts["Conflict + missing-info detection"]
    end

    subgraph S5["Polish, optional (step 9)"]
        Gemini["Gemini API"] --> Validator{"Evidence validator"}
    end

    Pipeline --> Guard
    Clean --> Chunk
    Indexer -->|"write inverted index"| DB
    DB -->|"read index"| Decompose
    Boosts --> Claims
    Conflicts --> Det["Deterministic answer"]
    Det --> Check{"Polish requested?"}
    Check -->|"no"| Final["Final result"]
    Check -.->|"yes"| Gemini
    Validator -.->|"pass"| Final
    Validator -.->|"fail or no API key: keep deterministic"| Final
    Final -->|"persist"| DB
    DB --> Results["GET /api/search/{id}/results"]
    Results --> User

    classDef crawl fill:#dbeafe,stroke:#2563eb,color:#111
    classDef index fill:#dcfce7,stroke:#16a34a,color:#111
    classDef rank fill:#fef9c3,stroke:#ca8a04,color:#111
    classDef extract fill:#fce7f3,stroke:#db2777,color:#111
    classDef polish fill:#ede9fe,stroke:#7c3aed,color:#111,stroke-dasharray:5 3
    class Guard,Robots,Queue,Fetch,Clean crawl
    class Chunk,Indexer index
    class Decompose,BM25,Boosts rank
    class Claims,Conflicts,Det extract
    class Gemini,Validator polish
```
---

## Key Features

- **Focused Same-Website Crawling**: Enforces strict same-origin security. Links to third-party domains, social trackers, and external networks are ignored by design.
- **SSRF & Loopback Protection**: Proactively rejects loopback addresses (`127.0.0.1`, `localhost`), link-local IPs (`169.254.0.0/16`), private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), IPv6 loopbacks, and non-HTTP schemes (`file:`, `javascript:`, `data:`).
- **Keyword-Biased Page Prioritization**: Uses a min-heap priority queue prioritizing links whose URL slugs and anchor texts match query terms, crawling the most relevant pages first.
- **Configurable Crawl Limits**: Sliders allow users to choose between 1 and 30 pages (default: 15) with an overall timeout budget (default: 120s) and per-page timeout (10s).
- **Pure Python Okapi BM25**: Full in-memory and SQLite-backed ranking engine without heavy external search dependencies (no Elasticsearch, Java, or C++ binaries required).
- **Explainable Relevance Scoring**: Every retrieved passage displays its complete score breakdown: BM25 Match, Title Bonus (`+2.0`), Heading Bonus (`+1.5`), Document Position Bonus (`+0.5`), and Depth Penalty (`-0.3`).
- **100% Traceable Citations**: Extracted claims feature interactive `[Source ↗]` badges opening the exact crawled page in a new tab, backed by expandable verbatim passage quotes.
- **Contradiction & Discrepancy Detection**: Cross-references claims across distinct crawled pages to identify conflicting statements (e.g., competing pricing numbers or contradictory policies).
- **Unanswered Aspects Detection**: If a multi-aspect question cannot be fully answered from crawled content, missing facets are explicitly flagged rather than hallucinating filler text.
- **Optional Evidence-Bounded AI Polish**: Enhances prose transitions using Google Gemini while strictly preserving all facts, numbers, and source URLs. If unavailable, it transparently reverts to deterministic mode.
- **Live SSE Streaming Dashboard**: Real-time progress bar, live URL monitor, and color-coded activity stream with seamless `Last-Event-ID` reconnection replay.
- **Search Cancellation**: Instant termination of in-flight searches, stopping crawler workers and releasing database locks cleanly.
- **Persistent Session History**: Search history is saved locally in SQLite, accessible through an off-canvas drawer with one-click reloading.
- **Mobile-Responsive SaaS Interface**: Clean, accessible dark theme crafted with CSS custom properties, responsive grid layouts, and keyboard navigation.

---

## Technology Stack

| Component | Technology | Role in SiteSage |
| :--- | :--- | :--- |
| **Backend Framework** | **Python 3.10+ / FastAPI** | Asynchronous REST routing, dependency injection, and SSE event streaming. |
| **ASGI Web Server** | **Uvicorn** | High-performance asynchronous HTTP server. |
| **HTTP Client** | **HTTPX (Async)** | Non-blocking async crawler requests with custom timeout and redirect handling. |
| **HTML Parsing** | **BeautifulSoup4** | Noise tag decomposition and leaf text node parsing. |
| **Database & Index** | **SQLite3 (WAL Mode)** | Persistent local storage for pages, passages, inverted indices, and sessions. |
| **Ranking Algorithm** | **Custom Okapi BM25** | Pure Python Okapi BM25 with Lucene non-negative IDF and additive field boosts. |
| **AI Polishing** | **Google Gemini API** | Optional readability enhancement via `google-genai` / HTTPX REST interface. |
| **Data Validation** | **Pydantic v2** | Data schema definition, request validation, and serialization. |
| **Frontend UI** | **HTML5 / Vanilla CSS / Vanilla JS** | Zero-dependency client with CSS custom properties and SSE event handling. |
| **Testing** | **Pytest / Pytest-Asyncio / Selenium** | Comprehensive unit, integration, benchmark, and browser E2E test suites. |

---

## Prerequisites

Before installing SiteSage, ensure your system meets the following requirements:

- **Python**: **Python 3.10 or higher** (Python 3.11, 3.12, 3.13, and 3.14 supported).
- **Git**: Installed and available in PATH.
- **Network**: Internet access for crawling target websites.
- **Google Gemini API Key (Optional)**: Required only if you intend to use the AI Readability Polish toggle. The core search engine, crawler, BM25 ranker, and evidence extraction work **100% deterministically without an API key**.
- **Docker & Docker Compose (Optional)**: For containerized deployments.

---

## Quick Start & Installation

### One-Click Launch (Recommended)

SiteSage includes intelligent self-healing launcher scripts that automatically check for Python 3.10+, create and activate a virtual environment, install required dependencies, initialize `.env`, and start the server:

#### Windows:
Double-click `run.bat` in File Explorer, or run in Command Prompt / PowerShell:
```cmd
run.bat
```

#### Linux / macOS:
```bash
chmod +x run.sh
./run.sh
```

---

### Manual Setup (Windows PowerShell)

```powershell
# 1. Clone the repository
git clone https://github.com/balafromtn/sitesage.git
cd sitesage

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
.\venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Configure environment variables (optional)
Copy-Item .env.example .env

# 6. Start the application server
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Visit **`http://127.0.0.1:8000`** in your browser.

---

### Manual Setup (Linux / macOS)

```bash
# 1. Clone the repository
git clone https://github.com/balafromtn/sitesage.git
cd sitesage

# 2. Create a virtual environment
python3 -m venv venv

# 3. Activate the virtual environment
source venv/bin/activate

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Configure environment variables (optional)
cp .env.example .env

# 6. Start the application server
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Visit **`http://127.0.0.1:8000`** in your browser.

---

### Docker Setup (Optional)

You can run SiteSage in a self-contained Docker container with persistent SQLite volume storage:

```bash
# Build and start container using Docker Compose
docker compose up -d --build

# View container logs
docker compose logs -f

# Stop container
docker compose down
```

Visit **`http://localhost:8000`** in your browser.

---

## Environment Configuration

SiteSage reads settings from environment variables or a local `.env` file in the project root. Create `.env` by copying `.env.example`:

```bash
cp .env.example .env
```

### Configuration Variables Reference

| Variable | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `HOST` | String | `127.0.0.1` | Network interface address for Uvicorn server binding. |
| `PORT` | Integer | `8000` | Port number for Uvicorn server binding. |
| `SITESAGE_DB_PATH` | Path | `sitesage.db` | File path for SQLite database storage. |
| `AI_POLISH_ENABLED` | Boolean | `false` | Global default for AI polishing (overridden per-query by UI toggle). |
| `AI_POLISH_MODEL` | String | `gemini-3.5-flash-lite` | Google Gemini model identifier used for readability polishing. |
| `GEMINI_API_KEY` | String | *Empty* | Your Google Gemini API key from Google AI Studio. |

### Obtaining a Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/) and sign in with your Google account.
2. Click **Get API key** and generate a new key.
3. Add the key to your `.env` file:
   ```env
   GEMINI_API_KEY=AIzaSy...your_key_here
   ```
4. **Never commit `.env` to Git.** `.env` is included in `.gitignore` by default.

---

## User Walkthrough

1. **Open the Interface**: Navigate to `http://127.0.0.1:8000` in your web browser.
2. **Enter Website URL**: Type the target website URL (e.g., `https://quotes.toscrape.com/` or `https://httpbin.org/`).
3. **Enter Search Inquiry**: Enter your question (e.g., `What quotes are about mistakes, and who said them?` or `What endpoints inspect client headers?`).
4. **Adjust Crawl Options**:
   - Use the **Crawl limit** slider to set the maximum number of pages to crawl (1 to 30).
   - Toggle **Readability polish** ON if you want Gemini to polish the text, or leave it OFF for raw verified evidence.
5. **Start Search**: Click **Search Website**.
6. **Monitor Live Progress**: Watch real-time crawl statistics (pages discovered, queued, crawled, failed), current URL indicators, and the live activity stream.
7. **Inspect Verified Claims**:
   - Review the primary evidence-supported answer.
   - Click any `[Source ↗]` link to open the crawled webpage in a new tab.
   - Expand the **Verbatim passage quote** accordion on any claim to view the exact text extracted from that page.
8. **Inspect Transparency Breakdown**: Expand **Advanced Search Transparency (BM25 Ranking Breakdown)** to examine how BM25 scores and additive boosts determined passage ranks.
9. **Access Session History**: Click the **History** button in the navigation header to view, reload, or review previous searches.

---

## API Reference

### Core REST Endpoints

#### 1. Service Health Check
```http
GET /health
```
**Response (`200 OK`):**
```json
{
  "status": "healthy",
  "service": "sitesage",
  "version": "0.1.0"
}
```

#### 2. Create Search Session
```http
POST /api/search
Content-Type: application/json
```
**Request Body:**
```json
{
  "url": "https://quotes.toscrape.com/",
  "question": "What quotes are about mistakes?",
  "max_pages": 15,
  "polish": false
}
```
**Response (`200 OK`):**
```json
{
  "session_id": "8f3b2049c81a",
  "status": "crawling"
}
```

#### 3. Real-Time SSE Progress Stream
```http
GET /api/search/{session_id}/stream
Accept: text/event-stream
```
Streams live Server-Sent Events. Supports the standard `Last-Event-ID` header to automatically replay missed events upon network reconnection.

#### 4. Query Session Status
```http
GET /api/search/{session_id}/status
```
**Response (`200 OK`):**
```json
{
  "session_id": "8f3b2049c81a",
  "status": "extracting",
  "stage": "retrieval",
  "pages_discovered": 12,
  "pages_queued": 2,
  "pages_crawled": 10,
  "pages_failed": 0,
  "max_pages": 15,
  "current_url": "https://quotes.toscrape.com/page/3/",
  "message": "Extracting evidence from ranked passages..."
}
```

#### 5. Retrieve Search Results
```http
GET /api/search/{session_id}/results?polish=false
```
**Response (`200 OK`):**
```json
{
  "answer": "### What quotes are about mistakes\n- \"Anyone who has never made a mistake has never tried anything new.\" — Albert Einstein [Source: https://quotes.toscrape.com/tag/mistakes/]",
  "claims": [
    {
      "claim": "\"Anyone who has never made a mistake has never tried anything new.\" — Albert Einstein",
      "confidence": 0.80,
      "aspect": "What quotes are about mistakes",
      "sources": [
        {
          "page_url": "https://quotes.toscrape.com/tag/mistakes/",
          "page_title": "Quotes to Scrape",
          "passage_id": 4,
          "section_heading": "Albert Einstein",
          "exact_quote": "“Anyone who has never made a mistake has never tried anything new.”"
        }
      ]
    }
  ],
  "question_aspects": [
    {
      "aspect": "What quotes are about mistakes",
      "keywords": ["quotes", "mistakes"]
    }
  ],
  "missing_aspects": [],
  "conflicts": [],
  "pages_crawled": 10,
  "pages_failed": 0,
  "ai_polished": false,
  "polish_status": "disabled",
  "polish_reason": "Readability polish was not requested."
}
```

#### 6. Cancel In-Flight Search
```http
POST /api/search/{session_id}/cancel
```
**Response (`200 OK`):**
```json
{
  "session_id": "8f3b2049c81a",
  "status": "cancelled"
}
```

#### 7. Retrieve Session History
```http
GET /api/sessions?limit=20
```
**Response (`200 OK`):**
```json
[
  {
    "session_id": "8f3b2049c81a",
    "seed_url": "https://quotes.toscrape.com/",
    "question": "What quotes are about mistakes?",
    "status": "done",
    "pages_crawled": 10,
    "created_at": "2026-11-22T08:30:00.000000+00:00"
  }
]
```

### Server-Sent Events (SSE) Stream

| Event Type | Stage | Description |
| :--- | :--- | :--- |
| `session_started` | `initialization` | Session initialized, database entries created. |
| `crawling_started` | `crawling` | Priority crawl engine started. |
| `page_discovered` | `crawling` | New candidate internal link discovered and enqueued. |
| `page_crawled` | `crawling` | Page successfully fetched, cleaned, and parsed. |
| `page_failed` | `crawling` | Page fetch failed (timeout, HTTP error, or rejected size). |
| `crawling_completed`| `crawling` | Crawl phase completed upon hitting limit or draining queue. |
| `indexing_started` | `indexing` | Structural passage extraction and indexing initiated. |
| `indexing_completed`| `indexing` | Inverted index constructed and stored in SQLite. |
| `retrieval_started` | `ranking` | Question decomposed into aspects and scored with BM25. |
| `evidence_found` | `retrieval` | Candidate passages extracted and confidence scored. |
| `polishing_started` | `polishing` | Gemini API polishing initiated (if requested). |
| `answer_generated` | `extracting` | Answer synthesized from verified claims. |
| `pipeline_completed`| `completed` | Complete pipeline finished; results ready. |
| `session_cancelled` | `cancelled` | Search was cancelled by user action. |
| `pipeline_error` | `error` | Pipeline encountered an unrecoverable error. |

---

## Architecture & Implementation Details

### Question-Aware Priority Crawler
Standard web crawlers employ breadth-first search (BFS), which explores navigation menus and footer links before finding substantive content. SiteSage uses a **min-heap priority queue** (`heapq`) scored against query terms:
$$\text{Relevance} = 3.0 \times \text{slug\_overlap} + 2.0 \times \text{anchor\_overlap} - 0.5 \times \text{depth}$$
Links containing query keywords in their URL slug or anchor text jump to the front of the queue, ensuring that the 30-page crawl budget focuses on target content.

### Passage Indexing & Structural Boundary Alignment
Raw HTML is processed with BeautifulSoup4:
1. Noise elements (`<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`) are decomposed.
2. Text is extracted strictly from leaf text nodes (`NavigableString`) to avoid multi-ancestor string duplication.
3. Text is chunked into bounded passages along sentence boundaries (`config.MIN_PASSAGE_LENGTH = 20`, `config.MAX_PASSAGE_LENGTH = 500`).
4. Passage start positions are aligned with structural `<h1>`–`<h6>` headings using exact substring matching (`page.text.find(heading_text)`), preventing text truncation.

### Pure Python Okapi BM25 Ranking
Passages are scored using Okapi BM25:
$$\text{BM25}(D, Q) = \sum_{t \in Q} \text{IDF}(t) \cdot \frac{f(t, D) \cdot (k_1 + 1)}{f(t, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}$$
Where $k_1 = 1.2$ and $b = 0.75$. To prevent negative weights on common terms, SiteSage uses Lucene non-negative IDF:
$$\text{IDF}(t) = \ln\left(1 + \frac{N - n(t) + 0.5}{n(t) + 0.5}\right)$$
Additive explainability bonuses are applied:
- **Title Match Bonus (`+2.0`)**: Query keywords appear in page `<title>`.
- **Heading Match Bonus (`+1.5`)**: Query keywords appear in the passage's section heading.
- **Document Position Bonus (`+0.5`)**: Excerpts appearing near the top of the webpage receive a linear boost.
- **Depth Penalty (`-0.3`)**: Deeply nested URLs receive a slight penalty.

### Deterministic Evidence Extraction & Conflict Detection
Compound questions are decomposed into distinct facets using clause boundary conjunction analysis (e.g. splitting `What is X, and how much does Y cost?` into `X` and `cost of Y`).

For each facet, candidate sentences are extracted from top-ranked passages and validated against focal entity criteria. Contradiction detection analyzes semantic overlap and checks for:
1. **Negation Polarity Inversion**: Statement A affirms a property while Statement B denies it.
2. **Numeric Metric Conflicts**: Conflicting numbers or prices sharing identical units and measurement context words (`$`, `%`, `per month`, `refund days`, `users`, `storage`).

### AI Readability Polish & Safety Guardrails
When enabled, Google Gemini is provided only verified extracted claims and instructed to enhance readability. Output passes through an automated validation guard:
- **Number Conservation**: The polished text cannot introduce new numbers or omit existing figures.
- **URL Conservation**: Every source URL from verified claims must be preserved.
- **No Hallucinated Citations**: Cannot invent URLs not present in the original evidence.
- **Preserve Unanswered Aspects**: Cannot fabricate answers for aspects flagged as missing.

If any check fails, or if `GEMINI_API_KEY` is missing or rate-limited, SiteSage automatically reverts to the deterministic answer with an explanatory badge.

### Why Custom BM25 Instead of Pure LLM Scraping?
1. **Zero Hallucination Grounding**: BM25 performs mathematical keyword matching. An LLM cannot hallucinate passages into an inverted index.
2. **Explainability**: Every ranking decision displays its exact score breakdown (term frequency, IDF, title bonuses).
3. **Speed & Efficiency**: Indexing 30 pages takes under 200ms locally in SQLite, requiring zero cloud GPU compute.
4. **Cost**: Eliminates the high token costs and latency of feeding 30 full HTML pages into an LLM context window.

---

## Project Structure

```text
sitesage/
├── run.bat                     # Windows one-click launcher (creates venv, installs, checks API key, runs)
├── run.sh                      # Linux/macOS one-click launcher (creates venv, installs, checks API key, runs)
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Production container definition (Python 3.12-slim)
├── docker-compose.yml          # Docker Compose configuration with volume persistence
├── benchmark_results.json      # Serialized benchmark evaluation results
├── .env.example                # Template for environment variables
├── .gitignore                  # Git ignore rules (caches, venvs, databases, secrets)
├── README.md                   # Complete project documentation
├── backend/                    # Core Python application modules
│   ├── __init__.py             # Backend package initialization & path resolution
│   ├── main.py                 # FastAPI application entrypoint & static mount
│   ├── api.py                  # REST endpoints (/health, /api/search, /api/sessions, etc.)
│   ├── pipeline.py             # Pipeline orchestrator & SSE event broadcaster
│   ├── config.py               # Central configuration & tuneable parameters
│   ├── models.py               # Pydantic data schemas & response models
│   ├── database.py             # SQLite schema, WAL configuration & connection helpers
│   ├── crawler.py              # Question-aware priority crawler & SSRF guardrails
│   ├── indexer.py              # HTML parsing, passage chunking & inverted indexer
│   ├── ranker.py               # Pure Python Okapi BM25 ranker with explainability boosts
│   ├── extractor.py            # Question decomposition, claim extraction & conflict detector
│   ├── polisher.py             # Gemini API polisher with strict evidence boundary validation
│   └── evaluate_benchmark.py   # Benchmark evaluation runner (15 test scenarios)
├── scripts/                    # Standalone utility & validation scripts
│   ├── take_screenshot.py      # Automated headless screenshot generator
│   └── validate_real_world.py  # Live website end-to-end validation test script
├── screenshots/                # Application UI walkthrough screenshots
│   ├── 01_homepage.png
│   ├── 02_form_populated.png
│   ├── 03_live_crawl_dashboard.png
│   ├── 04_search_results.png
│   ├── 05_transparency_bm25_explainability.png
│   └── 06_session_history_drawer.png
├── static/                     # Frontend client assets
│   ├── index.html              # Semantic HTML5 interface
│   ├── style.css               # Dark-mode SaaS stylesheet
│   └── js/
│       ├── api.js              # REST client wrapper
│       ├── app.js              # Main application logic & form handling
│       ├── stream.js           # Server-Sent Events (SSE) streaming client
│       └── ui.js               # DOM rendering, hyperlinks & explainability tables
└── tests/                      # Automated test suite
    ├── test_api.py             # REST endpoint & validation tests
    ├── test_browser_e2e.py     # Selenium WebDriver browser tests
    ├── test_config.py          # Configuration loading tests
    ├── test_crawler.py         # Crawler normalization, safety & cancellation tests
    ├── test_database.py        # SQLite schema, persistence & CRUD tests
    ├── test_evaluation.py      # Benchmark recall & conflict tests
    ├── test_extractor.py       # Question decomposition & claim extraction tests
    ├── test_indexer.py         # Passage extraction & term indexing tests
    ├── test_models.py          # Pydantic schema validation tests
    ├── test_pipeline.py        # Pipeline orchestration & SSE formatting tests
    ├── test_polisher.py        # AI polisher defaults, safety & fallback tests
    ├── test_ranker.py          # BM25 ranking, IDF & field boost tests
    ├── test_source_hyperlinks.js # Node.js DOM hyperlink sanitization test suite
    └── test_source_hyperlinks.py # Backend source link traceability tests
```

---

## Automated Testing & Benchmark Evaluation

### Running the Pytest Suite

SiteSage features a comprehensive automated test suite covering API contracts, crawler safety, indexing precision, BM25 ranking accuracy, claim extraction, conflict detection, AI polishing safety, and UI DOM construction:

```powershell
# Run the full automated test suite
python -m pytest tests/ -v
```

**Actual Test Result:**
- **204 passed**, 4 skipped (E2E browser tests skip automatically when the live server is offline), 0 failed.
- Execution time: ~9 seconds.

### Running Client-Side Link Sanitization Tests

```bash
node tests/test_source_hyperlinks.js
```
**Actual Result:** All 5 test suites passed cleanly (100% OK), verifying that `javascript:`, `data:`, and malformed protocols are rejected while valid HTTP/HTTPS URLs open safely in a new tab.

---

### Running Benchmark Evaluation

Run the benchmark evaluation harness across 15 realistic search scenarios:

```powershell
python evaluate_benchmark.py
```

### Evaluation Metrics & Benchmark Results

The evaluation dataset tests factual lookups, compound questions, cross-page synthesis, numerical queries, missing information detection, and contradiction handling:

| Evaluation Metric | Measured Value | Meaning & Context |
| :--- | :---: | :--- |
| **Mean Reciprocal Rank (MRR)** | **95.8% (0.96)** | The first relevant document appears at Rank #1 in nearly all queries. |
| **R-Precision (Precision@\|Rel\|)** | **87.5% (0.88)** | Precision measured at rank $R$, where $R$ is the size of the ground-truth relevant document set. |
| **Mean Recall@5** | **95.8% (0.96)** | Relevant evidence passages are retrieved within the top 5 results across all targeted queries. |
| **Claim-to-Source Traceability** | **100.0%** | Every single extracted claim links directly to a verified source URL and verbatim quote. |
| **Question Decomposition Accuracy**| **73.3%** | Accurately isolates distinct facets in multi-intent compound queries. |
| **Raw Precision@5** | **25.0%** | *Note on metric:* Mathematically constrained by small corpus sizes where only 1 relevant document exists in the corpus ($1/5 = 0.20$ theoretical maximum). |

*Benchmark results are persisted to `benchmark_results.json`.*

---

## Security & Limitations

### Verified Security Protections
- **SSRF & Loopback Blocking**: Hardened IP checks block internal IPv4 loopbacks (`127.0.0.0/8`), private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local IPs (`169.254.0.0/16`), IPv6 loopbacks (`::1`, `fe80:`, `fc00:`), and restricted ports (`22`, `25`, `445`, `3306`, `5432`, `6379`, `11211`).
- **Same-Origin Constraint**: The crawler strictly rejects links leading to external domains.
- **Resource Constraints**: Capped at 30 pages maximum, 10s per-page timeout, 120s total session timeout, and 5 MB maximum response size per page.
- **Client-Side Sanitization**: Source URLs are strictly validated to accept only `http:` and `https:`. Links using `javascript:`, `data:`, or malformed protocols are rejected.
- **Safe DOM Construction**: The answer renderer constructs DOM nodes using `document.createElement()` and `textContent` rather than `innerHTML`, mitigating XSS risks from crawled content.

### Honest Limitations
1. **Client-Rendered SPAs**: SiteSage uses asynchronous HTTP requests (`httpx`) and BeautifulSoup4. Websites requiring JavaScript execution (e.g. heavy React/Vue/Angular SPAs without server-side rendering) will yield limited text content.
2. **Anti-Bot & CAPTCHA Protections**: Websites protected by Cloudflare Turnstile, Akamai, or strict bot-detection mechanisms may return 403 Forbidden or 429 Too Many Requests.
3. **Robots.txt Adherence**: SiteSage strictly respects `robots.txt` rules and Disallow directives; disallowed pages are skipped.
4. **SQLite Concurrency**: SQLite with WAL mode allows concurrent reads during writes; however, high numbers of simultaneous multi-page crawls share a single write connection pool.

---

## AI Tools & Acknowledgements

In accordance with hackathon submission transparency guidelines, here is the disclosure of AI tools and external technologies utilized:

- **Google Gemini API**: Utilized for the optional Stage 5 Readability Polisher (`gemini-3.5-flash-lite`), bounded by an automated evidence verification validator.
- **Google Antigravity**: Agentic development environment used for code architecture, automated test creation, benchmarking, and project validation.
- **Open-Source Libraries**: Built on FastAPI, Uvicorn, HTTPX, BeautifulSoup4, and Pydantic.

---

## Hackathon Submission Information

- **Project Name**: SiteSage
- **Tagline**: Don't search through websites. Ask them.
- **Repository URL**: `https://github.com/balafromtn/sitesage`
- **Live Deployment URL**: *[SiteSage](https://sitesage-884j.onrender.com/)*
- **Demo Video Link**: *(Insert demo recording URL here)*
- **Track / Category**: Web Search & Information Retrieval / Hackathon
- **Team Members**:
  - `balafromtn` (Lead Developer)

---

## Future Improvements

The following features are planned for future releases:
- **Headless Browser Crawler Mode**: Optional Playwright / Chromium crawler fallback for JavaScript-rendered Single Page Applications.
- **PDF & Document Parsing**: Direct indexing of linked `.pdf`, `.docx`, and `.markdown` files encountered during crawls.
- **Hybrid Semantic Search**: Optional local embeddings (e.g., ONNX-based sentence transformers) to blend vector similarity with BM25 keyword precision.
- **Domain Whitelisting & Multi-Seed Crawling**: Ability to provide multiple starting URLs across subdomains within an organization.
- **Export Formats**: One-click export of research sessions to PDF, Markdown, and CSV formats.

---

## License

This project is created for hackathon submission and evaluation. Check the repository for licensing terms before commercial distribution.
