# AutoDllmBot

Meteora DLMM tooling: a Discord alert feed with research, a backtester, and an AI liquidity trader.

| File | What it does |
|---|---|
| `discord_reader.py`, `discord_user_reader.py` | Read allowlisted Discord channels into `out/discord_messages.jsonl` |
| `pool_watch.py` | Turns pool links in that feed into alerts (chart, safety checks, Claude's setup), plus a busy-pool scanner; logs every alert to `out/alerts.jsonl` |
| `research.py` | Pool research and chart (Meteora data API, DexScreener, RugCheck) |
| `backtest_alerts.py` | Replays logged alerts on 5m candles and fees |
| `lp_trader.py` | **AI trader.** Claude picks pools, range, shape and when to re-center, close or come back, from `knowledge/DLMM_KNOWLEDGE.md` and live data; code enforces the guardrails. Paper by default |
| `lp_model.py` | Position model: bins, value, fee share calibrated on profitable wallets' real fees |
| `lp_exec/lp_exec.mjs` | On-chain executor (Meteora DLMM SDK): plan, quote, open, close. Never creates bin arrays |
| `lp_bot.py` | Retired alert-following paper bot (final: 14 trades, −0.545 SOL); lp_trader reuses its helpers |
| `send_discord.py` | Webhook sender |
| `knowledge/DLMM_KNOWLEDGE.md` | Everything learned: LP Army course, community playbook, HawkFi models, wallet study, backtests (§17) |

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd lp_exec && npm ci)
cp .env.example .env   # fill in tokens and webhooks
```

Claude runs through the local `claude` CLI (`CLAUDE_BIN`). Services run under launchd (`com.sinclair.*`).

## Safety

- Paper trading unless the owner sets `LP_TRADER_LIVE=1` and `LP_BOT_KEYPAIR` (a dedicated wallet). Live caps: 0.25 SOL per position, 0.1 SOL reserve, 1 SOL daily loss.
- `.env`, keypairs and `out/` are git-ignored. Never commit secrets.
- Research tooling, not financial advice.
