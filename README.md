### 1. All Sync Setups – How They Work

The program uses a **smart dynamic system** that only touches data that actually needs updating. It never wastes time or API calls on blocks that are already complete.

| Sync Type                  | What it does                                                                 | When to use it                          | Uses temp file? | Updates live? |
|----------------------------|------------------------------------------------------------------------------|-----------------------------------------|-----------------|---------------|
| **🔥 Quick Sync Recent**   | 1. Catches up any brand-new blocks at the current chain tip<br>2. Then scans your existing blocks and only refreshes the **partial** ones (missing price, hashrate, etc.) | First run or after the chain has grown | Yes (only partial blocks) | Yes (real-time) |
| **🔄 Full Backward Sync**  | Starts from the newest block and walks backwards, but **only adds or refreshes partial blocks**. Never re-fetches complete blocks. | When you want older history | Yes (only partial) | Yes |
| **🔄 Refresh Existing Blocks** | Scans **all** your cached blocks and refreshes **only** the ones that are incomplete (missing fields). | When you think some old blocks are missing price/hashrate | Yes (only partial) | Yes |
| **Periodic checker** (runs automatically every ~33 minutes) | Checks if new blocks appeared on the chain and adds them (rich data + enrichment) | Always running in background | No | Yes |
| **⏹️ Stop Sync**           | Immediately stops any running sync (Quick, Full, or Refresh) | When you want to pause | — | — |

**Key smart behaviour (this is what makes it efficient):**
- Before any refresh, the code checks `_is_complete_block()` → only blocks missing **price_usd**, **estimated_hashrate**, **difficulty**, etc. are moved to `temp_BBTP.crumbs`.
- Complete blocks are **never** touched again → saves API calls and time.
- After every operation the temp file is automatically deleted.

### 2. How All Data Is Determined (Estimations & Predictions)

The program uses **all** the blocks you have stored (minimum 3 blocks required).
It calculates rolling averages from your real data and adds a tiny growth factor for future blocks.

| Field (Live Predictions)          | How it is calculated (formula)                                                                 | Data used                  | Minimum blocks needed |
|-----------------------------------|------------------------------------------------------------------------------------------------|----------------------------|-----------------------|
| **Next Diff Adj**                 | `2016 - (current_height % 2016)`                                                               | Current height only        | 1                     |
| **Est Hashrate**                  | `avg_hashrate × (1 + (target - current) × 0.0001)`                                            | All stored blocks          | 3                     |
| **Est Price**                     | `avg_price × (1 + (target - current) × 0.00005)`                                              | All stored blocks          | 3                     |
| **HR/Price**                      | `estimated_hashrate ÷ estimated_price`                                                         | From above two fields      | 3                     |
| **Est Tx**                        | `avg_tx_count × 1.02`                                                                          | All stored blocks          | 3                     |
| **Est Nonce**                     | Fixed placeholder (real nonce is random per block)                                             | —                          | —                     |
| **Potential Winning Nonce**       | `estimated_nonce + 1337`                                                                       | —                          | —                     |

**Recent Rate** (button):
- Takes the last up-to-2016 blocks you have.
- Formula: `(time_of_last_block – time_of_first_block) ÷ (last_height – first_height)`
- Shows average seconds per block.

**Build Rate Curve** (button):
- For every single block you have stored:
  - Ideal time = `GENESIS_TIMESTAMP + height × 600`
  - Delta = `(actual_time – ideal_time) ÷ 86400` (in days)
- Saves full curve to `btc_block_rate_curve.json` for plotting later.

**Live Predictions** update automatically:
- After every new block fetched
- After every refreshed block
- Every 300 ms via the live timer (so the UI never looks “dead”)

**Live Fetch Progress** shows real session numbers:
- “Last Seen” = most recent block fetched this session
- “Oldest” = lowest block number fetched this session
- “Top” = highest block number fetched this session

**Live Status** updates every 300 ms:
- Cached Blocks = total blocks in BBTP.crumbs
- Network Tip = your highest cached block / real chain tip
- Drift = days ahead/behind the ideal 10-minute schedule

All live sections stay visible even after you click **Stop Sync**.

---

