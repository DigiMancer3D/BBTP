# 🟠 BTC Block Time Predictor (BBTP)

**Optimized Dynamic Bitcoin Block Time & Prediction GUI**

A standalone Python/Tkinter application that syncs Bitcoin blockchain data, builds persistent caches, predicts future block times, and provides live analytics, notebooks, and maths behind every estimation.

**Current Version:** Optimized Dynamic (2026) — fully responsive, non-blocking, self-correcting predictions.

---

### 0. How to Install

1. Make sure you have **Python 3.8+** installed.
2. Download or clone the repository:
   ```bash
   git clone https://github.com/DigiMancer3D/BBTP.git
   cd BBTP
   ```
3. (Recommended) Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate    # Linux / macOS
   # venv\Scripts\activate     # Windows
   ```
4. Install required packages:
   ```bash
   pip install requests pillow
   ```
5. Run the program:
   ```bash
   python3 BBTP.py
   ```

On first run the program automatically creates all necessary files (`BBTP.crumbs`, `BTC.chain`, etc.).

---

### 1. All Sync Setups — How They Work

The program uses **threaded, non-blocking syncs** with a shared stop event, live progress bars, and automatic pause/resume based on API health.

| Sync Type              | What it does                                                                 | When to use it                          | Uses temp file? | Updates live? | Phase 3 behaviour                     |
|------------------------|------------------------------------------------------------------------------|-----------------------------------------|-----------------|---------------|---------------------------------------|
| **🔥 Quick Sync**      | Catches up recent blocks + ~2000-block backward scan                        | Daily use / when < few hundred blocks behind | Yes             | Yes           | Only refreshes newly added blocks     |
| **🔄 Full Backward**   | Fetches from tip all the way to Genesis (block 0)                           | First run or after long absence         | Yes             | Yes           | Only logs missing data                |
| **🔄 Refresh**         | Scans cache for incomplete blocks and fixes them                             | After any sync or when gaps appear      | Yes             | Yes           | Full multi-pass (user-controlled)     |

**Key smart behavior:**
- Every sync updates **Live Fetch Progress** after every **3 blocks**.
- **Sync Progress bar** shows phase + % and auto-pauses when APIs are on cooldown.
- **BBTP.temp** stores unfinished work so you can resume after a restart.

---

### 2. How All Data Is Determined (Estimations & Predictions)

#### Live Predictions (auto-updated every new block)
Uses rolling averages from the last ~2016 blocks with self-correcting trend adjustment.

| Field                    | How it is calculated (formula)                                      | Data used                  | Minimum blocks needed |
|--------------------------|---------------------------------------------------------------------|----------------------------|-----------------------|
| Next Diff Adj            | `2016 - (current % 2016)`                                           | Current height             | 1                     |
| Est Hashrate             | `avg_hr × (1 + (target - current) × 0.00008)` + trend adjustment   | Last 2016 blocks           | 3                     |
| Est Price                | `avg_price × (1 + (target - current) × 0.00006)` + trend adjustment| Last 2016 blocks           | 3                     |
| HR/Price                 | `est_hr / est_price`                                                | Adjusted values            | 3                     |
| Est Tx                   | `avg_tx × 1.015`                                                    | Last 2016 blocks           | 3                     |
| Est Nonce                | Smart blended average of min/max/mean + random spread               | Last 100 nonces            | 10                    |
| Potential Winning Nonce  | `Est Nonce + 1337`                                                  | —                          | 10                    |

#### Predict Block function
Uses the same average block time formula as above, then applies the full self-correcting adjuster.

---

### 3. Smart Services, Systems & Data

**Self-correcting prediction model**
- Trend flags (up=2, down=1, neutral=0) for hashrate and price (last block + 50-block average)
- Detection of repeating / looping / triple-bounce trends
- Per-prediction **error-rate tracking** stored in `BBTP.temp`
- Final multiplier based on trend + error rate keeps accuracy in the ~9–33% range

**API flag & pause system**
- Each API has real-time status: 🟢 Green / 🟠 Orange / 🔴 Red / 🔵 Blue / 🟡 Yellow
- Shown with emoji + countdown in the **⚙️ API** settings popup
- Sync automatically pauses when required APIs are unavailable
- Orange APIs are retried on every periodic check

**BBTP.temp persistence**
Stores window size, unfinished work, API flags & cooldowns, prediction adjusters, and non-default L&R settings.

---

### 4. Functions & System Loop

**Main live loop (`live_timer` – every 300 ms)**
1. `update_status()` — refreshes Live Status + BTD + Tip Data
2. `auto_update_predictions()` — refreshes Live Predictions panel
3. `check_cooldown_status()` — shows remaining cooldown time
4. `calculate_trends()` — updates HR/price trend flags

**Periodic tasks**
- Every **9 minutes** → `periodic_new_block_checker`
- Every **60 minutes** → notebook refresh (when cooldown active)
- On shutdown → saves `BBTP.temp` and cleanly stops threads

---

### 5. Intended Use Methods

1. **First run** → click **Full Backward Sync** (takes time; you can stop and resume later)
2. **Daily use** → **Quick Sync Recent**
3. **After any sync** → **Refresh Existing Blocks**
4. **Make predictions** → type a future block number and click **🚀 Predict**
5. **View history** → use any of the four Notebook buttons
6. **Tune data collection** → **⚙️ Data** / **⚙️ API** / **⚙️ L&R** settings
7. **Close safely** → use the window X (confirmation dialog appears)

---

### 6. All Files Used & Associated With

| File                  | Stores what                                      | Smart functions?                              | How it works |
|-----------------------|--------------------------------------------------|-----------------------------------------------|--------------|
| **BBTP.crumbs**       | Main per-block cache (with `__settings__` header) | Auto-merges complete blocks to BTC.chain     | JSON, bulk-saved every 2.5 s |
| **BTC.chain**         | Fully enriched complete blocks                   | Archive for bootstrap & long-term storage    | Sorted JSON list |
| **predicts.block**    | Every manual “Predict Block” result             | Line-delimited JSON, searchable notebook     | Appended on each prediction |
| **LiveP.btc**         | Live prediction snapshots (every new block)     | Top-by-block index, newest first             | Line-delimited JSON |
| **BR.curve**          | Full rate curve (delta_days per height)         | Built on-demand                              | JSON array |
| **BRC.arch**          | Timestamped snapshots of the curve              | Archive for historical analysis              | One JSON object per line |
| **BBTP.temp**         | Window size, unfinished work, API flags, adjusters, L&R toggles | Carried over on restart                      | JSON, deleted when work is finished |
| **data_settings.json**| Which fields to collect (price, hashrate, etc.) | Toggles control what is stored & displayed   | Persisted on close |
| **api_settings.json** | Which APIs are enabled                           | Controls fetcher rotation                    | Persisted on close |
| **BBTP.log**          | Optional detailed logs (when L&R toggle on)     | —                                            | Text file |

---

### 7. Advanced / Internal Details

**Trend detection algorithms**
- Simple last-block direction + 50-block rolling average
- Looping / repeating / triple-bounce pattern detection
- Per-prediction error-rate tracking with self-adjusting multiplier

**API rate limiting & handling**
- Automatic per-API status flags with cooldown timers
- Sync pauses intelligently when APIs are unavailable
- Rotation through multiple public APIs with fallback

**Prediction accuracy bounds**
- Designed to stay within ~9–33% error range through trend adjustment
- Self-correcting model uses stored error rates from previous predictions

**Window icon support**
- Loads `bbtp-icon.png` (64×64 recommended) from the same folder for the task manager / title bar

---

Enjoy predicting the Bitcoin blockchain! 🚀

---

