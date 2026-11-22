# Backtest reports (tracked snapshots)

Human-readable exports from Phase 3.4+ backtest runs. **No API keys, no Parquet candles.**

| File | Contents |
| --- | --- |
| `phase34_btc_summary.txt` | Console metrics table, random-baseline stats, OOS score calibration per exit model (from `summary.txt` of the latest run). |
| `phase34_btc_diagnostics.json` | Machine-readable IS/OOS diagnostics for BTCUSDT **5m / 15m / 1h** (gross vs net, SL/cost buckets, MFE, breakdowns, what-if, fee scenarios). |
| `phase34_whatif.md` | Markdown tables derived from `phase34_btc_diagnostics.json` (IS vs OOS columns). |
| `phase34_console.txt` | Full backtest CLI log for the run that produced the above. |

Regenerate by running:

```bash
python -m backtest.run --symbols BTCUSDT --tfs 5m,15m,1h --exit-models tp1_full,partial_be --reuse-signals
```

Copies land here automatically via `backtest.reports_export.export_reports`.

**Phase 3.5 edge research**

```bash
python -m backtest.data_download --research --symbols BTCUSDT,ETHUSDT,SOLUSDT --months 24
python -m research.edge_report --symbols BTCUSDT,ETHUSDT,SOLUSDT --phase all
```

| File | Contents |
| --- | --- |
| `phase35_is_selection.md` | Frozen IS feature/rule picks (timestamp + commit). |
| `phase35_is_selection.json` | Machine-readable IS selection. |
| `phase35_edge_research.md` | IS IC/quintiles/rules + OOS confirmation and verdicts. |

Gap notes live in `data/history/{SYMBOL}/download_gaps.json` (gitignored).

**BTC regime (`btc_regime`)** needs ≥200 daily bars of warmup before your LTF backtest window. Fetch ~30 months of `1d` history once per machine (data are gitignored):

```bash
# If re-downloading 1d, delete data/history/BTCUSDT/1d.manifest.json first (otherwise cached months are skipped and the merge can truncate).
python -m backtest.data_download --symbols BTCUSDT --intervals 1d --months 30 --no-funding
```

**Low-fee scenario** in diagnostics uses MEXC USDT-M **standard** tier: 0.01% maker / 0.04% taker ([MEXC fee schedule](https://www.mexc.com/fee)). BTCUSDT may be lower (e.g. 0% / 0.02%) on promo tiers.