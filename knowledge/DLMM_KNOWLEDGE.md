# Meteora DLMM & LP knowledge base

Everything learned while building @SinClair_0000's LP content: the LP Army Academy course,
Meteora's docs and APIs, the community playbook from X, HawkFi's models, live pool research, and our
own wallet study, backtests and paper trades (§17). `knowledge/lp-notes.md` is the short version
the routines read; this is the full reference.

---

## 1. LP Army & the Academy

- **LP Army** (@met_lparmy) is Meteora's LP education community: free Academy at lparmy.com/academy,
  Discord with ranked roles, coaching/AMA sessions, community tools.
- **Roles seen**: Academy Trainee → **LP Army Private** (plus Engagement Squad, Degen, etc.).
- **How Private is earned (Academy path)**: complete the courses, pass **≥80% of the quizzes in
  "Practical"** to unlock the graduation task, pass the graduation task.
- **Bootcamp path (alternative)**: day 1 deposit ≥$100 in a non-stablecoin pair and hold ≥1h →
  "Boot Camp Trainee"; day 2 prove positive returns via exam + screenshots, manual review →
  NFT certificate + Private.
- **Private unlocks**: advanced training, exclusive channels, community tools (profit trackers,
  Dune dashboards), NFT certificate.

### Course map (lesson URLs)
1-1 intro & key terms · 1-4 DLMM mechanics · 2-2 LP safety · 2-3 price charts & tools ·
2-5 finding opportunities · 2-7 practical DLMM · 2-8 monitoring positions & portfolio ·
2-9 generating PnL cards. (`lparmy.com/academy/lesson-…`)

---

## 2. DeFi basics (course part 1)

- **Coin** = native to its chain (SOL). **Token** = issued on a chain (USDC on Solana).
- **CA (contract address)** uniquely identifies a token. Always use the verified CA, never the
  ticker; many tokens share a symbol.
- **CEX** custodial (exchange holds keys). **DEX** non-custodial (you sign).
- **Aggregator** (Jupiter) routes swaps across venues for better execution.
- **Validators** confirm Solana txs; staked SOL is collateral, misbehaviour is penalised.
- **RPC** = your wallet/app's connection to the network. Bad RPC or low priority fee → slow/failed txs.
- **AMM**: on-chain swaps against pooled liquidity, no order book. LPs deposit, traders swap,
  LPs earn a share of fees.
- **Concentrated liquidity**: capital focused around chosen prices → more fee capture per $, but
  the position can go out of range and become one-sided.

---

## 3. Meteora products

| Product | What it is | Key facts |
|---|---|---|
| **DLMM** | Dynamic Liquidity Market Maker: price split into discrete **bins** | You pick range, shape, bin step. Base + dynamic fees. Up to **1,400 bins/position**, resizable ranges. Some pools support limit-order style liquidity. Token-2022 support. |
| **DAMM v2** | Configurable constant-product AMM | Dynamic fees, **fee schedulers** (time- and market-cap-based, rate limiting), concentration options, **NFT positions**. Both tokens required. Fees **not** auto-compounded. **Earns MET points**. No lending yield. |
| **DAMM v1** (legacy) | Classic AMM + **Dynamic Vaults** | Lending yield on idle liquidity, auto-compounding. **PnL must be calculated manually.** One-sided deposits get **auto-swapped**. **No MET points.** |
| **DBC** | Dynamic Bonding Curve | Token launches; graduate automatically into DAMM v2. |
| **Alpha Vault** | Pre-launch deposits | Protected buys before public trading, pro-rata or FCFS. |
| **Presale Vault** | Presales | Fixed-price, FCFS, pro-rata. |
| Helpers | Zap, Dynamic Fee Sharing, Stake2Earn | Zap = enter/exit in one asset. |

### MET token & referral staking
- MET's main uses are **staking and revenue share**, not governance votes.
- **Referral Staking**: stakers get a share of eligible DLMM protocol fees.
  Cycle 1 paid $262K USDC to 3,977 wallets; Cycle 2 (ended 21 Sep 2026) paid **$700K+**, 89M+ MET
  staked, 11,000+ users referred.

### Protocol numbers (for data posts)
- **H1 2026**: LPs earned **~$140M fees on ~$32B volume**; **~75% ($105M)** from tokens **not**
  launched on Meteora.
- **August 2026**: $5.4B volume (+37.9% MoM), $27.5M fees; DLMM volume +39.8% MoM, DLMM fees +56.4% MoM.

---

## 4. DLMM mechanics (course 1-4)

