# Colcap Tracker — Extension Roadmap

Detailed, phased plan for the proposed extensions. Ordered to **keep the
deployed page functional at every step** and to be **resumable**: each phase is
self-contained, ends green (tests pass), and is committed before the next
starts. If work stops mid-way (usage limit, API rate-limit, etc.) a new session
resumes from the **Status checklist** below — find the first unchecked box.

## Resume protocol (read this first on a fresh session)
1. Check the **Status checklist** — the first unchecked phase is the next task.
2. Within a phase, sub-tasks are checkboxes; continue from the first unchecked.
3. Run `pytest` to confirm the current baseline is green before adding code.
4. Finish the phase, run `pytest`, tick its boxes here, then commit to `main`
   with the repo key (see memory `colcap-repo-ssh-key`): 
   `GIT_SSH_COMMAND="ssh -i ~/mescude1_ae_mac -o IdentitiesOnly=yes" git push origin main`
5. Constraints (from `agents.md`): least dependencies (no new runtime deps —
   reuse pandas/numpy/plotly/yfinance; pytest is the only dev dep), output stays
   static HTML (GitHub Pages), every new pure function gets a unit test.

## Status checklist
- [x] Phase 1 — Fetch resilience, caching & resume
- [x] Phase 2 — Ticker resolver & coverage guardrails
- [x] Phase 3 — CSV / JSON export button
- [x] Phase 4 — COLCAP benchmark + beta
- [x] Phase 5 — Dividends & corporate-actions tab
- [ ] Phase 6 — Compare-page upgrades (overlays + shareable state)
- [ ] Phase 7 — Alerts digest (`--alerts`) + workflow wiring
- [ ] Phase 8 — Portfolio mode
- [ ] Phase 9 — Package refactor

---

## Phase 1 — Fetch resilience, caching & resume  *(foundation)*
**Why first:** protects the live page from Yahoo rate-limits, lets a throttled
run resume on the next hourly cycle, and makes the whole test suite run offline.

**Design**
- Add a tiny on-disk cache under `.cache/` (gitignored): one file per
  `symbol_interval_period` key. Use `DataFrame.to_pickle` / `read_pickle`
  (pandas is already a dep — **no new dependency**, no parquet/pyarrow).
- `cached_history(symbol_meta, history_kwargs, interval, max_age_min=60)`:
  return cached frame if fresh; else fetch, write cache, return. On fetch
  failure (rate-limit / network), **fall back to stale cache** if present and
  log a warning instead of failing the run.
- `fetch_multi` (compare): fetch per-symbol through the cache so a partially
  rate-limited batch still produces a page from whatever is cached; symbols that
  fail *and* have no cache are skipped (current behaviour) — the next run fills
  them in "as soon as the limit resets".
- Add `--no-cache` and `--cache-ttl <min>` CLI flags.

**Tests** (`tests/test_cache.py`, offline)
- Cache write→read round-trips a frame.
- Stale-but-present cache is returned when the (monkeypatched) fetch raises.
- TTL expiry triggers a refetch.
- `--no-cache` bypasses the cache.

**Keeps page functional:** yes — fetch path is wrapped, existing behaviour
preserved when cache empty. **Est:** 1 session.

---

## Phase 2 — Ticker resolver & coverage guardrails
**Why:** the `.CL` mapping is fragile — BANCOLOMBIA/PFBCOLOMBIA silently dropped.

**Design**
- `resolve_yahoo(symbol_meta)`: try the registry `yahoo` ticker, then documented
  fallbacks (e.g. `BANCOLOMBIA` → `CIB` ADR as last resort, plain `.CL`,
  uppercase variants). Cache the first ticker that returns data.
- Compare run prints a **coverage report** (`got X/N`, lists missing) and embeds
  a small "data coverage" note in `compare.html`.
- Per-symbol dashboard: if the primary ticker fails, try resolver before the
  existing multi-tier fallback.

**Tests:** resolver picks first working ticker (monkeypatched fetch returning
empty then non-empty); coverage summary counts correctly.

**Keeps page functional:** yes — purely additive fallback. **Est:** 1 session.

---

## Phase 3 — CSV / JSON export button
**Why:** quick, zero-risk, client-side; high utility.

**Design**
- In `build_html`, embed the price+indicator table as a JS array and add an
  "⬇ Export CSV / JSON" button that builds a Blob and triggers download — no
  server, no dependency.
- Same button on `compare.html` exporting the current selection's aligned table.

**Tests:** HTML contains the export button + embedded data array; functional
HTML test asserts presence.

