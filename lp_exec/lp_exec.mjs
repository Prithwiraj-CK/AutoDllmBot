// Meteora DLMM executor for lp_bot.py. Prints one JSON object per run.
//
//   node lp_exec.mjs plan  <pool> <shape> <lo%> <hi%> <sol>     read-only: bin range, positions, rent cost
//   node lp_exec.mjs quote <pool> <amount> [buy]                read-only: selling <amount> token for SOL, or with buy,
//                                                               spending <amount> SOL on the token: amount out + price impact
//   node lp_exec.mjs price <pool> [n]                           read-only: token priced in SOL at the on-chain active bin; with n,
//                                                               also the liquidity (in SOL) of the n bins each side of it
//   node lp_exec.mjs wallet                                     public key + SOL balance of LP_BOT_KEYPAIR
//   node lp_exec.mjs open  <pool> <shape> <lo%> <hi%> <sol> [--simulate]
//   node lp_exec.mjs close <pool> [--simulate]                  withdraw + close every position in the pool, sell the token for SOL
//
// Any alert setup opens: one-sided SOL (lo<0, hi=0), a layer that starts below price (lo<hi<0), two-sided (lo<0<hi: the
// share of SOL above price is swapped to the token first) or one-sided token (lo=0<hi: all of it swapped).
// Read-only commands also work on pools quoted in USDC/USDT/JupUSD: prices and liquidity are then in that quote.
// open and close trade SOL pairs only. Every transaction is simulated before it is sent; --simulate stops at
// the first step. Env: LP_BOT_RPC_URL, LP_BOT_KEYPAIR (path to a keypair JSON file, never printed),
// LP_BOT_SLIPPAGE_BPS (exit swap, default 300).
import fs from "node:fs";
import { createRequire } from "node:module";
// the SDK's ESM build has a broken directory import, so load its CommonJS build
const dlmmSdk = createRequire(import.meta.url)("@meteora-ag/dlmm");
const { StrategyType, deriveBinArray, binIdToBinArrayIndex, getPositionRentExemption, MAX_BIN_ARRAY_SIZE } = dlmmSdk;
const DLMM = dlmmSdk; // the CJS module itself is the DLMM class, with the helpers attached
import { Connection, Keypair, PublicKey, LAMPORTS_PER_SOL } from "@solana/web3.js";
import BN from "bn.js";

const SOL = "So11111111111111111111111111111111111111112";
const USD_QUOTES = ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                    "JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD"];  // USDC, USDT, JupUSD
const BIN_ARRAY_RENT = 0.07143744; // SOL, paid once by whoever first touches a bin array, not refunded
const conn = new Connection(process.env.LP_BOT_RPC_URL || "https://api.mainnet-beta.solana.com", "confirmed");
const [cmd, ...args] = process.argv.slice(2);
const simulateOnly = args.includes("--simulate");
const out = (o) => { console.log(JSON.stringify(o)); process.exit(o.ok === false ? 1 : 0); };

function wallet() {
  const path = process.env.LP_BOT_KEYPAIR;
  if (!path) out({ ok: false, error: "LP_BOT_KEYPAIR is not set" });
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(path, "utf8"))));
}

// solIsX means "the quote is token X": SOL when the pool has it, else a USD stable (read-only use)
async function pool(address, solOnly = false) {
  const dlmm = await DLMM.create(conn, new PublicKey(address));
  const x = dlmm.tokenX.publicKey.toBase58(), y = dlmm.tokenY.publicKey.toBase58();
  const solIsX = x === SOL || (y !== SOL && !solOnly && USD_QUOTES.includes(x));
  const quote = solIsX ? dlmm.tokenX : dlmm.tokenY;
  if (quote.publicKey.toBase58() !== SOL && (solOnly || !USD_QUOTES.includes(quote.publicKey.toBase58())))
    out({ ok: false, error: solOnly ? "not a SOL pair (live trading is SOL pairs only)" : "no SOL or USD quote" });
  return { dlmm, solIsX, token: solIsX ? dlmm.tokenY : dlmm.tokenX, qdec: quote.mint.decimals };
}

// The alert's range is in "token priced in SOL". SOL as token Y sits in the bins below the active bin; when SOL is
// token X the pool price is inverted, so the same range sits above it.
function binRange(dlmm, solIsX, lo, hi) {
  if (lo > 0 || lo >= hi) out({ ok: false, error: `bad range ${lo}%..${hi}%` });
  const step = Math.log(1 + dlmm.lbPair.binStep / 10000);
  const below = lo < 0 ? Math.max(1, Math.round(Math.log(1 / (1 + lo / 100)) / step)) : 0;
  const above = hi > 0 ? Math.max(1, Math.round(Math.log(1 + hi / 100) / step)) : 0;
  const skip = hi < 0 ? Math.max(1, Math.round(Math.log(1 / (1 + hi / 100)) / step)) : 0;  // a layer that starts below price
  const top = hi < 0 ? -skip : above;
  const active = dlmm.lbPair.activeId;
  return solIsX ? { minBinId: active - top, maxBinId: active + below } : { minBinId: active - below, maxBinId: active + top };
}