- **Bin** = a discrete price container holding liquidity. Only bins that price trades through earn
  fees (the active bin does the work).
- **Bin step** = price gap between neighbouring bins in basis points. **100 bps = 1%.**
  Small step → tight spacing, calmer pairs (SOL-USDC uses 4 bps). Large step (80–200+) → wide
  spacing, survives volatility, typical for memecoins.
- **Bins needed for a range** ≈ ln(upper/lower) / ln(1 + binstep/10000).
  e.g. bin step 100, −85% → 0%: ln(1/0.15)/ln(1.01) ≈ **191 bins**.
- Pools and bins hold liquidity from many LPs; one LP leaving doesn't destroy the pool.

### The three shapes (Meteora's definitions)
| Shape | Distribution | Use when |
|---|---|---|
| **Spot** | Even across the range | Versatile default; most conditions |
| **Curve** | Stacked in the middle, tapering out | Calm / ranging markets, stable-ish pairs; most capital-efficient if price stays put |
| **Bid-Ask** | Stacked at the edges (inverse of curve) | Volatility; DCA in on dips / out on pumps; catching big swings |

- The shape is your **thesis**: pick it from what you expect price to do, not from a screenshot.
- **One-sided SOL Bid-Ask below price** = DCA into the token as it drops while earning fees.
  Risk: if it keeps dropping you end up **100% in the token**. Only on tokens you'd hold.
- Tight range = high fee density, out of range fast. Wide range = tolerance, thinner capital.

### Fees
- Base fee (set per pool, e.g. 0.04% SOL-USDC, 1–3%+ on memes) + **dynamic fee** that rises with
  volatility. Some pools have farm rewards.
- **High fee % is not automatically good**: it often just reflects extreme volatility, poor
  liquidity, or big inventory risk. The real question: *will real trading flow pay more than the
  inventory conversion, divergent loss and execution costs?*

---

## 5. Impermanent / divergent loss & PnL

- **IL / divergent loss** = value of LPing minus value of just holding. As price moves through your
  range, your mix shifts toward the falling asset.
- **Net result = fee income + token price change − divergent loss − costs** (rent, slippage, tx fees).
- **Green fees ≠ green position.** A position can be +20% in fees and −40% overall after the token
  dumps through the range. Conversely a volatile pool can be very profitable if fees outrun it.
- **USD vs SOL**: Metlex and others show PnL in **USD**; if SOL moved, the USD number moves even if
  the SOL result didn't. Always know your unit.
- The real performance question: after fees, divergent loss, price movement, slippage, rent and
  tx costs, did the **strategy** produce a **repeatable** net result?

---

## 6. LP safety (course 2-2): volume is NOT safety

A pool can show huge volume and still be manipulated, bundled, or one wallet from zero.

### Pre-entry checks
1. **Exact token CA** from a trusted source, never the ticker.
2. **Exact pool address**: same token, many pools with different bin step, fee, liquidity, locks.
3. **Mint & freeze authority**: revoked removes 2 admin risks but **does not** make it safe.
4. **Top holders & dev wallets**: concentration, linked wallets, unexplained supply control.
5. **Bundling / wallet relationships**: GMGN + **Bubblemaps** reveal wallets funded together or
   receiving tokens together. Spiderweb map = you're exit liquidity.
6. **Wash trading / fake volume**: volume insanely high vs liquidity, few unique traders, huge
   volume but price barely moves. Real flow is messy; fake flow is suspiciously smooth.
7. **LP lock for THAT pool**: a "locked" headline may refer to another pool.
8. **Token age & narrative timing**: the narrative may already be priced in or fading.
9. **Market-cap-per-holder** and other concentration signals (warnings, not decisions).
10. **Price divergence vs Jupiter / external markets**: arbs rebalance through your liquidity and
    you're the cheap side.

Tools answer different questions: **RugCheck** (authorities, risks, LP lock %), **Bubblemaps**
(clusters), **GMGN** (holders, dev, bundles), **DexScreener** (flow, charts), **Solscan** (txs),
**Jupiter** (reference price), **Meteora** (pool data). No single "safety score" replaces the process.
**Even a token that passes every check can still collapse.** Checks reduce avoidable risk, not market risk.

---

## 7. Charts & timing (course 2-3)

- **RSI**: overbought (>70) / oversold (<30).
- **MACD**: momentum and trend changes.
- **VPVR** (volume profile): where volume traded across price levels. The point of control (POC)
  and high-volume nodes are natural places to put liquidity; LP-relevant.
