# GridWise Smart Campus Energy Optimization System
### BUP CSE Fest 2026 Hackathon — Online Preliminary Solution

A production-ready HTTP API service & interactive command center web application that accepts 24-hour campus energy scenarios with natural-language operator notes, interprets notes using LLM structured extraction with deterministic guardrails, and solves the cost-minimizing 24-hour energy schedule using exact Linear Programming (LP).

---

## 🏛️ Architecture & Processing Pipeline

```
 ┌────────────────┐     ┌────────────────┐     ┌────────────────────┐
 │ Scenario Input │ --> │ LLM            │ --> │ Guardrail          │
 │ (JSON + Notes) │     │ Interpreter    │     │ Validator          │
 └────────────────┘     └────────────────┘     └────────────────────┘
                                                         │
                                                         ▼
 ┌────────────────┐     ┌────────────────┐     ┌────────────────────┐
 │  API Response  │ <-- │ Response       │ <-- │ LP Optimizer       │
 │     (JSON)     │     │ Formatter      │     │ Solver (PuLP/SciPy)│
 └────────────────┘     └────────────────┘     └────────────────────┘
```

1. **API & UI Layer (FastAPI & Pydantic)**: Exposes `GET /` (Interactive Web Dashboard), `GET /health`, and `POST /optimize-energy`. Strictly validates JSON shapes and handles invalid requests cleanly.
2. **LLM Interpreter Engine**: Converts 1–3 natural-language operator notes into structured directives using OpenAI (`gpt-4o-mini`) or Google Gemini (`gemini-2.5-flash`). Features an offline rule-based fallback parser for local testing or network failures.
3. **Deterministic Guardrails**: Validates note mapping order, unique ascending hour ranges (`[0..23]`), factor bounds (`0.0 <= factor <= 1.0`), and enforces `applies = false` for `no_op`.
4. **Linear Programming (LP) Optimizer**: Uses `PuLP` or `SciPy.optimize.linprog` to solve the 24-hour schedule in milliseconds, guaranteeing global cost minimization.

---

## 🌐 Deploying on Vercel (Step-by-Step)

The repository includes a pre-configured `vercel.json` for seamless Vercel deployment.

### Option A: Deploy via GitHub (Recommended)
1. Push your repository to GitHub:
   ```bash
   git add vercel.json .gitignore README.md
   git commit -m "Configure project for Vercel deployment"
   git push origin main
   ```
2. Go to [Vercel Dashboard](https://vercel.com/new) and select **Import Repository**.
3. Set Environment Variables in Vercel Project Settings:
   - `OPENAI_API_KEY`: `your_openai_api_key`
   - `LLM_PROVIDER`: `openai`
   - `OPENAI_MODEL`: `gpt-4o-mini`
4. Click **Deploy**. Vercel will automatically build the Python Serverless Function and serve your UI at `https://your-project.vercel.app/`.

### Option B: Deploy via Vercel CLI
```bash
# 1. Install Vercel CLI
npm i -g vercel

# 2. Log in and deploy
vercel

# 3. Add production secrets
vercel env add OPENAI_API_KEY
vercel --prod
```

---

## 🚀 Local Development Setup

```bash
# 1. Clone/Navigate to repository
cd "m:/BUP Hackathon"

# 2. Create virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env

# 5. Run local server
python main.py
```
Access local dashboard at `http://localhost:8001`.

---

## 🧪 Testing & Verification

Run the test suite against all 10 public sample scenarios:
```bash
pytest tests/test_sample_cases.py -v
```

---

## 🔒 Security & Secrets Policy

- **No Secrets in Repo**: API keys are excluded via `.gitignore` and `.vercel` exclusions.
- **Environment Variables**: Credentials are configured dynamically at runtime.