const SHAPES = { "Spot": StrategyType.Spot, "Curve": StrategyType.Curve, "Bid-Ask": StrategyType.BidAsk };

// Bin arrays (70 bins each) cost whoever first touches one ~0.071 SOL that never comes back. 'fit' is the range cut
// down to the unbroken run of arrays that already exist around the active bin, so opening it creates none.
async function missingBinArrays(dlmm, minBinId, maxBinId) {
  const lo = binIdToBinArrayIndex(new BN(minBinId)).toNumber(), hi = binIdToBinArrayIndex(new BN(maxBinId)).toNumber();
  const keys = [];
  for (let i = lo; i <= hi; i++) keys.push(deriveBinArray(dlmm.pubkey, new BN(i), dlmm.program.programId)[0]);
  const infos = await conn.getMultipleAccountsInfo(keys);
  const exists = (i) => !!infos[i - lo];
  const size = Number(MAX_BIN_ARRAY_SIZE ?? 70), act = binIdToBinArrayIndex(new BN(dlmm.lbPair.activeId)).toNumber();
  let fit = null;
  if (act >= lo && act <= hi && exists(act)) {
    let a = act, b = act;
    while (a - 1 >= lo && exists(a - 1)) a--;
    while (b + 1 <= hi && exists(b + 1)) b++;
    fit = { minBinId: Math.max(minBinId, a * size), maxBinId: Math.min(maxBinId, b * size + size - 1) };
  }
  return { total: keys.length, missing: infos.filter((x) => !x).length, fit };
}

// A bin range back to the alert's terms: % from price for the token priced in SOL (inverse of binRange)
function rangePct(dlmm, solIsX, minBinId, maxBinId) {
  const g = 1 + dlmm.lbPair.binStep / 10000, act = dlmm.lbPair.activeId;
  const off = (id) => (solIsX ? act - id : id - act);  // bins from the active bin, in token-price terms (up = dearer)
  const [a, b] = [off(minBinId), off(maxBinId)].sort((x, y) => x - y);
  return { lo: +((g ** Math.min(a, 0) - 1) * 100).toFixed(6), hi: +((g ** b - 1) * 100).toFixed(6) };
}

async function plan(address, shape, lo, hi, sol) {
  const { dlmm, solIsX } = await pool(address);
  const { minBinId, maxBinId } = binRange(dlmm, solIsX, Number(lo), Number(hi));
  const bins = maxBinId - minBinId + 1;
  const arrays = await missingBinArrays(dlmm, minBinId, maxBinId);
  const positionRent = (await getPositionRentExemption(conn, new BN(bins))) / LAMPORTS_PER_SOL; // refunded on close
  const perToken = Number((await dlmm.getActiveBin()).pricePerToken); // on-chain now: Y per X in whole tokens
  return { ok: true, pool: address, shape, sol: Number(sol), activeId: dlmm.lbPair.activeId, minBinId, maxBinId, bins,
           price: solIsX ? 1 / perToken : perToken, // token priced in SOL at the active bin
           binArrays: arrays.total, binArraysToCreate: arrays.missing,
           fit: arrays.fit && rangePct(dlmm, solIsX, arrays.fit.minBinId, arrays.fit.maxBinId),
           rentNotRefunded: +(arrays.missing * BIN_ARRAY_RENT).toFixed(5), rentRefunded: +positionRent.toFixed(5) };
}

async function quote(address, amount, side = "sell", ctx = null) {
  const { dlmm, solIsX, token, qdec } = ctx || await pool(address);
  const buy = side === "buy";
  const inDecimals = buy ? qdec : token.mint.decimals, outDecimals = buy ? token.mint.decimals : qdec;
  const raw = new BN(Math.floor(Number(amount) * 10 ** inDecimals).toString());
  if (raw.isZero()) return { ok: true, out: 0, solOut: 0, priceImpactPct: 0 };
  const swapForY = buy ? solIsX : !solIsX; // X -> Y when we pay with whichever of SOL/token is X
  const binArrays = await dlmm.getBinArrayForSwap(swapForY);
  const q = dlmm.swapQuote(raw, swapForY, new BN(10000), binArrays, true);
  const got = Number(q.outAmount.toString()) / 10 ** outDecimals;
  return { ok: true, out: got, solOut: buy ? undefined : got, tokenOut: buy ? got : undefined,
           consumed: Number(q.consumedInAmount.toString()) / 10 ** inDecimals, priceImpactPct: Number(q.priceImpact.toString()), q };
}