- **SuperTrend**: trend following. **Heikin Ashi**: smoothed candles, clearer trend structure.
- Volume analysis matters most for LPs: no trading = no fees.
- TA on new tokens is low-confidence; combine with liquidity, flow, age and safety. The goal is a
  better probability estimate, not a prediction.

---

## 8. Finding opportunities (course 2-5)

Sources: Meteora pool screens, DexScreener, GMGN, community channels, holder data.
1. Find pools with meaningful activity.
2. Compare **volume vs active liquidity vs fees** (fee/TVL, volume/TVL).
3. Check the activity is organic enough to bother.
4. Run the full safety process.
5. Pick the best mix of liquidity, fee structure, activity and manageable risk.

**"Volume is king"** = no trading, no fees. It does **not** mean the highest-volume pool is best.

---

## 9. Strategy & range selection

| Market | Shape | Side | Range idea |
|---|---|---|---|
| Downtrend (24h ≤ −30%) | Bid-Ask | one-sided SOL below | −40% to −85%; DCA in, fees on the chop |
| After a pump (24h ≥ +40%) | Spot | one-sided SOL below | −25% to −60%; catch the pullback, don't chase |
| High volatility / pool < 2 days old | Bid-Ask | one-sided SOL below | −35% to −80%, **small size** |
| Range-bound, calm | Spot (or Curve) | two-sided | ± half the 24h range (min ±8%) |

- Range width is a **risk control**. Volatile/uncertain tokens: start small, wider downside range.
- Adapt to the market regime; no setup is universal.
- These are rules of thumb used for the "example setup" panel in research charts, never advice.

---

## 10. Operating positions on Meteora (course 2-7)

- Create position; one-sided or two-sided deposit; **Ape In** for quick entry; **Zap Out** to exit
  into one asset; partial withdraw; withdraw from specific bins; rebalance / new position;
  liquidity & swap slippage; RPC and global priority-fee settings.
- Follow pool warnings before depositing.
- **Creating pools and bin arrays costs rent that is NOT refunded.**
- **Position rent IS refunded** when you close the position (closing dust positions reclaims SOL).
- **Zap Out has a bin limit**: very wide positions may need a normal withdraw + Jupiter swap.

---

## 11. Managing & exiting

**Before entry, write down**: reason, max size, holding period, range + shape, rebalance rule,
close rule, max acceptable loss.

**Out of range? Don't react emotionally.** Options: hold, compound, claim/sell fees, withdraw,
close, or open a new range. Depends on trend, token risk, liquidity, fee flow, inventory exposure.

**Close or reassess when**: price leaves the intended range · fee flow fades · volume looks
artificial · price diverges from external markets · risk profile worsens · the thesis is no longer
true · the position is too concentrated in one asset. "It might come back" is not on the list.

Don't blindly rebalance just because fees are positive.

---

## 12. Monitoring & PnL cards (course 2-8, 2-9)

- Monitor regularly: Meteora portfolio, **Ultra LP**, **Metlex**, Solscan, DexScreener, GMGN, safety tools.
- Track **realized** (closed) and **unrealized** (open) PnL. Tools calculate differently.
- **PnL cards**: find open/close txs on Solscan; Meteora keeps history for eligible closed positions;
  pool pages show position history; **Metlex** turns a position into a shareable card.
- A credible report shows: exact pool + CA, strategy + range, entry/exit txs, time in position,
  fees + net PnL, risks identified before entry, and what would have made you exit.
- Never present a profitable result as proof the token was safe.

---

## 13. The professional LP mindset

1. Plan, not emotion. 2. Try to **disprove** the trade before justifying it. 3. Verify exact token
and pool. 4. Volume = fee opportunity, not safety. 5. Match shape and range to the market.
6. Start small when testing. 7. Monitor and react to evidence. 8. Some trades should be passed on.
9. Record outcomes and improve. 10. Never risk money you can't lose.

The goal isn't finding a pool that can't rug. It's filtering hard, sizing rationally, earning fees
when real flow exists, and exiting when the thesis breaks.

### Pre-entry checklist
- [ ] CA from a trusted source  - [ ] exact pool address  - [ ] mint/freeze authority
- [ ] top holders, dev, bundling, insider links  - [ ] wash-trading risk
- [ ] active liquidity vs volume vs fees  - [ ] LP lock on this pool  - [ ] price vs Jupiter
- [ ] chart structure + volume  - [ ] shape, bin step, range  - [ ] size + max loss
- [ ] exit and out-of-range rules written down

---

## 14. Lessons from live research (Oct 2026)

