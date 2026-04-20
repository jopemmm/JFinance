# Action Plan: Asian Market Quantitative Trading System

**Objective:** Build, backtest, and deploy a quantitative trading system explicitly optimized for Chinese (A-Shares) and broader Asian markets, with institutional-grade risk management, regulatory compliance, and operational resilience.

> **Note on naming:** This is a *quantitative trading system*, not an "AI trading bot." The quantitative core (Kalman, GARCH, Markowitz, mean-reversion) is the proven, debuggable edge. ML/DL components are *experimental overlays* that must earn their place through rigorous out-of-sample validation. This distinction matters for setting realistic expectations and making sound architectural decisions.

---

## Phase 1: Data Foundation & Integrity

Build a bulletproof data pipeline before touching any model or strategy.

### 1.1 Data Connectors

- [ ] **Data Pipeline:** Integrate **AkShare** and **TuShare** to fetch high-fidelity, historical, and real-time Chinese market data.
- [ ] **Intraday Data:** Fetch 1-minute bars via `fetch_1min_bars(symbol, date)` — required for realistic slippage modeling and VWAP/TWAP execution algorithms.
- [ ] **Data Source Failover (Gap #22):** Implement a `ResilientDataClient` that automatically falls back from primary to secondary data source on failure. AkShare scrapes financial websites and breaks frequently; Tushare has rate limits and occasional downtime. A data outage during trading hours means missed signals.
  ```python
  class ResilientDataClient:
      def __init__(self, primary_client, fallback_client):
          self.primary = primary_client
          self.fallback = fallback_client
      
      def fetch_daily_ohlcv(self, symbol, start, end):
          try:
              return self.primary.fetch_daily_ohlcv(symbol, start, end)
          except Exception as e:
              logger.warning(f"Primary data source failed: {e}, falling back")
              return self.fallback.fetch_daily_ohlcv(symbol, start, end)
  ```
- [ ] **Data Staleness Checks:** Alert if the latest data point is > 1 trading day old. Never trade on stale data.

### 1.2 Data Validation Pipeline (Gap #13)

- [ ] **Automated Quality Checks:** Implement `src/data/validation.py` with checks run on every data ingestion. Silent data corruption from AkShare/Tushare will poison all downstream signals.
  ```python
  def validate_ohlcv(df: pd.DataFrame) -> list[str]:
      issues = []
      if (df["volume"] == 0).any():
          issues.append(f"Zero volume on {(df['volume'] == 0).sum()} days")
      if (df["high"] < df["low"]).any():
          issues.append("High < Low detected")
      if (df["close"] > df["high"]).any() or (df["close"] < df["low"]).any():
          issues.append("Close outside H/L range")
      if df.index.duplicated().any():
          issues.append("Duplicate dates")
      pct = df["close"].pct_change().abs()
      if (pct > 0.25).any():
          issues.append(f"Suspicious returns >25% on {(pct > 0.25).sum()} days")
      return issues
  ```
- [ ] **Validation gate:** Block any strategy from consuming data that fails validation. Log all validation failures for manual review.

### 1.3 Corporate Actions & Survivorship Bias

- [ ] **Corporate Actions Adjustment:** Implement `src/data/corporate_actions.py` using Tushare's `adj_factor` endpoint. A-share split/dividend treatment differs from Western markets — never assume raw prices are comparable across dates without adjustment.
- [ ] **Survivorship-Bias-Free Universe:** Use Tushare `index_weight` endpoint to fetch **point-in-time** index constituent snapshots. **Never** backtest on today's index members for historical periods — this inflates returns significantly.

### 1.4 Multi-Day Suspension Handling (Gap #3 — CRITICAL)

- [ ] **Fetch Suspension Periods:** Use Tushare `suspend_d` endpoint to identify stocks under multi-day trading suspensions.
- [ ] **Backtest Integration:** If a stock is suspended, treat all orders as **unfilled**. Currently only intraday price limits are handled; multi-day suspensions (common in A-shares for restructuring, investigations, etc.) produce phantom fills in backtests and rejected orders in live trading.
- [ ] **Live Integration:** The OMS must check suspension status before placing any order.
  ```python
  def get_suspended_dates(symbol: str, start: str, end: str, pro) -> set:
      df = pro.suspend_d(ts_code=symbol, start_date=start, end_date=end)
      return set(pd.to_datetime(df["trade_date"]).tolist())
  ```

### 1.5 Intraday Lunch-Break Handling (Gap #1 — CRITICAL)

- [ ] **Trading Calendar Logic:** Add lunch-break period (11:30–13:00 CST) to the trading calendar. Without this:
  - VWAP/TWAP execution will attempt to slice orders during the break (no market → rejected orders in live)
  - Volume profile calculations will be distorted (2 hours of zero volume in the middle of the day)
  - Intraday bar calculations will produce artifacts
- [ ] **Session-Aware Execution:** Split Chinese trading day into morning session (9:30–11:30) and afternoon session (13:00–15:00). All intraday algorithms must be session-aware.
  ```python
  CHINA_SESSIONS = [
      ("09:30", "11:30"),  # Morning session
      ("13:00", "15:00"),  # Afternoon session
  ]
  
  def is_trading_time(dt: datetime) -> bool:
      t = dt.time()
      return any(
          time.fromisoformat(start) <= t <= time.fromisoformat(end)
          for start, end in CHINA_SESSIONS
      )
  ```

### 1.6 Timezone & Calendar

- [ ] **Timezone Sync:** Enforce `df.tz_localize("Asia/Shanghai")` on all Pandas dataframes to guarantee execution timing.
- [ ] **Chinese Trading Calendar:** Implement holiday calendar (Spring Festival, National Day, etc.), half-days, and session times. Use `exchange_calendars` library or build custom.

---

## Phase 2: Quantitative Engine Setup

Implement the core mathematical modules to drive decision-making. These are the **proven, debuggable edge** of the system.

### 2.1 Kalman Filter (Signal Cleaning)

- [ ] **Adaptive Kalman Filter (Gap #14):** Apply to raw market data to strip HFT noise and prevent false breakout signals. **Do NOT use static covariance parameters.** The original plan used hardcoded `observation_covariance=1.0` and `transition_covariance=0.01` — these produce very different (wrong) smoothing behavior across stocks with different volatility profiles:
  - For low-vol stocks (bank stocks ¥5-10): over-smoothing, missing real signals
  - For high-vol stocks (ChiNext tech ¥50-200): under-smoothing, passing through noise
- [ ] **Use EM calibration** to adaptively tune parameters per-stock:
  ```python
  def kalman_smooth_adaptive(price: pd.Series, em_iterations: int = 5) -> pd.Series:
      kf = KalmanFilter(
          transition_matrices=[[1]],
          observation_matrices=[[1]],
          initial_state_mean=price.iloc[0],
          initial_state_covariance=1.0,
      )
      kf = kf.em(price.values.reshape(-1, 1), n_iter=em_iterations)
      state_means, _ = kf.filter(price.values.reshape(-1, 1))
      return pd.Series(state_means.ravel(), index=price.index)
  ```

### 2.2 GARCH(1,1) (Risk Sizing)

- [ ] **Fat-Tailed Distribution (Gap #15 — CRITICAL):** Forecast daily volatility and automatically scale down position sizes when predicted volatility spikes. **Use `dist="skewt"` or `dist="ged"`, NOT `dist="normal"`.** A-share returns are empirically fat-tailed (high kurtosis), especially during regulatory interventions (circuit breakers, state fund buying). The 2015 crash, where daily limits were hit for consecutive days, would produce catastrophic losses under normal-distribution GARCH sizing.
- [ ] **Compare distributions** using BIC/AIC and select the best fit per-stock.
- [ ] **Volatility Floor:** Prevent sizing up aggressively in low-vol periods that precede crashes:
  ```python
  def forecast_vol_safe(res, horizon: int = 1, vol_floor: float = 0.01) -> float:
      fcast = res.forecast(horizon=horizon)
      raw_vol = float(fcast.variance.values[-1, -1] ** 0.5) / 100.0
      return max(raw_vol, vol_floor)
  ```

### 2.3 Monte Carlo Simulation (Risk Analysis)

- [ ] **Monte Carlo for Risk, NOT Signals:** Run GBM trajectory simulations using drift (ARIMA) and vol (GARCH) inputs. Use for **VaR, expected shortfall, and scenario stress tests** — NOT as a primary buy/sell signal. The original plan's "Buy if P(target) > 70%" framing is dangerous: Monte Carlo under GBM assumptions has no predictive edge for individual trade entry.

### 2.4 Markowitz Efficient Frontier (Allocation)

- [ ] **Portfolio Optimization:** Calculate the Optimal Sharpe Ratio portfolio to determine capital allocation. Implement with `cvxpy` for proper constraint handling (weight bounds, leverage caps).
- [ ] **Sector Exposure Caps (Gap #4 — HIGH):** Add maximum per-sector allocation constraint (e.g., max 20% per GICS sector). Per-instrument position sizing alone is insufficient — a mean-reversion strategy on A-shares will naturally concentrate in beaten-down sectors (e.g., property in 2023-24). Without sector caps, a single sector collapse wipes out the portfolio.
  ```python
  # In portfolio optimization constraints:
  sector_constraints = [
      cp.sum(weights[sector_mask]) <= max_sector_weight
      for sector_mask in sector_masks.values()
  ]
  ```

### 2.5 Overnight Gap Risk Modeling (Gap #18)

- [ ] **Gap Risk Analysis:** A-shares trade 9:30-15:00 with no pre/post-market. Overnight news, global markets, and policy announcements create large gaps at open. Stop-losses set at close are meaningless if the stock gaps down 5% at open.
- [ ] **Adjust position sizing** to account for historical overnight gap distribution per stock:
  ```python
  def compute_overnight_gap(df: pd.DataFrame) -> pd.Series:
      """Gap between previous close and current open."""
      return (df["open"] / df["close"].shift(1) - 1)
  ```
- [ ] **Call Auction Monitoring:** Consider using the call auction price (9:15-9:25) as an early indicator for gap magnitude in live trading.

### 2.6 Additional Quantitative Models

- [ ] **ARIMA/ARIMAX:** Model return dynamics; provide drift estimate for Monte Carlo.
- [ ] **Cointegration & Pairs Trading:** Engle-Granger and Johansen tests for stat-arb pairs.
- [ ] **Regime Switching (HMM):** Infer latent regimes (bull, bear, high-vol, low-vol). Switch strategy parameters per regime.
- [ ] **PCA / Factor Models:** Extract market/sector/style factors. De-correlate portfolio and control factor risk.

---

## Phase 3: AI & Machine Learning Core

Feed the quantitative outputs into ML/DL models to generate supplementary trading signals. **These are experimental overlays — the quant core must be able to run independently without any ML component.**

### 3.1 Feature Engineering

- [ ] **Feature Pipeline:** Pass the Kalman-smoothed prices and GARCH volatility metrics into `pandas-ta` to generate standard technical features.
- [ ] **Feature Stationarity (Gap #6 — CRITICAL):** **Mandate differencing and rolling-volatility normalization.** Non-stationary features (raw price, moving averages) will cause gradient boosting models to learn spurious patterns that break after regime shifts. All features must be transformed to stationary inputs:
  - Use log-returns instead of raw prices
  - Z-score normalize using rolling windows
  - Difference moving averages rather than using levels
  ```python
  # BAD: non-stationary
  features["ma20"] = price.rolling(20).mean()
  
  # GOOD: stationary
  features["ma20_zscore"] = (price - price.rolling(20).mean()) / price.rolling(20).std()
  features["log_return"] = np.log(price / price.shift(1))
  features["vol_ratio"] = price.rolling(5).std() / price.rolling(20).std()
  ```

### 3.2 Target Leakage Prevention (Gap #7 — CRITICAL)

- [ ] **Define Prediction Timestamp Convention:** Document explicitly: "Features available at time T must not use any data from T or later." Without this, leakage will creep in through feature engineering (e.g., using same-day volume for a same-day return prediction).
- [ ] **Label Generation Rules:**
  - Prediction made at close of day T
  - Features use data up to and including day T close
  - Target is return from T+1 open to T+1 close (or T+N)
  - **Purge gap:** When splitting train/test, enforce a gap of ≥ `max_feature_lookback` days
- [ ] **Use `PurgedWalkForwardCV`** for all hyperparameter tuning — never standard k-fold for time-series data.

### 3.3 Predictive Training (XGBoost / LightGBM)

- [ ] **Supervised Classification:** Train models to predict whether the asset will experience a positive or negative return in the T+1 timeframe.
- [ ] **Model Persistence:** Save/load models with versioning. Log hyperparameters, training dates, and OOS metrics for every trained model.

### 3.4 Deep Learning (LSTMs) (Gap #20)

- [ ] **Constrained Architecture:** Implement Long Short-Term Memory networks with **explicit architectural constraints** to prevent overfitting:
  - Start with minimal architecture: 1-2 LSTM layers, 32-64 hidden units, 0.3-0.5 dropout
  - Sequence length of 30 days (document why — approximate monthly trading pattern cycle)
  - Financial LSTM papers show reproducibility rates below 30% — treat with extreme skepticism
- [ ] **Use LSTM for Volatility Forecasting** rather than return prediction (more stable target). Mandate that LSTM must beat GARCH on OOS volatility forecast RMSE before being used for position sizing.
- [ ] **Consider Alternatives:** Temporal Fusion Transformers offer built-in interpretability and multi-horizon forecasting — evaluate as replacement for vanilla LSTM.

### 3.5 Reinforcement Learning (Gap #21)

- [ ] **Experimental Track Only:** Deploy an RL Agent (e.g., Ray RLlib / Stable-Baselines3) to penalize excessive drawdowns. **Treat as exploratory with hard guardrails:**
  - **Position limits within the RL action space** (not just in the risk layer) — prevent the agent from taking extreme positions
  - **Conservative reward shaping:** `reward = return − λ·drawdown − μ·leverage − ν·turnover`
  - **Penalize holding periods > N days** to prevent stale positions
  - **Behavioral cloning** from the rule-based strategy as a pre-training step
- [ ] **Success Criteria:** Must beat rule-based baseline by ≥ 50 bps after costs over 6 months of paper trading **with lower max drawdown** (proving it learned risk management, not just return chasing).
- [ ] **Auto-Disable:** Kill switch disables RL agent if paper drawdown exceeds 5%.

### 3.6 Model Ensemble & Disagreement Handling (Gap #16)

- [ ] **Signal Aggregation Layer:** Define how to combine signals from XGBoost, LSTM, and RL when they disagree:
  - Weighted average (weights proportional to recent OOS performance)
  - Majority vote with confidence threshold
  - Meta-learner (stacking) using OOS predictions from each model
- [ ] **Disagreement Protocol:** If models disagree beyond a threshold, default to **no trade** (conservative). Never let the operator make ad-hoc decisions under time pressure.

### 3.7 Feature Importance Drift Monitoring (Gap #19)

- [ ] **Log SHAP values** or permutation importance at each retraining cycle.
- [ ] **Alert on drift:** When top-5 feature rankings change significantly (Kendall tau < 0.6 vs previous period), flag for review. In Chinese markets, dominant factors rotate aggressively (value → momentum → policy sentiment within a single year).
- [ ] **Feed into HMM:** Use feature importance shifts as an input to the regime-switching model.

### 3.8 Continuous Learning (Error Correction)

- [ ] Build a "False Positives" database. Store losing trades every week and use Bayesian Updating to retrain the ML models.
- [ ] **Regime-aware retraining:** Only retrain when regime indicators (HMM state, feature drift) suggest the current model is stale — not on a fixed schedule.

### 3.9 Signal Capacity & Crowding (Gap #17)

- [ ] **Alpha Decay Awareness:** Mean reversion on A-shares using Z-scores is one of the most crowded quantitative strategies in China. Monitor for signs that the edge is eroding:
  - Track turnover-adjusted Sharpe over time
  - Monitor limit-order fill rates (declining fills = crowding)
  - Compare live vs backtest performance attribution
- [ ] **Strategy Diversification:** Implement a strategy zoo with diverse signal sources (factor-based, event-driven, cross-sectional) — not just mean-reversion and momentum — to reduce crowding risk.

---

## Phase 4: Transaction Costs & Slippage Modeling

> Ignoring costs turns profitable backtests into losing live strategies.

### 4.1 A-Share Cost Model

- [ ] **Implement `src/backtester/costs.py`** with all A-share cost components:
  ```python
  class CostModel:
      def __init__(
          self,
          stamp_duty_rate: float = 0.0005,    # 0.05% on SELL side only
          commission_rate: float = 0.00025,   # typical retail broker rate (both sides)
          min_commission: float = 5.0,         # minimum per trade in CNY
          slippage_bps: float = 5.0,           # basis points of price impact
      ):
          self.stamp_duty_rate = stamp_duty_rate
          self.commission_rate = commission_rate
          self.min_commission = min_commission
          self.slippage_bps = slippage_bps / 10_000
  ```

### 4.2 Short-Selling Constraints & Borrow Costs (Gap #5)

- [ ] **Integrate Tushare `margin_secs`** for the shortable securities list and borrow rates.
- [ ] **Borrow fee modeling:** For any short signal, subtract estimated borrow cost from expected return. If expected return < borrow cost, suppress the signal.
- [ ] **Availability check:** Before placing a short order in live, verify the stock is on the broker's shortable list. Most retail margin accounts in China have very limited short availability.

### 4.3 Market Impact for Larger Orders (Gap #8)

- [ ] **Square-Root Impact Model:** For orders exceeding 0.1% of average daily volume (ADV), replace the constant-bps slippage with a nonlinear impact model:
  ```python
  def market_impact(order_size: float, adv: float, sigma: float) -> float:
      """Almgren-Chriss square-root impact model."""
      participation_rate = order_size / adv
      return sigma * np.sqrt(participation_rate)
  ```
- [ ] **ADV tracking:** Maintain rolling 20-day average volume for each instrument to detect liquidity changes.

---

## Phase 5: Risk Management & Portfolio Controls

### 5.1 Volatility-Based Position Sizing

- [ ] **GARCH-informed sizing:** Use the fat-tailed GARCH forecast (Phase 2.2) to set position sizes. Risk per trade = `capital * risk_pct / (stop_mult * sigma * price)`.

### 5.2 Sector Exposure Caps (Gap #4)

- [ ] **Enforce maximum per-sector allocation** (e.g., 20% of gross exposure per GICS sector).
- [ ] **Cross-Asset Correlation Check:** Before adding a new position, compute marginal portfolio risk. Reject trades that push portfolio concentration above thresholds.

### 5.3 Global Leverage & Drawdown Controls

- [ ] **Leverage limit:** `L = gross_exposure / equity`; enforce `L <= L_max` (e.g., 2×).
- [ ] **Drawdown state machine:** Normal → De-leveraging (DD > D1) → Kill Switch (DD > D2).
- [ ] **Overnight gap risk adjustment (Gap #18):** Factor historical gap-at-risk into the stop distance used for position sizing.

### 5.4 Strategy Decay Monitoring

- [ ] **Rolling 63-day Sharpe ratio** in paper/live mode.
- [ ] **Alert and optionally disable** strategy when rolling Sharpe falls below 2-sigma of its historical distribution.

### 5.5 Performance Attribution (Gap #23)

- [ ] **Return Decomposition:** Implement Brinson attribution to distinguish between:
  - Alpha from signals
  - Beta (market exposure)
  - Factor exposure (accidentally loading on size/value/momentum factors)
  - Luck (small sample coincidence)
- [ ] **Track hit rate by sector, by regime, and by signal source** to identify which components contribute and which are dead weight.
- [ ] **Information Ratio:** Excess return over benchmark per unit of tracking error.

---

## Phase 6: Asian Market Compliance Logic

Hardcode regional micro-structure rules into the execution core to prevent catastrophic failures.

### 6.1 T+1 Settlement Enforcement

- [ ] Lock A-Shares immediately after purchase. Force the system to predict *Overnight* (T+1 or T+2) patterns only.
- [ ] Disable day-trading logic for Mainland China stocks.
- [ ] Track purchase date per lot; disallow selling same-day buys.

### 6.2 Limit Up/Down Detection

- [ ] Program limit-caps (10% for main boards, 20% for STAR/ChiNext).
- [ ] Abort order execution if the price is within 1% of freezing limits.
- [ ] In backtests: if a stock is at limit-up, treat any buy as **unfilled**; if at limit-down, treat any sell as **unfilled**.

### 6.3 CSRC Algorithmic Trading Registration (Gap #11 — CRITICAL)

- [ ] **Registration Thresholds:** Since 2024, firms using automated/program trading in China must register strategies under the *Provisions on the Administration of Program Trading in the Securities Market*. The registration trigger is likely the **order frequency threshold**, not AUM, for retail accounts.
- [ ] **Legal Consultation:** Engage a qualified securities lawyer to determine specific thresholds for your account type and trading frequency before any live trading.
- [ ] **Compliance Config:** Maintain `config/compliance.yaml` with strategy IDs, risk control documentation, and max-order-rate declarations.
- [ ] **Retail vs Institutional Restrictions:** Document which account type your broker provides and what restrictions apply (order-to-trade ratio limits, available order types, etc.).

### 6.4 Tax-Lot Accounting & Audit Trail (Gap #9)

- [ ] **Audit Log Table:** Implement `audit_log` schema capturing every order, fill, cancellation, and position change with timestamps and correlation IDs.
- [ ] **Cost-Basis Tracking:** Implement FIFO/LIFO cost-basis selection method. Currently less critical for retail A-shares (capital gains tax is waived for individuals), but becomes essential if operating as a fund or if regulations change.

### 6.5 FX Risk Handling (Gap #25)

- [ ] **Base Currency Definition:** Define CNY as base currency for all P&L and risk calculations.
- [ ] **HKD Conversion:** For any Hong Kong-listed stocks, fetch daily FX rates and convert positions to base currency for risk aggregation.
- [ ] **AH Premium Signal:** For cross-listed stocks, the AH premium/discount itself can be a trading signal — requires FX-aware calculations.

---

## Phase 7: Execution & Broker Integration

### 7.1 Broker Adapters

- [ ] **Futu OpenD** (`futu_client.py`) — China/HK markets. Free tier has restrictive API rate limits.
- [ ] **Interactive Brokers** (`ib_client.py`) via `ib_insync` — for Stock Connect routing.
- [ ] **QMT** (`qmt_client.py`) — institutional-grade A-share algo trading platform for higher-frequency or larger-AUM operation.
- [ ] **Broker Symbol Map:** Maintain a translation table between internal symbol format and each broker's format.

### 7.2 Broker Rate Limits & Throttling (Gap #12 — CRITICAL)

- [ ] **Throttling Decorator:** Implement rate-limiting logic that prevents API rate-limit breaches. A burst of rebalancing signals will trigger rate-limit errors and cascade into missed fills.
  ```python
  import time
  from functools import wraps
  
  def throttle(max_calls_per_second: float):
      min_interval = 1.0 / max_calls_per_second
      last_call = [0.0]
      def decorator(func):
          @wraps(func)
          def wrapper(*args, **kwargs):
              elapsed = time.time() - last_call[0]
              if elapsed < min_interval:
                  time.sleep(min_interval - elapsed)
              last_call[0] = time.time()
              return func(*args, **kwargs)
          return wrapper
      return decorator
  ```
- [ ] **Broker Capabilities Config:** Store per-broker rate limits, available order types, and restrictions in `config/broker_capabilities.yaml`:
  ```yaml
  brokers:
    futu:
      max_orders_per_second: 5
      max_orders_per_day: 10000
      supported_order_types: ["limit", "market"]
      supports_iceberg: false
    ib:
      max_orders_per_second: 50
      supported_order_types: ["limit", "market", "stop", "trailing_stop"]
      supports_iceberg: true
  ```

### 7.3 Order Management System (OMS)

- [ ] Place / modify / cancel; track order status.
- [ ] Validate against T+1 rule, limit up/down range, suspension status, eligible securities.
- [ ] **Latency buffer:** After order placement, wait 500ms–2s before querying status. Retail internet latency to Shanghai/Shenzhen exchanges is 2–5 seconds typical. Do not assume millisecond fills.

### 7.4 Execution Algorithms

- [ ] **VWAP/TWAP** using 1-minute bar volume curves — **must be session-aware** (see Gap #1, Phase 1.5).
- [ ] Respect tick sizes and lot sizes (A-shares: 100-share lot minimum).
- [ ] **Bid-ask bounce:** Include half-spread cost in slippage model for limit-order strategies.

### 7.5 Futures & Index Basis Risk (Gap #2)

- [ ] **Future module** for stock index futures data (IF, IC, IH) — enables market beta hedging.
- [ ] **Margin modeling** for futures positions.
- [ ] **Priority:** Low for initial launch (equity-only is fine), but important for short capacity and portfolio hedging as AUM grows.

---

## Phase 8: Backtesting & Validation Engine

### 8.1 Backtester Core

- [ ] Inputs: price data, strategy functions, risk manager, `CostModel` instance.
- [ ] Must use **point-in-time universe** snapshots — not current constituents.
- [ ] Must apply **price-limit fill logic** and **suspension handling**.
- [ ] Outputs: `BacktestResult` — equity curve, trade list, metrics.

### 8.2 Backtester-to-Live Consistency (Architectural Gap)

- [ ] **Single Strategy Interface:** The backtester and live execution engine must consume the **same** strategy interface. Separate codepaths are the #1 cause of "backtest looks great, live bleeds money."
- [ ] **Shadow Mode:** The live engine should be able to replay yesterday's data through the backtester and compare signals. Any divergence indicates a bug.
- [ ] **Shared Cost Model:** The backtester must use the same `CostModel` and OMS validation logic used in live (same fill simulation, same price-limit handling).

### 8.3 Backtester Determinism (Gap #24)

- [ ] **Set random seeds** in all entry points: `random.seed()`, `np.random.seed()`, `torch.manual_seed()`.
- [ ] Log the exact seed used for each backtest run.
- [ ] **Regression test:** Known backtest on fixed data must produce identical equity curve across runs.

### 8.4 Metrics & Evaluation

- [ ] Total return, CAGR, annualized volatility.
- [ ] Sharpe, Sortino, Calmar ratios.
- [ ] Max drawdown, turnover, hit rate, payoff ratio.
- [ ] **Regime-conditional Sharpe** (performance in bull/bear/high-vol regimes separately).
- [ ] Strategy selection criteria: backtest regimes must include 2015 crash, 2018 trade war, 2020 COVID, 2021-2023 tech selloff.

### 8.5 Model Validation & Overfitting Guardrails

- [ ] **PurgedWalkForwardCV** with purge gap to prevent look-ahead leakage.
- [ ] **OOS stability:** Strategy must show positive OOS Sharpe in ≥ 4 of 5 walk-forward folds before paper trading.
- [ ] **Overfit flag:** If OOS Sharpe < 0.5 × in-sample Sharpe, the strategy is likely overfit — reject.

---

## Phase 9: Infrastructure & Deployment

### 9.1 Cloud Hosting

- [ ] Deploy the Dockerized bot on a low-latency VPS located in **Hong Kong, Tokyo, or Singapore** (e.g., Alibaba Cloud or Tencent Cloud).
- [ ] **Note:** Colocation is not available for retail investors. Build latency tolerance into execution logic.

### 9.2 Docker Health Checks (Gap #26)

- [ ] **Health Endpoint:** Add a `/health` HTTP endpoint that checks:
  - Data freshness (is latest market data < 1 trading day old?)
  - Broker connectivity (can we reach the API?)
  - Position store accessibility (can we read/write to PostgreSQL?)
  - Strategy process alive (has the main loop executed within expected interval?)
- [ ] **Docker `HEALTHCHECK`** directive in Dockerfile.
- [ ] **Consider Kubernetes** with liveness/readiness probes for production deployment.

### 9.3 State Persistence

- [ ] **Position Store:** On startup, load positions from PostgreSQL. On every fill/order update, persist atomically.
- [ ] **Order Store:** Track pending/partially filled/cancelled orders. On restart, query broker for open-order status and reconcile with DB.
- [ ] **Restart test:** Simulate a bot restart in paper and confirm positions reconcile correctly before going live.

### 9.4 Database Architecture

- [ ] **Backtest:** Parquet files on disk (acceptable for read-only batch work).
- [ ] **Live:** PostgreSQL + TimescaleDB for atomic writes and concurrent reads. Do **not** use Parquet for live state — it lacks transactional guarantees.
- [ ] **Redis:** For real-time signal cache and inter-process communication.

---

## Phase 10: Monitoring, Logging & Operations

### 10.1 Logging

- [ ] Structured JSON logs with correlation IDs and symbol tags.
- [ ] Log levels (DEBUG/INFO/WARNING/ERROR) with rotation.
- [ ] Every order, fill, signal, and risk event must be logged.

### 10.2 Monitoring & Alerting

- [ ] **Prometheus metrics:** P&L, leverage, drawdown, order latency, fill rates, error rates.
- [ ] **Grafana dashboards** for real-time visualization.
- [ ] **Strategy decay alerts:** Email/Slack when rolling Sharpe falls below threshold.
- [ ] **Data quality alerts:** When validation pipeline detects anomalies.
- [ ] **Feature drift alerts:** When ML feature importance shifts significantly.

### 10.3 Kill Switch

- [ ] **Triggers:**
  - Drawdown > D2 threshold
  - Leverage > L_max for N consecutive seconds
  - RL agent paper drawdown > 5%
  - Critical connectivity or execution errors
  - Broker API rate-limit breach (Gap #12)
  - Data staleness > threshold

### 10.4 Operational Runbook (Gap #10 — CRITICAL)

- [ ] **Create `docs/operational_runbook.md`** with documented procedures for:
  - **Bot crash during trading hours:** How to assess open positions, whether to manually close or wait for restart, how to reconcile state.
  - **API outage (broker):** Switchover procedure to backup broker or manual trading.
  - **API outage (data):** Failover to secondary data source; when to halt trading.
  - **Position reconciliation failure:** Steps to manually verify positions against broker statement.
  - **Kill switch activation:** Who is notified, what manual steps follow, how to re-enable.
  - **Deployment / rollback procedure:** How to deploy a new version, and how to rollback if it misbehaves.
- [ ] **On-call rotation:** If multiple operators, define escalation paths.
- [ ] **Incident post-mortem template:** After any incident, document what happened, why, and what changes prevent recurrence.

---

## Phase 11: Strategy Lifecycle & Deployment Gates

### 11.1 Strategy Lifecycle State Machine

Every strategy must pass through defined gates — no exceptions:

```
Research → Backtest → [GATE: OOS Sharpe ≥ 0.8 in 4/5 folds] 
  → Paper Trading (3-6 months) → [GATE: 6-month paper Sharpe ≥ 0.8]
  → Live Small (1-5% AUM) → [GATE: 3-month live Sharpe ≥ 0.6]
  → Live Full

Decay detected → Demote to Live Small → Paper → Research (post-mortem)
Drawdown > 15% → Reject → Research (post-mortem required)
```

### 11.2 Pre-Live Deployment Checklist

- [ ] **Data integrity:** All validation checks pass, suspension data loaded, corporate actions applied.
- [ ] **Cost model:** Verified against actual broker fee schedule.
- [ ] **Compliance:** CSRC registration confirmed (if applicable), account restrictions documented.
- [ ] **Kill switch:** Tested and verified functional.
- [ ] **State persistence:** Bot restart test passed — positions reconcile correctly.
- [ ] **Runbook:** Operational procedures documented and reviewed.
- [ ] **Capital:** Start with very small capital (1-5% of intended AUM). Monitor for 3-6 months before scaling.
- [ ] **No impulsive tuning:** Parameter updates only through the formal strategy lifecycle, never ad-hoc during live trading.

---

## Appendix A: Gap Reference Table

| # | Gap Description | Priority | Phase | Source |
|---|---|---|---|---|
| 1 | Intraday lunch-break handling | 🔴 Critical | 1.5 | DeepSeek |
| 2 | Futures / basis risk hedging | 🟢 Low | 7.5 | DeepSeek |
| 3 | Multi-day suspension handling | 🔴 Critical | 1.4 | DeepSeek |
| 4 | Sector exposure caps | 🟠 High | 2.4, 5.2 | DeepSeek |
| 5 | Short borrow costs | 🟢 Low | 4.2 | DeepSeek |
| 6 | ML feature stationarity | 🔴 Critical | 3.1 | DeepSeek |
| 7 | Target leakage prevention | 🔴 Critical | 3.2 | DeepSeek |
| 8 | Market impact for scale | 🟢 Low | 4.3 | DeepSeek |
| 9 | Tax-lot accounting | 🟢 Low | 6.4 | DeepSeek |
| 10 | Operational runbook | 🔴 Critical | 10.4 | DeepSeek |
| 11 | CSRC registration thresholds | 🔴 Critical | 6.3 | DeepSeek |
| 12 | Broker rate limits & throttling | 🔴 Critical | 7.2 | DeepSeek |
| 13 | Data validation pipeline | 🔴 Critical | 1.2 | Own analysis |
| 14 | Adaptive Kalman filter | 🟠 High | 2.1 | Own analysis |
| 15 | GARCH fat-tail distribution | 🔴 Critical | 2.2 | Own analysis |
| 16 | Model ensemble / disagreement | 🟡 Medium | 3.6 | Own analysis |
| 17 | Signal crowding / capacity | 🟡 Medium | 3.9 | Own analysis |
| 18 | Overnight gap risk | 🟠 High | 2.5 | Own analysis |
| 19 | Feature importance drift | 🟡 Medium | 3.7 | Own analysis |
| 20 | LSTM architecture constraints | 🟡 Medium | 3.4 | Own analysis |
| 21 | RL guardrail completeness | 🟡 Medium | 3.5 | Own analysis |
| 22 | Data source failover | 🟠 High | 1.1 | Own analysis |
| 23 | Performance attribution | 🟡 Medium | 5.5 | Own analysis |
| 24 | Backtester determinism | 🟢 Low | 8.3 | Own analysis |
| 25 | FX risk for HK stocks | 🟢 Low | 6.5 | Own analysis |
| 26 | Docker health checks | 🟢 Low | 9.2 | Own analysis |

## Appendix B: Known Gaps vs Production-Grade Systems

| Dimension | This Plan | What a Full Prop Desk Would Add |
|---|---|---|
| Mathematical Foundation | ✅ Adaptive Kalman, fat-tail GARCH, HMM, PCA | Hawkes processes, optimal execution models |
| Risk Management | ✅ Drawdown state machine, vol-sizing, sector caps, gap risk | Intraday VaR limits, CVaR optimization |
| Data Handling | ✅ Survivorship-free, corp actions, price limits, suspensions, validation | Full tick data, Level-2 order book |
| Execution Realism | ✅ Slippage model, limit-hit logic, latency, rate limiting | Co-location, smart order routing |
| ML Pipeline | ✅ Stationarity, leakage prevention, drift monitoring, ensemble | Online learning, neural architecture search |
| Regulatory Awareness | ✅ CSRC compliance, audit trail, FX handling | Dedicated compliance officer, legal review |
| Operational Readiness | ✅ Logging, monitoring, state persistence, runbook | Multi-region redundancy, DR failover |
| Costs | ✅ Stamp duty, commission tiers, slippage, borrow rates, market impact | Financing costs, cross-venue arbitrage |

**Bottom line:** Implement this plan and you will have a research-grade framework that can survive real A-share markets at small scale. The "Known Gaps" table describes what separates a cautious retail-AUM system from a full institutional desk — useful as a future roadmap, not as blockers for initial deployment.