async function tokenBalanceRaw(owner, mint) {
  const accts = await conn.getParsedTokenAccountsByOwner(owner, { mint });
  return accts.value.reduce((s, a) => s.add(new BN(a.account.data.parsed.info.tokenAmount.amount)), new BN(0));
}

async function send(tx, signers, label, log) {
  const { blockhash, lastValidBlockHeight } = await conn.getLatestBlockhash("confirmed");
  tx.recentBlockhash = blockhash;
  tx.feePayer = signers[0].publicKey;
  tx.sign(...signers);
  const sim = await conn.simulateTransaction(tx);
  if (sim.value.err) {
    log.push({ step: label, simulated: false, error: JSON.stringify(sim.value.err), logs: (sim.value.logs || []).slice(-6) });
    throw new Error(`${label}: simulation failed`);
  }
  if (simulateOnly) { log.push({ step: label, simulated: true }); return null; }
  const sig = await conn.sendRawTransaction(tx.serialize(), { skipPreflight: true, maxRetries: 3 });
  const res = await conn.confirmTransaction({ signature: sig, blockhash, lastValidBlockHeight }, "confirmed");
  if (res.value.err) { log.push({ step: label, sig, error: JSON.stringify(res.value.err) }); throw new Error(`${label}: failed on chain`); }
  log.push({ step: label, sig });
  return sig;
}

async function open(address, shape, lo, hi, sol) {
  if (!SHAPES.hasOwnProperty(shape)) out({ ok: false, error: `unknown shape ${shape}` });
  const user = wallet();
  const ctx = await pool(address, true);
  const { dlmm, solIsX, token } = ctx;
  lo = Number(lo); hi = Number(hi);
  binRange(dlmm, solIsX, lo, hi); // validate before spending anything
  const lamports = new BN(Math.floor(Number(sol) * LAMPORTS_PER_SOL).toString());
  const position = Keypair.generate();
  const log = [];
  try {
    let solIn = lamports, tokenIn = new BN(0);
    if (hi > 0) {  // the range above price holds the token: buy the share of SOL that sits above price (all if one-sided)
      const r = binRange(dlmm, solIsX, lo, hi), active = dlmm.lbPair.activeId;
      const above = solIsX ? active - r.minBinId : r.maxBinId - active, total = r.maxBinId - r.minBinId + 1;
      const spend = lo < 0 ? lamports.muln(above).divn(total) : lamports;
      const q = await quote(address, Number(spend.toString()) / LAMPORTS_PER_SOL, "buy", ctx);
      const bps = Number(process.env.LP_BOT_SLIPPAGE_BPS || 300);
      const before = await tokenBalanceRaw(user.publicKey, token.publicKey);
      await send(await dlmm.swap({ inToken: new PublicKey(SOL), outToken: token.publicKey, inAmount: q.q.consumedInAmount,
                                   minOutAmount: q.q.outAmount.muln(10000 - bps).divn(10000), lbPair: dlmm.pubkey,
                                   user: user.publicKey, binArraysPubkey: q.q.binArraysPubkey }), [user], "buy token", log);
      if (simulateOnly) return { ok: true, simulated: true, log, note: "the deposit needs the bought tokens, so simulation stops after the swap" };
      tokenIn = (await tokenBalanceRaw(user.publicKey, token.publicKey)).sub(before);
      solIn = lamports.sub(spend);
      await dlmm.refetchStates();  // our own buy moved the active bin
    }
    const { minBinId, maxBinId } = binRange(dlmm, solIsX, lo, hi);
    const missing = (await missingBinArrays(dlmm, minBinId, maxBinId)).missing;
    if (missing) return { ok: false, error: `range would create ${missing} new bin array(s) (rent not refunded): not opening`, log };
    const [totalXAmount, totalYAmount] = solIsX ? [solIn, tokenIn] : [tokenIn, solIn];
    const strategy = { minBinId, maxBinId, strategyType: SHAPES[shape], singleSidedX: totalYAmount.isZero() };
    // one extended position covering the whole range (up to 1400 bins), then deposits in chunks so the shape stays
    // the alert's shape across the full range instead of restarting every 70 bins
    await send(await dlmm.createExtendedEmptyPosition(minBinId, maxBinId, position.publicKey, user.publicKey),
               [user, position], "create position", log);
    if (simulateOnly) {
      return { ok: true, simulated: true, minBinId, maxBinId, bins: maxBinId - minBinId + 1, log,
               note: "deposits can only be simulated once the position exists; create position simulated OK" };
    }
    const txs = await dlmm.addLiquidityByStrategyChunkable({ positionPubKey: position.publicKey, user: user.publicKey,
      totalXAmount, totalYAmount, strategy, slippage: 1 });
    for (const [i, tx] of txs.entries()) await send(tx, [user], `deposit ${i + 1}/${txs.length}`, log);
    return { ok: true, position: position.publicKey.toBase58(), minBinId, maxBinId, bins: maxBinId - minBinId + 1, log };
  } catch (e) {
    return { ok: false, error: e.message, position: position.publicKey.toBase58(), log,
             note: "if a deposit failed after the position was created, run close on this pool to withdraw what went in" };
  }
}