- **AUTON-SOL**: top pool by fee/TVL on 7 Oct (fee/TVL 74%, $12.8M vol on $315K TVL, 40x vol/TVL,
  21h old, rugcheck clean, freeze revoked). **Next day: −72% on the day.** A clean safety check
  and huge fees on a <1-day-old pool still meant a knife.
- **GOMO-SOL** (8 Oct): fee/TVL 51%, $600K vol on $39K TVL, but −50% on the day and a 500%+ 24h
  range; volume already fading. Example setup: Bid-Ask, one-sided SOL, −85%→0%, ~191 bins.
- Top fee/TVL lists are dominated by **< 2-day-old memecoin pools**. Treat high fee/TVL there as a
  volatility signal as much as an opportunity.
- Same token often has **several pools** (different bin steps 80/100/125/200). Compare them.

---

## 15. Community playbook from X (harvested Oct 2026)

Distilled from ~2,200 tweets on DLMM teaching/strategy (28 searches, Top-ranked) plus ~340 posts by
**@EvilPanda**, one of the most-followed LP Army teachers (posts consistent +100–250 SOL months).
Paraphrased, credited by handle. These are what experienced LPs say they do, not advice.

### 15.1 The four parts every strategy needs (EvilPanda)
**Coin selection → pool selection → entry criteria → exit criteria.** Get those four down and you can
LP from a phone without stress. **Coin selection is ~80% of the result**; a "90% token selection,
5% discipline, 5% luck" split is echoed by others (@findocere). No shape or range saves a scam coin.

### 15.2 Evil Panda Strat: SOL-sided, wide, from near the top
The idea: be the **last, widest pool** so every panic seller, bundler and stop-loss pays you fees on
the way down, then exit on the first bounce.
- **Screen**: DexScreener filter MC ≥ $250K and 24h vol ≥ $1M, sort by age, skip tokens with no
  image/profile. GMGN: total fees > 30 SOL, phishing < 30%, bundling < 60%, insiders < 10%, top-10 < 30%.
  Avoid very new tokens: after a run of rugs he added **"only coins ≥ 12h old"** (elsewhere: skipping
  < 4h old removes most rugs; if you go that early, use −99%).
- **Pool**: **high base fee (5% or 10%)** with bin step 80/100/125 (also 200/10%). Range **−86% to
  −95%** (one example: −90% on 80/0.8% ≈ 290 bins; −95% on 125/10%).
- **Entry**: 15-min chart, wait for price to **break above SuperTrend**, then open one-sided SOL
  (Spot preferred, Bid-Ask OK). Don't chase pumps; it's fine to open below ATH when a dump is expected.
- **Exit = confluence of 2 signals** (15m, or 5m when busy): **RSI(2) closes > 90** AND either
  **price closes above the upper Bollinger Band** or **MACD prints its first green histogram bar**.
  A SuperTrend support break is the cue to start watching for the exit. When profit is unusually big,
  take it and move on; don't milk it.
- **Why Spot over Bid-Ask here**: coins often dump only ~50% before bouncing; Spot earns far more fees
  in the upper part of the range. The −95% width is **rug insurance**, not where the fees come from.
- **Why wide**: capital-inefficient, yes, but price stays in range through a −80/−90% dump, fees keep
  printing, and a small bounce can turn it green. Wider range = lower breakeven. He calls it peace of
  mind and better sleep.
- If the exit signal fires and you're red: wrong coin, or opened too high in a crowded pool.

### 15.3 Fee tier & pool choice
- **New/volatile coins (< ~12h): use 5–10% pools.** More fees per crossing, and in a rug the fees
  offset more IL. One rug in a crowded 2% pool convinced him to never go under 5% in volatile periods.
- A **100/2% pool on a brand-new coin** can be someone offloading DAMM bags, or the dev wanting to pay
  less when they rug.
- After a rug, when the token **consolidates**, a 100/1% pool can farm the sideways chop well.
- Same token has several pools: compare bin step/fee/TVL and pick by the **correction size you
  expect**, not the highest TVL.
- Test fee tiers safely in the **LP Army Playground** (simulated money), e.g. 1% vs 5% on the same coin.
- **Pool structure risk** (EvilPanda): if ~25% of a pool's TVL is copy-traders of one wallet, when
  that wallet closes they all dump together, a big inorganic red candle. Check who is in the pool
  ("pool originality"); LP Agent shows top LP wallets per pool.

