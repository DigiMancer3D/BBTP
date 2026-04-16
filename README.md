### 0. How to Install

1. Make sure you have **Python 3.8+** installed.
2. Save the complete code **`BBTP.py`** (or `btc_predict_gui.py`).
3. Open a terminal / command prompt in the folder containing the file.
4. Run:  
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install requests
   python3 BBTP.py
   ```
5. On first run the program automatically creates:
   - `BBTP.crumbs` (main cache)
   - `BTC.chain` (complete blocks archive)
   - `predicts.block`, `LiveP.btc`, `BR.curve`, `BRC.arch`, `BBTP.temp`, etc.

 `pip install requests` is required for setup but not always for running.

---

### 1. All Sync Setups

The program uses **non-blocking threaded syncs** with a shared `sync_stop_event`, progress bars, and live logging. It automatically pauses when APIs are unavailable (red/blue flags) and resumes when they recover.

| Sync Type          | What it does                                                                 | When to use it                          | Uses temp file? | Updates live? | Phase 3 behaviour (new)                     |
|--------------------|------------------------------------------------------------------------------|-----------------------------------------|-----------------|---------------|---------------------------------------------|
| **🔥 Quick Sync**  | Catches up recent blocks + 2000-block backward scan                         | Daily / when you are wihtin or under a hundred blocks behind the chain | Yes             | Yes           | Only refreshes blocks *just added* by Quick |
| **🔄 Full Backward** | Fetches from tip all the way to Genesis (block 0)                         | First run or after long absence         | Yes             | Yes           | Only logs missing data (no auto-fetch)      |
| **🔄 Refresh**     | Scans existing cache for incomplete blocks and fixes them                    | After any sync or when you see gaps     | Yes             | Yes           | Full multi-pass refresh (user-controlled)   |

**Key smart behavior:**
- Every sync updates the **Live Fetch Progress** label every **3 blocks**.
- The **Sync Progress bar** shows phase + % and automatically pauses/resumes based on API flags.
- **BBTP.temp** stores unfinished work so you can resume after a restart.

---

### 2. Estimations & Predictions

#### Live Predictions
These update automatically on every new block and use the last ~2016 blocks for rolling averages.

| Field                    | How it is calculated (formula)                                      | Data used                  | Minimum blocks needed |
|--------------------------|---------------------------------------------------------------------|----------------------------|-----------------------|
| Next Diff Adj            | `2016 - (current % 2016)`                                           | Current height             | 1                     |
| Est Hashrate             | `avg_hr × (1 + (target - current) × 0.00008)` then **adjusted**   | Last 2016 blocks           | 3                     |
| Est Price                | `avg_price × (1 + (target - current) × 0.00006)` then **adjusted** | Last 2016 blocks           | 3                     |
| HR/Price                 | `est_hr / est_price`                                                | Adjusted values            | 3                     |
| Est Tx                   | `avg_tx × 1.015`                                                    | Last 2016 blocks           | 3                     |
| Est Nonce                | Smart blended average of min/max/mean + random spread               | Last 100 nonces            | 10                    |
| Potential Winning Nonce  | `Est Nonce + 1337`                                                  | —                          | 10                    |

#### Predict Block function
Uses the **same average block time** formula, then applies the **self-correcting adjuster** (see section 3).

---

### 3. Smart Services, Systems & Data

**Self-correcting prediction model**
- Trend flags (up=2, down=1, neutral=0) for:
  - Hashrate (last block + 50-block average)
  - Price (last block + 50-block average)
  - “Price follows hashrate” / “Hashrate follows price”
- Looping / repeating / triple-bounce trend detection
- Per-prediction **error-rate tracking** stored in `BBTP.temp`
- Final adjuster multiplies the raw estimate by a factor based on trend + error rate (keeps accuracy inside ~9–33% range)

**API flag & pause system**
- Each API has its own real-time status:  
  🟢 Green / 🟠 Orange / 🔴 Red / 🔵 Blue / 🟡 Yellow
- Shown with emoji + cooldown timer in the **⚙️ API** settings popup
- When all required APIs for a data type are red/blue → sync **pauses automatically**
- Orange APIs are retried after every periodic new-block check
- Unique cooldowns: Orange=5 min, Red=77 min, Blue=69 min, Yellow=21 h

**BBTP.temp persistence**
Stores:
- Window size & position
- Unfinished/paused work
- API flags & cooldown timers
- Prediction adjusters & error rates
- Non-default L&R settings

---

### 4. Functions & System Loop

**Main loop (live_timer – every 300 ms)**
1. `update_status()` → refreshes Live Status + BTD + tip data
2. `auto_update_predictions()` → refreshes Live Predictions panel
3. `check_cooldown_status()` → shows remaining cooldown if any
4. `calculate_trends()` → updates HR/price trend flags

**Periodic tasks**
- Every 9 minutes → `periodic_new_block_checker`
- Every 33.1 minutes → full new-block scan
- Every 11.1 minutes (& after a cooldown active) → notebook refresh

**Shutdown**
- Shows confirmation dialog: “A Shutdown has begun… Do you want to proceed?”
- On Yes → saves `BBTP.temp`, stops threads, destroys window cleanly
- No or Cancel → cancels shutdown

---

### 5. Intended Use Methods

1. **First run** → click **Full Backward Sync** (takes time, may need to stop to handle other things then return until finished going to genesis)
2. **Daily** → **Quick Sync Recent**
3. **After any sync** → **Refresh Existing Blocks** (fixes stored data gaps)
4. **Check predictions** → type a future block number and click **🚀 Predict**
5. **View history** → use the four Notebook buttons
6. **Tune what is stored** → **⚙️ Data** / **⚙️ API** / **⚙️ L&R** settings
7. **Close safely** → use the window X (confirmation appears)

---

### 6. All Files Used & Associated With

| File                  | Stores what                                      | Smart functions?                              | How it works |
|-----------------------|--------------------------------------------------|-----------------------------------------------|--------------|
| **BBTP.crumbs**       | Main per-block cache (with `__settings__` header) | Auto-merges to BTC.chain when complete       | JSON, bulk-saved every 2.5 s |
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
- Detects looping / repeating / triple-bounce patterns
- Error-rate accumulator per prediction type
- Final multiplier clamps predictions to realistic 9–33% accuracy band

**API rate-limiting & handling**
- Round-robin across 5 APIs with per-API flags
- Automatic pause/resume when required APIs are unavailable
- Distinct cooldown timers per flag color
- Orange APIs retried aggressively after periodic checks

**Prediction accuracy bounds**
- Base linear extrapolation + trend multiplier + error-rate damper
- Designed to stay within ~9 % (best case) to 33 % (worst case) of actual future values

**Thread safety**
- `RLock` on cache
- `queue.Queue` + `after()` for all GUI updates
- Daemon threads for sync/refresh

**Shutdown / restart resilience**
- Confirmation dialog
- Full state saved to `BBTP.temp`
- Unfinished work popup on next launch

**GUI responsiveness**
- All heavy work runs in background threads
- Progress bars and live labels updated via queued `after()` calls
- No freezing even during full historical sync

---