async function close(address) {
  const user = wallet();
  const { dlmm, solIsX, token } = await pool(address, true);
  const log = [];
  try {
    const { userPositions } = await dlmm.getPositionsByUserAndLbPair(user.publicKey);
    for (const p of userPositions) {
      const { lowerBinId, upperBinId } = p.positionData;
      const txs = await dlmm.removeLiquidity({ user: user.publicKey, position: p.publicKey, fromBinId: lowerBinId,
                                               toBinId: upperBinId, bps: new BN(10000), shouldClaimAndClose: true });
      for (const [i, tx] of txs.entries()) await send(tx, [user], `withdraw ${p.publicKey.toBase58().slice(0, 6)} ${i + 1}/${txs.length}`, log);
    }
    // sell whatever token the position ended up holding back to SOL, capped by LP_BOT_SLIPPAGE_BPS
    const ata = await conn.getParsedTokenAccountsByOwner(user.publicKey, { mint: token.publicKey });
    const held = ata.value.reduce((s, a) => s + Number(a.account.data.parsed.info.tokenAmount.uiAmount || 0), 0);
    let sold = null;
    if (held > 0 && !simulateOnly) {
      const q = await quote(address, held);
      const bps = Number(process.env.LP_BOT_SLIPPAGE_BPS || 300);
      const minOut = q.q.outAmount.mul(new BN(10000 - bps)).div(new BN(10000));
      const tx = await dlmm.swap({ inToken: token.publicKey, outToken: new PublicKey(SOL), inAmount: q.q.consumedInAmount,
                                   minOutAmount: minOut, lbPair: dlmm.pubkey, user: user.publicKey, binArraysPubkey: q.q.binArraysPubkey });
      await send(tx, [user], "sell token", log);
      sold = { token: held, solOut: q.solOut, priceImpactPct: q.priceImpactPct };
    }
    return { ok: true, positions: userPositions.length, sold, log, simulated: simulateOnly };
  } catch (e) {
    return { ok: false, error: e.message, log };
  }
}

try {
  if (cmd === "plan") out(await plan(...args.slice(0, 5)));
  else if (cmd === "quote") { const { q, ...r } = await quote(args[0], args[1], args[2] || "sell"); out(r); }
  else if (cmd === "price") {
    const { dlmm, solIsX, token, qdec } = await pool(args[0]);
    const n = Number(args[1] || 0);
    const { activeBin, bins } = await dlmm.getBinsAroundActiveBin(n, n);
    const act = bins.find((b) => b.binId === activeBin) || (await dlmm.getActiveBin());
    const inSol = (perToken) => (solIsX ? 1 / perToken : perToken); // token priced in the quote
    const dx = 10 ** (solIsX ? qdec : token.mint.decimals), dy = 10 ** (solIsX ? token.mint.decimals : qdec);
    const r = { ok: true, activeId: activeBin, price: inSol(Number(act.pricePerToken)) };
    if (n) r.bins = bins.map((b) => {
      const px = Number(b.pricePerToken), x = Number(b.xAmount.toString()) / dx, y = Number(b.yAmount.toString()) / dy;
      return [b.binId, inSol(px), solIsX ? x + y / px : y + x * px]; // [bin id, token price, liquidity in quote units]
    });
    out(r);
  }
  else if (cmd === "wallet") {
    const w = wallet();
    out({ ok: true, pubkey: w.publicKey.toBase58(), sol: (await conn.getBalance(w.publicKey)) / LAMPORTS_PER_SOL });
  }
  else if (cmd === "open") out(await open(...args.filter((a) => a !== "--simulate").slice(0, 5)));
  else if (cmd === "close") out(await close(args[0]));
  else out({ ok: false, error: "usage: plan|quote|price|wallet|open|close (see top of file)" });
} catch (e) {
  out({ ok: false, error: e.message });
}