### 15.4 Bonus Stage / multi-day two-sided Bid-Ask (EvilPanda's 2026 main strat)
Originally from @bengsharksol; ~10 iterations later it's a multi-day chop farm:
1. Find a coin that **dumped hard and is now chopping sideways** but isn't dead (volume, narrative,
   real buyers and sellers).
2. Open a **two-sided Bid-Ask** with **Ape In** (default range, 69 bins ≈ 34 below / 34 above).
3. If price bleeds out of range, **layer another two-sided BA near the new low** (multi-layered).
4. **Take profit on the pump**, wait for the next dump, repeat until the trend looks finished.
- **Never "top-blast"**: don't open two-sided BA near highs; wait for the dump.
- Choppy coins are the dream; even "dead"-looking coins that chop sideways keep paying.
- Needs a hard rule that says **"this coin is done, move on"**; that took him months and losses.

### 15.5 Token-sided Bid-Ask: DCA out with fees
- Buy a token low, put it in a **one-sided token Bid-Ask above price**: it sells progressively into
  strength (more as price rises) and earns fees in the chop. Several examples beat plain holding
  (e.g. +117% vs ~+46% hold; profitable exit 54% below entry thanks to fees).
- **Flip pattern**: SOL Bid-Ask below → price dumps through it (now holding token) → close and reopen as
  **token Bid-Ask above** to sell the bounce (EvilPanda, @0xyunss). 0xyunss variant: after a 70–80% dump
  and slight retrace, tight 15–30% SOL BA; exit/flip on a **5m SuperTrend break** into a token BA with a
  wide (≈200%) upside range.