**Keeps page functional:** yes — additive UI. **Est:** 0.5 session.

---

## Phase 4 — COLCAP benchmark + beta
**Why:** core value for Colombian investors — relative performance & risk.

**Design**
- Add an index proxy to the registry (`ICOLCAP.CL` ETF; resolver-backed).
- `calc_beta(stock_returns, index_returns)` and tracking error (pure, testable).
- Candlestick/cumulative: overlay rebased index line. New metric cards:
  **Beta** and **vs-COLCAP** excess return.
- `--no-benchmark` flag to skip the extra fetch.

**Tests:** beta of a series vs itself ≈ 1; beta vs scaled series = scale;
benchmark overlay present in HTML when enabled.

**Keeps page functional:** yes — benchmark fetch failure degrades gracefully
(cards show "N/A", no overlay). **Est:** 1 session.

---

## Phase 5 — Dividends & corporate-actions tab
**Design**
- `fetch_actions(stock)` → normalize `stock.dividends` / `stock.splits`
  (cache-backed, tolerant of empties).
- New "💰 Dividends" tab: dividend-history bar chart + trailing-yield trend +
  splits table. Hidden/empty-state when no data.

**Tests:** normalizer handles full / empty actions; tab renders with fixture
data; empty-state path covered.

**Keeps page functional:** yes — new tab, empty-state fallback. **Est:** 1 session.

---

## Phase 6 — Compare-page upgrades
**Design (all client-side in the embedded JS)**
- Normalized **drawdown overlay** for selected symbols.
- **Rolling correlation** chart (selectable window) for exactly-two selections.
- Persist selection in the **URL hash** (`#GRUPOSURA,ECOPETROL`) so a comparison
  is shareable/bookmarkable; read on load, update on change.

**Tests:** Python-side payload unchanged (existing tests hold); add assertions
that the new chart containers + hash-sync JS are present in the HTML.

**Keeps page functional:** yes — additive; default view unchanged when no hash.
**Est:** 1 session.

---

## Phase 7 — Alerts digest (`--alerts`) + workflow wiring
**Why:** leverages the new hourly schedule.

**Design**
- `--alerts` mode scans all COLCAP symbols (via cache) and emits `alerts.html`:
  RSI overbought/oversold, MACD crossovers, 52-week highs/lows, golden/death
  cross, new max-drawdown. Reuse existing indicator functions.
- Workflow: add a step generating `alerts.html`; feature it on the index next to
  Compare. Because Phase 1 caching is in place, a rate-limited scan still
  produces a digest from cached data and completes next cycle.

**Tests:** alert-rule functions on synthetic frames (each rule fires / doesn't on
crafted inputs); `alerts.html` renders.

**Keeps page functional:** yes — separate page. **Est:** 1–1.5 sessions.

---

## Phase 8 — Portfolio mode
**Design**
- `--portfolio "GRUPOSURA:0.4,ECOPETROL:0.3,ISA:0.3"` → `portfolio.html`.
- Blended return series, vol, Sharpe, **contribution-to-risk** per holding
  (covariance-based; pure functions, testable). Reuses compare fetch/align.
- Weights editable client-side with live recompute (same JS pattern as compare).

**Tests:** weights normalize; equal-weight blend equals mean of components;
risk contributions sum to total variance.

**Keeps page functional:** yes — new page/mode. **Est:** 1.5 sessions.

---

## Phase 9 — Package refactor  *(last — structural)*
**Why last:** highest churn; do once the feature set is stable.

**Design**
- Split `sura_tracker.py` into a package: `data/` (fetch, cache, resolver),
  `indicators/`, `render/` (figures, html), `news/`, `compare/`, `portfolio/`.
- Keep a thin `sura_tracker.py` entry shim so the Actions workflow
  (`python sura_tracker.py …`) and all CLI flags keep working unchanged.
- Move tests alongside modules; CI runs `pytest` unchanged.

**Tests:** entire existing suite must pass untouched (the contract). Add an
import-surface test asserting the shim re-exports the public API.

**Keeps page functional:** yes — behaviour-preserving; verified by the full
suite + a live smoke run of each mode. **Est:** 1–2 sessions.

---

## Cross-cutting definition of done (every phase)
- New runtime dependencies: **none**. Dev dep stays just `pytest`.
- `pytest` green; new pure logic unit-tested; HTML changes covered by a
  functional assertion.
- Output remains static, self-contained HTML (GitHub Pages deployable).
- One live smoke run of the affected mode before committing.
- Commit to `main`, push with `~/mescude1_ae_mac`, tick the Status checklist.
