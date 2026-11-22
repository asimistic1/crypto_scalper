# Crypto Scalper — manual trading assistant

Phase 4 reframes this project as a **manual trading assistant**, not an automated signal bot.  
Phases 3–3.5c (see [`reports/`](reports/README.md)) showed no durable edge after fees on BTC/ETH/SOL for the built-in setups and tested features.

## Run locally

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # set APP_PASSWORD_HASH
streamlit run streamlit_app.py
```

Use the project venv (Python 3.13). Data under `data/` is gitignored.

## Pages

| Page | Purpose |
| --- | --- |
| **Live** | Chart analysis, trade planner, optional pattern labels with Phase 3.4 warnings, alerts |
| **Journal** | Plan → execute → review; stats and CSV export |
| **Watchlist** | Multi-coin context (trends, zones, funding) — information only |
| **Test idea** | Custom rule backtest with IS/OOS lock protocol |
| **Settings** | Fees, risk defaults, watchlist, timezone |
| **Backtest** | Phase 3 research UI (unchanged engine) |

Nothing in the Live planner sends orders to any exchange.

## Security

- Password gate (`APP_PASSWORD_HASH`), Streamlit XSRF, chart CSP
- SQLite with WAL; parameterized queries; `data/journal.db`, `data/settings.db`, `data/alerts.db` stay local
- Pinned dependencies; run `pip-audit` before deploy

## Why automatic signals were removed

See `reports/phase34_*`, `reports/phase35c_edge_research.md` — expectancy after fees was negative across automatic setups; the UI now shows context and tools for **your** decisions only.