- Using a fixed ~100-bin token range forces you to take profit when it goes out of range above.
- **Big holders exiting**: a narrow token-side Bid-Ask sells a large bag without the price impact of a
  market sell, and earns fees doing it (@0xIcedMilo, Meteora's single-sided take-profit guide).

### 15.6 Spot vs Bid-Ask vs Curve (evidence)
- @ConstantineDeFi ran Spot (5 SOL) vs Bid-Ask (20 SOL), both SOL-sided −90%, same time: **Spot earned
  about as much in fees at ¼ the size** while price stayed in the upper third. After a > −30% dump BA
  caught up, and BA's **lower average entry** put it in profit after only a +15% bounce (Spot needed ~+36%).
  Rule of thumb: Spot if it chops near the top, BA if it dumps deep before bouncing.
- @findocere: **Spot** when volume is spread across all prices; **Bid-Ask** when you expect a flash dump
  before volume arrives; **Curve** when you expect the volume concentrated around one level.
- Mixes are common: 50/50 BA+Spot, 70:30 BA:Spot for more fees (@0xyunss).

### 15.7 Risk, sizing & discipline
- **Cut at the bottom of the range** (@ChivesWork): below −50% is "hell mode", where a $500 position at the
  range floor can halve again in seconds. Plot the range bottom on the chart and be ready to eject.
  (EvilPanda's wide strat instead holds through, by design: different strategies, different rules.)
- **Diversify**: at least 6 positions (EvilPanda), 8–10 in volatile times; small wallets ≤ ~70% in one
  pool unless A+.
- **Size by risk**: bigger only in wider/safer setups; increase size only as a reward for a clean day;
  start with 0.5–1 SOL positions until the strategy is yours.
- **No revenge LP**; after a loss take a break. After a big loss: calculate it honestly, **don't bet
  bigger**, rebuild confidence with small positions (ChivesWork).
- **Don't babysit overnight**: EvilPanda doesn't open after ~6pm unless the setup is wide; several LPs
  vibe-coded bots that **only close** positions on their rules (entries stay manual).
- **Know your temperament**: tight "Heart Attack" ranges suit screen-watchers; wide ranges suit people
  who can't watch all day. Copying someone else's strategy fails under pressure.
- The beginner cycle everyone reports: easy wins → first rekt → recover → over-confidence → bigger rekt →
  quit or rebuild. Track every trade's data and review it (even with AI) to find your edge.

### 15.8 Market regime: the weekly DLMM cycle (EvilPanda)
**Normal** (≈1 good coin/day) → **hot** (many runners, everything prints) → **crime season** (good-looking
coins rug early, 1–2 days) → **dry** (volume gone, few or no setups) → repeat. Get **less aggressive
when it's hot** (crime season is next), more aggressive once the dry season ends. In dry markets doing
nothing is a valid position. In a "high print" regime (many tokens > 10% 24h fee/TVL) one LP ran an
**equal-size basket of 15+ tokens** (≥ 24h old, MC ≥ $300K, −50% to −95%, Spot or 50/50 BA+Spot) and
closed everything after 15–24h on total PnL (@0xMrBeefman). Only works in that regime.

### 15.9 Blue-chip & DCA uses
- **DCA into SOL with USDC**: one-sided USDC Spot in SOL-USDC 10/0.1% (70 bins). After 2 days, converting
  everything to SOL gave ~7% more SOL than a straight market buy (EvilPanda).
- **Accumulate BTC**: single-sided USDC Bid-Ask ~40% below price in cbBTC/USDC (348 bins), collecting
  fees while it waits (@satsmonkes).
- Tight SOL-USDC (bin step 4, 0.04%) can show ~1%+ daily while in range; compounding helps, but it's
  out of range fast (@molusol).

### 15.10 Product changes worth knowing (2025–2026)
- **Dynamic positions**: up to **1,400 bins** per position (was 69), so no more stitching 10 positions;
  low bin steps (20) work with wide ranges; Bid-Ask/Curve shapes no longer "sawtooth". Old 69-bin range
  tables (80 bs ≈ −40%, 100 ≈ −50%, 125 ≈ −57%, 200 ≈ −74%, 250 ≈ −81%, 400 ≈ −93%) only apply to a
  69-bin position such as Ape In's default.
- New combos like **20/2%**; dynamic fee rides on top of the base fee.
- **Ape In** (one-click entry), **Auto-Fill + Zap** for two-sided positions straight from SOL.
- **Dynamic Terminal** (Mar 2026): trading-terminal layout, bin lines on the chart, precise min/max.
- **Quote Token Fees** (May 2026): earn DLMM fees fully in SOL, USDC or a chosen token.
- **Referral Staking** (Jul 2026): stake MET, share DLMM protocol fees, refer LPs.
- **DLMM Pro** (announced Oct 2026): launch → open liquidity without migrating, configurable dynamic fees,
  choose fee token, LP + on-chain limit orders in the same pool.
- Double-sided LP swaps routed through pumpswap can earn pump.fun **cashback** (check the app).

### 15.11 @0xMrBeefman's LP thread (Oct 2026)
- **Fees are a position too**: claim and sell (or hold) fees according to what you expect the token to do,
  not by habit.
- **Check pool price vs market before entry**: if the DLMM pool is 10–20%+ off Jupiter, arbs trade through
  your liquidity and you're the cheap side (he showed deposits losing up to 99%). Use the app's
  **Sync with Jupiter** first. Add in parts, not all at once.
- **Wide ≠ safe**: a very wide range with low fees is just inefficient. He prefers −50/−60% and accepting a
  20–30% loss over sitting in a −95% range hoping for a pump.
- **Hybrid ≈ Bid-Ask on IL, but prints near entry**: Bid-Ask at market earns almost nothing while price sits
  at the top of its range; a hybrid (Spot near price + Bid-Ask below) earns from the start. He now runs
  mostly hybrids or Spot.
- **Timing**: Friday evening and all of Saturday (EU time) are the worst for slow cooks (thin flow).
- **Don't open at market**: place the range below price and let it come to you, unless fees are high
  *right now*.
- His four rules: avoid tokens likely to dump hard · only pools that are printing · enter at your own
  levels · cut a position that isn't printing, even if price is mid-range.

### 15.12 HawkFi automation models (whitepaper, Oct 2026)
HawkFi automates DLMM positions; two of the profitable wallets studied (§17) run through it. Its models are
named recipes worth knowing as setups:
- **HFL (High Frequency Liquidity)**: tight range, **swapless auto-rebalance the moment price leaves it**
  (0-minute), fees collected into SOL; for high-volume pools with active price movement. Base model has a
  stop loss on a 20% pool-price drop. Tight / Wide variants.
- **Precision Hybrid**: 50% Spot + 50% Bid-Ask kept around the active bin and reshaped as price moves:
  fees near price plus swing gains; 69 bins (Wide 149, Ultra Wide 250); **+ Rebalance** adds Ping Pong
  so the whole range follows price.
- **Precision Curve**: concentrated Curve, reshaped often ("2x fee concentration"); calm, high-volume pools.
- **Precision Flip**: alternates between fee mode in volume spikes and swing mode in volatility spikes.
- **Multi-day Cook Up (MCU)**: Spot + auto-compound + **up-only** auto-rebalance, for multi-hour to
  multi-day LP in sideways or rising markets (Curve variant is more aggressive).
- **Heart Attack**: tight Spot for **shallow** corrections in early, high-volume launches (Wide = deep
  corrections; **Ping Pong / Bid-Ask-Flip** = flips liquidity to sell the retrace).
- Building blocks: Reshape Liquidity, Auto-rebalance (swapped / swapless / Ping Pong), Auto-compound,
  Auto-accumulate fees, Take Profit, Stop Loss.
- The common thread: **keep liquidity where price is trading and move it when price moves**. That is what
  the profitable wallets do by hand or by bot (§17).

### 15.13 Content angles this gives @SinClair_0000
Explain *why* wide-range SOL-sided works (fees from panic sellers); Spot vs Bid-Ask in one picture;
the 2-indicator exit; why 5–10% pools on new coins; the weekly crime/dry cycle; copy-trader pool risk;
"green fees ≠ green position" with a token-sided example; the DCA-into-SOL math. Credit teachers by
handle when using their frameworks; never present their PnL as yours.

---

## 16. Data sources & APIs (all free unless noted)

| Source | Endpoint | Gives |
|---|---|---|
| Meteora DLMM data API | `https://dlmm.datapi.meteora.ag` | `GET /pools` (`sort_by=fee_tvl_ratio_24h:desc`, `filter_by=tvl>25000 && volume_24h>250000 && is_blacklisted=false`), `/pools/{addr}`, `/pools/{addr}/ohlcv?timeframe=30m|1h&start_time&end_time` (**always pass end_time**), `/portfolio?user=`, `/positions/{pool}/pnl?user=`, `/stats/protocol_metrics`. OpenAPI: docs.meteora.ag/developer-guides/dlmm/api-reference/openapi.json |
| Pool fields | | tvl, volume/fees/fee_tvl_ratio per 30m/1h/2h/4h/12h/24h (fee_tvl_ratio is already in **%**), pool_config (bin_step, base_fee_pct), dynamic_fee_pct, token_x/y (holders, market_cap, freeze_authority_disabled), created_at (ms). OHLCV price = token_y per token_x |
| DexScreener | `api.dexscreener.com/latest/dex/pairs/solana/{a,b,c}` (up to 30) | buys/sells m5/h1/h6/h24, priceChange, liquidity, fdv, socials. Page screenshots are unreliable (stale candles, Cloudflare); use the API |
| RugCheck | `api.rugcheck.xyz/v1/tokens/{mint}/report/summary` | score, risks[{level,name}], lpLockedPct |
| twitterapi.io (paid) | `api.twitterapi.io/twitter/tweet/advanced_search`, `/twitter/user/last_tweets`, `/oapi/my/info` | ~$0.15/1K tweets; header `X-API-Key`; balance = recharge_credits + total_bonus_credits (100K credits = $1) |
| Meteora app | `app.meteora.ag/dlmm/{pool}` | open a position on that exact pool |

---

## 17. What the data says: profitable wallets, backtests, paper trading (Oct 2026)

Our own measurements. Where they disagree with a teacher's rule of thumb, they describe what *made money*
in the period measured, not a law.

### 17.1 Nine profitable wallets (Valhalla/Meteora data, 1,066 positions from their last 30 days)
Combined: **+125.7 SOL on 25,727 SOL deployed (+0.49% per position)**; fees 291 SOL, price/IL −166 SOL.
Win rates 63–83%. Their edge is fees outrunning IL, many times a day, with small losses.
- **Holds are short**: median hold 2 min (8D1m, FEFB), 13–27 min (FehD, BBRQ, 7aDH/HawkFi), 2–5 h
  (Df2E, EuPt/HawkFi), 18 h (2Djf, the slow cooker). Holds over **24 h are the only bucket that loses on
  average** (−0.42%, worst 10% −3.1%); 12–24 h holds were best (+2.5%).
- **They follow price**: 35–71% of positions are reopened in the same pool **within 3 minutes** of closing
  (re-centering / rebalancing). 6–25 positions open at once; 7–38 positions a day.
- **Ranges**: median ~70 bins (one bin array, no extra rent) up to ~150; SOL below price with the bottom at
  −50% to −78%, or two-sided roughly −40/−65% → +3/+8%. Ranges extending >15% above price did badly
  (win 55%, worst 10% −13%). Under 40 bins: worst 10% −4.8%.
- **Pools**: bin step 100 dominates (80–125 common); base fee 1–2% (up to 5%); 1h volume before entry
  median $13K–150K; usually entered after a run-up (1h +2% to +89%) but 15–45% under the 24h high.
  Pool age varies by style (median 1–2 h for the fast scalpers, 85–100 h for the slow ones).
- **Losses stay small**: worst 2% of positions −10.5%, worst 1% −31%: almost all brand-new pools (< 1 h)
  that rugged. Falling knives (1h move < −20%) won only 50%.
- **Size**: median deposit 3–50 SOL, so bin-array and position rent are noise to them.
- **What doesn't separate winners from losers**: pool age beyond the first hour, 24h-high distance,
  volume above ~$30K/h, bin step, base fee. Management (short holds, re-centering, leaving when flow
  dies) matters more than pool picking.

### 17.2 Fee capture (calibrated on those wallets' real fees)
Replaying their real positions through a fee model: share of a pool's fees ≈ position $ ÷ (position $ +
L), with competing liquidity **L ≈ $30K + 0.3 × the pool's 1h volume**, weighted by how much of the position
sits in the bins that traded (Bid-Ask is thin near price, so it earns less there). That reproduces their
average fee (≈3% per position for 5 min–24 h holds). Our old paper model (share = $ ÷ TVL) was in the
same ballpark on average but not checked against reality before.

### 17.3 Backtests
- **Our alert feed, 55 alerts, 5m candles**: holding 72 h loses (−$203 per $100 × 55); a small take-profit
  (+2% incl. fees) with Bid-Ask −90% was slightly positive (+$43, 91% win) **before rent**; −60/−75%
  ranges all lost; a 10% take-profit lost. Rent (0.071 SOL per new bin array) wipes a +2% win on a
  0.5 SOL position.
- **Wallet-style strategy on 354 pools the wallets traded (1,005 trades, 40 days, 5 SOL each)**:
  pick a pool ≥ 6 h old with ≥ $60K volume in the last hour and not down > 20% in the last hour → **Spot
  from +5% above price to −90%** (only if the bin arrays exist) → close and reopen when price is 6% above
  entry (70% of exits) · close when 30-min volume < $5K · close below the range bottom · max 12 h.
  Result **+3.0% per trade, 95% win, worst 2% −1.1%**; on pools the parameter search never saw +3.1%; on
  our own alert pools (not wallet picks) +2.2%, 97% win; with 15% sell slippage still +2.5%.
  Depth matters most: −80% → +2.5% (worst 2% −8%), −70% → +1.8% (worst 2% −24%). Pools ≥ 1 h instead of
  ≥ 6 h: worst 2% −17%. **Spot beat Bid-Ask** once fees were weighted by where liquidity sits.
  Caveat: a model, calibrated on averages; real results will be worse than a 95% win rate.

### 17.4 Paper trading (alert-following bot, Oct 2026)
- 7 of 7 take-profits closed +1.5% to +2.1%, most with price 16–35% **below** entry (fees covered it).
- Losses came from things the rules didn't handle: **bin-array rent** (GME: trade +3.4%, result −11%),
  a **14-minute-old pool that rugged 87% in 20 min** (MUSK2028, liquidity now $0), and **holding a
  crashing fresh pool for days** (Moustache −40% at 60 h). Losers shared one sign: **the pool's liquidity
  left** (TVL $0–$2.5K afterwards).
- The data API price can lag minutes on fast pools; read the active bin on-chain for entries.
- Fixes: never create bin arrays (cut the range to existing arrays or skip), on-chain entry price.

### 17.5 Strategy menu by market condition (how the pieces fit)
| Condition | Setup | Source |
|---|---|---|
| Hot pool (≥ $60K/h), ≥ 6 h old, not a falling knife | Spot +5%/−90%, re-center when price runs +6%, leave when volume dies, ≤ 12 h | §17.3, §17.1 |
| Strong coin pumping near ATH, real volume, clean holders | SOL-sided Spot −86/−95% in a 5–10% pool after a 15m SuperTrend break; exit on RSI(2) > 90 + upper BB | §15.2 |
| Dumped hard, now chopping sideways, still has buyers | Two-sided Bid-Ask (Bonus Stage), layer near lows, TP on pumps | §15.4 |
| Price at the top of a calm range, steady flow | Hybrid (Spot near price + Bid-Ask below) or MCU-style Spot, up-only rebalance | §15.11, §15.12 |
| Holding a bag after a dump | Token-sided Bid-Ask above price (DCA out with fees), or flip SOL BA → token BA | §15.5 |
| Pool < 1–6 h old | Skip, or tiny size with −99% and a 5–10% fee pool | §15.2, §17.1 |
| Falling knife (1h < −20%), liquidity leaving, pool vs Jupiter gap > 10% | Skip / close | §17.1, §17.4, §15.11 |
| Dry market, or Fri evening–Sat for slow cooks | Do less, smaller | §15.8, §15.11 |
