"""Position model shared by lp_trader.py: exact bins, value at any price, and fee share calibrated on what nine
profitable wallets actually earned (knowledge base §17.2).

Prices are the token priced in SOL. Quote bins hold SOL, token bins hold tokens.
"""
import math

# competing liquidity a position shares fees with: L = L_A + L_B * pool volume in the last hour (USD)
L_A, L_B = 30000.0, 0.3


def bins_for(p0, lo_pct, hi_pct, step_bps, shape, sol):
    """[(price, "q"|"t", amount)] for `sol` SOL placed from lo_pct below to hi_pct above p0."""
    g = 1 + step_bps / 10000
    nb = max(1, round(math.log(1 / (1 + lo_pct / 100)) / math.log(g))) if lo_pct < 0 else 0
    na = max(1, round(math.log(1 + hi_pct / 100) / math.log(g))) if hi_pct > 0 else 0

    def weights(n, away_heavy):
        w = ([1.0] * n if shape == "Spot" else
             [i + 1.0 for i in range(n)] if (shape == "Bid-Ask") == away_heavy else [n - i + 0.0 for i in range(n)])
        s = sum(w)
        return [x / s for x in w]
    below = sol if na == 0 else (0.0 if nb == 0 else sol * nb / (nb + na))
    out = [(p0 * g ** -(i + 1), "q", below * w) for i, w in enumerate(weights(nb, True))]
    out += [(p0 * g ** (i + 1), "t", (sol - below) * w / p0) for i, w in enumerate(weights(na, True))]
    return out


def holdings(bins, p):
    """(SOL, tokens) the position holds at price p."""
    sol = tok = 0.0
    for b, k, a in bins:
        if k == "q":
            sol, tok = (sol + a, tok) if p >= b else (sol, tok + a / b)
        else:
            sol, tok = (sol + a * b, tok) if p > b else (sol, tok + a)
    return sol, tok


def value(bins, p):
    sol, tok = holdings(bins, p)
    return sol + tok * p


def density(bins, lo, hi):
    """SOL per bin where price traded vs the position's average (1.0 = even spread)."""
    cap = [(b, a if k == "q" else a * b) for b, k, a in bins]
    inb = [v for b, v in cap if lo <= b <= hi] or [min(cap, key=lambda x: abs(x[0] - (lo + hi) / 2))[1]]
    return (sum(inb) / len(inb)) / (sum(v for _, v in cap) / len(cap))


def candle_fees_usd(bins, candle, pool_fees_usd, pos_usd, vol_1h_usd):
    """Fees one 5m candle pays this position: pool fees x our share x time in range x liquidity where it traded."""
    bot, top = min(b for b, *_ in bins), max(b for b, *_ in bins)
    lo, hi = candle["low"], candle["high"]
    ov = max(0.0, min(hi, top) - max(lo, bot))
    frac = ov / (hi - lo) if hi > lo else float(bot <= candle["close"] <= top)
    if not frac:
        return 0.0
    share = pos_usd / (pos_usd + L_A + L_B * vol_1h_usd)
    return pool_fees_usd * share * frac * density(bins, max(lo, bot), min(hi, top))
