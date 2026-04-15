import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import requests
import json
import time
from datetime import datetime
import os
from typing import Dict, Optional
import random
from threading import Lock

CACHE_FILE = "BBTP.crumbs"
TEMP_FILE = "temp_BBTP.crumbs"
GENESIS_TIMESTAMP = 1231006505
DIFFICULTY_EPOCH = 2016


class RichBlockFetcher:
    def __init__(self):
        self.apis = [
            {"name": "Mempool.space", "get": self._mempool_get},
            {"name": "Blockstream.info", "get": self._blockstream_get},
            {"name": "Chain.so", "get": self._chainso_get},
        ]
        self.idx = 0
        self.last_api_used = ""

    def _mempool_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Mempool.space"
        try:
            r = requests.get(f"https://mempool.space/api/block-height/{height}", timeout=8)
            r.raise_for_status()
            bh = r.text.strip()
            r = requests.get(f"https://mempool.space/api/block/{bh}", timeout=8)
            r.raise_for_status()
            data = r.json()
            return {
                "time": data.get("timestamp") or data.get("time"),
                "hash": data.get("id"),
                "size": data.get("size"),
                "tx_count": data.get("tx_count"),
                "nonce": data.get("nonce"),
                "bits": data.get("bits"),
                "weight": data.get("weight"),
                "difficulty": data.get("difficulty"),
            }
        except:
            return None

    def _blockstream_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Blockstream.info"
        try:
            r = requests.get(f"https://blockstream.info/api/block-height/{height}", timeout=8)
            r.raise_for_status()
            bh = r.text.strip()
            r = requests.get(f"https://blockstream.info/api/block/{bh}", timeout=8)
            r.raise_for_status()
            data = r.json()
            return {
                "time": data.get("timestamp"),
                "hash": data.get("id"),
                "size": data.get("size"),
                "tx_count": data.get("tx_count"),
                "nonce": data.get("nonce"),
                "bits": data.get("bits"),
                "weight": data.get("weight"),
                "difficulty": data.get("difficulty"),
            }
        except:
            return None

    def _chainso_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Chain.so"
        try:
            r = requests.get(f"https://chain.so/api/v3/block/BTC/{height}", timeout=8)
            r.raise_for_status()
            data = r.json().get("data", {})
            return {
                "time": data.get("time"),
                "hash": data.get("hash"),
                "size": data.get("size"),
                "tx_count": data.get("n_tx"),
                "nonce": data.get("nonce"),
                "bits": data.get("bits"),
                "weight": data.get("weight"),
                "difficulty": data.get("difficulty"),
            }
        except:
            return None

    def get_full_block(self, height: int, cache: Dict[str, dict]) -> Optional[dict]:
        h_str = str(height)
        existing = cache.get(h_str)
        block_data = None
        start = self.idx
        for _ in range(len(self.apis)):
            block_data = self.apis[self.idx]["get"](height)
            self.idx = (self.idx + 1) % len(self.apis)
            if block_data and block_data.get("time") is not None:
                break
            time.sleep(0.42)
        if not block_data:
            return existing
        if existing:
            for k, v in block_data.items():
                if v is not None and (k not in existing or existing[k] is None):
                    existing[k] = v
            cache[h_str] = existing
        else:
            cache[h_str] = block_data
        return cache[h_str]


class DataEnricher:
    @staticmethod
    def get_price_at_timestamp(ts: int) -> Optional[float]:
        try:
            from_ts = ts - 7200
            to_ts = ts + 7200
            url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range?vs_currency=usd&from={from_ts}&to={to_ts}&precision=2"
            r = requests.get(url, timeout=12)
            r.raise_for_status()
            prices = r.json().get("prices", [])
            if not prices:
                return None
            closest = min(prices, key=lambda x: abs(x[0]/1000 - ts))
            return round(closest[1], 2)
        except:
            return None

    @staticmethod
    def estimate_hashrate(difficulty: Optional[float]) -> Optional[float]:
        if not difficulty or difficulty <= 0:
            return None
        hr = difficulty * (2 ** 32) / 600
        return round(hr / 1e18, 4)


class BTCBlockPredictorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🟠 BTC Block Time Predictor – OPTIMIZED DYNAMIC VERSION")
        self.geometry("1420x980")
        self.resizable(True, True)
        self.update_queue = queue.Queue()
        self.cache: Dict[str, dict] = {}
        self.fetcher = RichBlockFetcher()
        self.enricher = DataEnricher()
        self.sync_stop_event = threading.Event()
        self.sync_running = False
        self.last_new_block_check = time.time()
        self.cooldown_active = False
        self.session_fetched = 0
        self.session_oldest = 0
        self.session_top = 0
        self.cache_lock = Lock()
        self.last_price_fetch = 0

        self.last_est_nonce = None
        self.last_win_nonce = None
        self.current_tip_height = 0
        self.current_tip_nonce = None

        self.new_cache_created_on_startup = not os.path.exists(CACHE_FILE)

        self.load_cache()
        self.create_widgets()
        self.update_status()
        self.after(1000, self.periodic_new_block_checker)
        self.after(60000, self.periodic_notebook_refresh)
        self.after(300, self.live_timer)

    def _is_complete_block(self, block: dict) -> bool:
        required = ["time", "hash", "size", "tx_count", "difficulty", "estimated_hashrate", "price_usd"]
        return all(block.get(k) is not None for k in required)

    def load_cache(self):
        with self.cache_lock:
            try:
                if os.path.exists(CACHE_FILE):
                    with open(CACHE_FILE, "r") as f:
                        raw = json.load(f)
                    for h_str, v in list(raw.items()):
                        if not isinstance(v, dict):
                            raw[h_str] = {"time": v} if isinstance(v, (int, float)) else {}
                    self.cache = raw
                else:
                    self.cache = {}
                    with open(CACHE_FILE, "w") as f:
                        json.dump(self.cache, f, indent=2)
            except Exception as e:
                self.cache = {}
                try:
                    with open(CACHE_FILE, "w") as f:
                        json.dump(self.cache, f, indent=2)
                except:
                    pass

    def save_cache(self):
        with self.cache_lock:
            try:
                with open(CACHE_FILE, "w") as f:
                    json.dump(self.cache, f, indent=2)
            except Exception as e:
                print(f"⚠️ Save failed: {e}")
            if os.path.exists(TEMP_FILE):
                try:
                    os.remove(TEMP_FILE)
                except:
                    pass

    def get_full_block(self, height: int) -> Optional[dict]:
        h_str = str(height)
        with self.cache_lock:
            data = self.fetcher.get_full_block(height, self.cache)
        if data:
            self.save_cache()
            self._enrich_block(h_str)
            if height == max((int(h) for h in self.cache.keys()), default=0):
                self._update_sticky_nonce_predictions()
            self.after(10, self.update_status)
            self.after(10, self.auto_update_predictions)
        return data

    def _enrich_block(self, h_str: str):
        with self.cache_lock:
            block = self.cache.get(h_str)
            if not block or not block.get("time"):
                return
            ts = block["time"]
            now = time.time()
            if "price_usd" not in block or block["price_usd"] is None:
                if now - self.last_price_fetch > 45:
                    price = self.enricher.get_price_at_timestamp(ts)
                    self.last_price_fetch = now
                    if price is not None:
                        block["price_usd"] = price
            if "difficulty" in block and block["difficulty"] and ("estimated_hashrate" not in block or block["estimated_hashrate"] is None):
                hr = self.enricher.estimate_hashrate(block["difficulty"])
                if hr is not None:
                    block["estimated_hashrate"] = hr
            self.cache[h_str] = block
        self.save_cache()

    def _update_sticky_nonce_predictions(self):
        if len(self.cache) < 10:
            return
        with self.cache_lock:
            recent_nonces = [b.get("nonce") for b in list(self.cache.values())[-200:]
                             if isinstance(b.get("nonce"), (int, float)) and b.get("nonce") > 1000000]
            if recent_nonces:
                min_n = min(recent_nonces)
                max_n = max(recent_nonces)
                range_size = max(50000000, int((max_n - min_n) * 1.8))
                self.last_est_nonce = random.randint(int(min_n), int(max_n + range_size))
            else:
                self.last_est_nonce = random.randint(2000000000, 4300000000)
            self.last_win_nonce = self.last_est_nonce + 1337 if self.last_est_nonce is not None else 1337

    def refresh_cached_blocks(self):
        if self.sync_running:
            messagebox.showinfo("Busy", "Wait for current operation")
            return
        self.sync_running = True
        self.btn_refresh.config(state="disabled")
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        try:
            self.queue_update("🔄 Scanning for partial blocks only...")
            with self.cache_lock:
                partial = {h: b for h, b in self.cache.items() if not self._is_complete_block(b)}
            if not partial:
                self.queue_update("✅ All blocks complete")
                return
            self.queue_update(f"🔄 Found {len(partial):,} partial blocks")
            with open(TEMP_FILE, "w") as f:
                json.dump(partial, f, indent=2)
            with self.cache_lock:
                for h in partial:
                    self.cache.pop(h, None)
            self.save_cache()
            refreshed = 0
            for h_str in list(partial.keys()):
                if self.sync_stop_event.is_set():
                    break
                self.get_full_block(int(h_str))
                refreshed += 1
                if refreshed % 30 == 0:
                    self.queue_update(f" Refreshed {refreshed:,}/{len(partial):,} partial blocks")
                time.sleep(0.65)
            self.queue_update(f"✅ Dynamic refresh complete")
        except Exception as e:
            self.queue_update(f"❌ Refresh error: {e}")
        finally:
            self.sync_running = False
            self.btn_refresh.config(state="normal")
            self.after(200, self.update_status)

    def _start_sync(self, mode: str = "quick"):
        if self.sync_running:
            messagebox.showinfo("Busy", "Sync already running")
            return

        # Extra confirmation for full historical sync (all blocks)
        if mode == "full":
            if not messagebox.askyesno("⚠️ FULL HISTORICAL SYNC",
                                       "Full Backward Sync will now fetch EVERY block from the current tip ALL the way back to Genesis (block 0).\n\n"
                                       "This will take a VERY long time (hours or more) and will use a lot of API calls.\n\n"
                                       "Are you sure you want to continue?"):
                return

        self.sync_running = True
        self.sync_stop_event.clear()
        self.btn_stop.config(state="normal")
        self.btn_quick.config(state="disabled")
        self.btn_backward.config(state="disabled")
        self.session_fetched = 0
        self.session_oldest = 0
        self.session_top = 0
        threading.Thread(target=self.sync_thread, args=(mode,), daemon=True).start()

    def sync_thread(self, mode: str):
        try:
            self.queue_update(f"🚀 Starting {mode.upper()} sync...")
            tip = self.get_current_height()
            if tip == 0:
                self.queue_update("❌ Cannot reach network tip")
                return

            with self.cache_lock:
                cached_max = max((int(h) for h in self.cache.keys()), default=0)

            gap = tip - cached_max
            self.session_oldest = tip
            self.session_top = tip

            # PHASE 1: Always catch up any newer blocks first
            if gap > 0:
                self.queue_update(f"🔼 Catching up {gap:,} new blocks...")
                for h in range(tip, cached_max, -1):
                    if self.sync_stop_event.is_set():
                        break
                    if str(h) not in self.cache or not self._is_complete_block(self.cache.get(str(h), {})):
                        self.get_full_block(h)
                    self.session_fetched += 1
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                    self.after(10, self.update_status)
                    time.sleep(0.35)

            # PHASE 2: Full historical backfill (ALL blocks from tip down to genesis)
            if mode == "full":
                self.queue_update(f"🔄 FULL HISTORICAL BACKWARD SYNC: Fetching ALL blocks from {tip:,} down to Genesis (0)...")
                for h in range(tip, -1, -1):   # ← THIS IS THE CHANGE: now goes all the way to 0
                    if self.sync_stop_event.is_set():
                        break
                    if str(h) not in self.cache or not self._is_complete_block(self.cache.get(str(h), {})):
                        self.get_full_block(h)
                    self.session_fetched += 1
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    if self.session_fetched % 30 == 0:
                        self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                        self.after(10, self.update_status)
                    time.sleep(0.50)   # Slightly slower to respect free API limits

            elif mode == "quick":
                lower = max(cached_max, tip - 2000)
                self.queue_update(f"🔼 Quick backward sync from {tip:,} down to {lower:,} (recent blocks first)")
                for h in range(tip, lower - 1, -1):
                    if self.sync_stop_event.is_set():
                        break
                    if str(h) not in self.cache or not self._is_complete_block(self.cache.get(str(h), {})):
                        self.get_full_block(h)
                    self.session_fetched += 1
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                    self.after(10, self.update_status)
                    time.sleep(0.42)

            # PHASE 3: Partial block refresh
            self.queue_update("🔄 Phase 3: Checking partial blocks only...")
            with self.cache_lock:
                partial = {h: b for h, b in self.cache.items() if not self._is_complete_block(b)}
            if partial:
                self.queue_update(f" Found {len(partial):,} partial blocks")
                with open(TEMP_FILE, "w") as f:
                    json.dump(partial, f, indent=2)
                with self.cache_lock:
                    for h in partial:
                        self.cache.pop(h, None)
                self.save_cache()
                for h_str in list(partial.keys()):
                    if self.sync_stop_event.is_set():
                        break
                    self.get_full_block(int(h_str))
                    self.after(10, self.update_status)
                    time.sleep(0.65)
            else:
                self.queue_update("✅ All blocks already complete")

            self.queue_update(f"✅ {mode.upper()} dynamic sync finished")
        except Exception as e:
            self.queue_update(f"❌ Sync error: {e}")
        finally:
            self.sync_running = False
            self.btn_stop.config(state="disabled")
            self.btn_quick.config(state="normal")
            self.btn_backward.config(state="normal")
            self.after(200, self.update_status)

    def stop_sync(self):
        self.sync_stop_event.set()
        self.queue_update("⏹️ Stop signal sent...")
        self.btn_stop.config(state="disabled")
        self.after(100, self.auto_update_predictions)

    def live_timer(self):
        self.update_status()
        self.auto_update_predictions()
        self.after(300, self.live_timer)

    def auto_update_predictions(self):
        if hasattr(self, "predict_entry") and self.predict_entry.get().strip():
            try:
                target = int(self.predict_entry.get().strip())
                self.update_prediction_labels(target)
            except:
                pass

    def update_prediction_labels(self, target: int):
        if len(self.cache) < 3:
            return
        with self.cache_lock:
            current = max(int(h) for h in self.cache.keys())
        if target <= current:
            return
        with self.cache_lock:
            all_heights = sorted(int(h) for h in self.cache.keys())
            use = all_heights[-2016:] if len(all_heights) > 2016 else all_heights
            t_start = self.cache[str(use[0])]["time"]
            t_end = self.cache[str(use[-1])]["time"]
            avg_sec = (t_end - t_start) / (use[-1] - use[0]) if len(use) > 1 else 600
            recent_blocks = [b for b in self.cache.values() if "difficulty" in b]
            avg_hr = sum(b.get("estimated_hashrate", 0) for b in recent_blocks) / len(recent_blocks) if recent_blocks else 600
            avg_price = sum(b.get("price_usd", 0) for b in recent_blocks if "price_usd" in b) / len(recent_blocks) if recent_blocks else 70000
            avg_tx = sum(b.get("tx_count", 0) for b in recent_blocks) / len(recent_blocks) if recent_blocks else 3000
            blocks_until_adjustment = DIFFICULTY_EPOCH - (current % DIFFICULTY_EPOCH)
            est_hr = round(avg_hr * (1 + (target - current) * 0.00008), 4)
            est_price = round(avg_price * (1 + (target - current) * 0.00006), 2)
            est_tx = int(avg_tx * 1.015)

        nonce_text = f"{self.last_est_nonce}" if self.last_est_nonce is not None else "—"
        win_text = f"{self.last_win_nonce}" if self.last_win_nonce is not None else "—"

        self.lbl_diff.config(text=f"Next Diff Adj: {blocks_until_adjustment}")
        self.lbl_hr.config(text=f"Est Hashrate: {est_hr} EH/s")
        self.lbl_price.config(text=f"Est Price: ${est_price:,.2f}")
        self.lbl_ratio.config(text=f"HR/Price: {est_hr/est_price:.6f}")
        self.lbl_tx.config(text=f"Est Tx: {est_tx:,}")
        self.lbl_nonce.config(text=f"Est Nonce: {nonce_text}")
        self.lbl_win_nonce.config(text=f"Potential Winning Nonce: {win_text}")

    def open_maths_window(self):
        if hasattr(self, "maths_win") and self.maths_win.winfo_exists():
            self.maths_win.lift()
            return
        self.maths_win = tk.Toplevel(self)
        self.maths_win.title("📐 Maths Behind Predictions")
        self.maths_win.geometry("940x760")
        txt = scrolledtext.ScrolledText(self.maths_win, font=("Consolas", 11), wrap=tk.WORD, bg="#f8f8f8")
        txt.pack(fill="both", expand=True, padx=15, pady=15)
        explanation = """# 📐 BTC Block Time Predictor – Maths Explained

**Live Prediction System** uses all stored blocks (min 3 required).

### 1. Average Block Time
```python
avg_sec = (last_timestamp - first_timestamp) / (last_height - first_height)
```

### 2. Estimated Timestamp for Target Block
```python
est_ts = last_ts + (target - current) * avg_sec
```

### 3. Next Difficulty Adjustment
Bitcoin adjusts every **2016** blocks.
```python
blocks_until_adj = 2016 - (current_height % 2016)
```

### 4. Estimated Hashrate / Price / Tx Count
Rolling average of recent blocks + small linear growth:
- HR: `avg_hr * (1 + (target - current) * 0.00008)`
- Price: `avg_price * (1 + (target - current) * 0.00006)`
- Tx: `avg_tx * 1.015`

### 5. Smart Nonce Estimation
Uses **real recent nonce trend** + randomness within observed range.
Nonce values **only update when a new block is discovered** (they stick otherwise).

All values update **live** after every new or refreshed block.
"""
        txt.insert(tk.END, explanation)
        txt.config(state="disabled")

    def open_notebook(self):
        if hasattr(self, "notebook_win") and self.notebook_win.winfo_exists():
            self.notebook_win.lift()
            return
        self.notebook_win = tk.Toplevel(self)
        self.notebook_win.title("📖 BTC Notebook – BBTP.crumbs")
        self.notebook_win.geometry("1200x780")
        top = ttk.Frame(self.notebook_win)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search_var, width=35)
        search_entry.pack(side="left", padx=5)
        search_entry.bind("<KeyRelease>", lambda e: self.refresh_notebook_view())
        ttk.Label(top, text="Height filter:").pack(side="left", padx=(30,5))
        self.filter_min = ttk.Entry(top, width=12)
        self.filter_min.pack(side="left")
        ttk.Label(top, text="–").pack(side="left")
        self.filter_max = ttk.Entry(top, width=12)
        self.filter_max.pack(side="left", padx=5)
        ttk.Button(top, text="Apply", command=self.refresh_notebook_view).pack(side="left", padx=5)
        ttk.Button(top, text="Clear", command=self.clear_notebook_filters).pack(side="left")
        cols = ("Height", "Time", "Hash", "Size", "Tx", "Nonce", "Difficulty", "Hashrate (EH/s)", "Price USD")
        self.tree = ttk.Treeview(self.notebook_win, columns=cols, show="headings", height=28)
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=130, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=5)
        nav = ttk.Frame(self.notebook_win)
        nav.pack(fill="x", padx=10, pady=8)
        self.page_label = ttk.Label(nav, text="Page 1 / ?")
        self.page_label.pack(side="left")
        ttk.Button(nav, text="◀ Prev", command=self.prev_page).pack(side="left", padx=5)
        ttk.Button(nav, text="Next ▶", command=self.next_page).pack(side="left")
        self.page_size = 50
        self.current_page = 0
        self.refresh_notebook_view()

    def refresh_notebook_view(self):
        if not hasattr(self, "tree"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
        except:
            return
        heights = sorted(int(h) for h in data.keys())
        try:
            fmin = int(self.filter_min.get() or 0)
            fmax = int(self.filter_max.get() or 999999999)
            heights = [h for h in heights if fmin <= h <= fmax]
        except:
            pass
        term = self.search_var.get().strip().lower()
        if term:
            heights = [h for h in heights if term in str(h) or term in str(data[str(h)].get("hash", "")).lower()]
        total_pages = (len(heights) + self.page_size - 1) // self.page_size
        start = self.current_page * self.page_size
        page_heights = heights[start:start + self.page_size]
        for h in page_heights:
            b = data[str(h)]
            self.tree.insert("", "end", values=(
                h,
                datetime.fromtimestamp(b.get("time", 0)).strftime("%Y-%m-%d %H:%M"),
                (b.get("hash", "")[:16] + "...") if b.get("hash") else "",
                b.get("size", ""),
                b.get("tx_count", ""),
                b.get("nonce", ""),
                f"{b.get('difficulty', 0):.2f}" if b.get("difficulty") else "",
                f"{b.get('estimated_hashrate', 0):.4f}" if b.get("estimated_hashrate") else "",
                f"${b.get('price_usd', 0):,.2f}" if b.get("price_usd") else ""
            ))
        self.page_label.config(text=f"Page {self.current_page + 1} / {max(1, total_pages)}")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_notebook_view()

    def next_page(self):
        self.current_page += 1
        self.refresh_notebook_view()

    def clear_notebook_filters(self):
        self.filter_min.delete(0, tk.END)
        self.filter_max.delete(0, tk.END)
        self.search_var.set("")
        self.current_page = 0
        self.refresh_notebook_view()

    def queue_update(self, message: str):
        self.update_queue.put(("log", message))
        if hasattr(self, "log_area"):
            self.after(10, self.process_queue)
        else:
            print(message)

    def queue_progress(self, count: int, current: int, oldest: int, top: int):
        api = self.fetcher.last_api_used or "API"
        txt = f"{api} → Block(s) {count} fetched: Last Seen {current:,} | Oldest {oldest:,} | Top {top:,}"
        self.update_queue.put(("progress", txt))
        if hasattr(self, "live_progress"):
            self.after(10, self.process_queue)

    def process_queue(self):
        while not self.update_queue.empty():
            item = self.update_queue.get()
            if item[0] == "log":
                self.log_area.insert(tk.END, item[1] + "\n")
                self.log_area.see(tk.END)
            elif item[0] == "progress":
                self.live_progress.config(text=item[1])

    def get_current_height(self) -> int:
        for url in ["https://mempool.space/api/blocks/tip/height", "https://blockstream.info/api/blocks/tip/height"]:
            try:
                r = requests.get(url, timeout=8)
                return int(r.text.strip())
            except:
                continue
        return 0

    def build_curve_thread(self):
        if len(self.cache) < 3:
            messagebox.showwarning("Too few blocks", "Need at least 3 blocks!")
            return
        self.queue_update("📈 Building full rate curve...")
        with self.cache_lock:
            curve_data = []
            for h_str, block in sorted(self.cache.items(), key=lambda x: int(x[0])):
                h = int(h_str)
                actual = block["time"]
                ideal = GENESIS_TIMESTAMP + h * 600
                delta_days = (actual - ideal) / 86400.0
                curve_data.append({"height": h, "delta_days": round(delta_days, 4)})
        with open("btc_block_rate_curve.json", "w") as f:
            json.dump(curve_data, f, indent=2)
        self.queue_update(f"✅ Curve saved! Total drift: {curve_data[-1]['delta_days']:+.2f} days")

    def predict_block(self):
        if len(self.cache) >= 3:
            self.show_recent_rate()
            threading.Thread(target=self.build_curve_thread, daemon=True).start()
        if len(self.cache) < 3:
            messagebox.showwarning("Too few blocks", "Need at least 3 blocks!")
            return
        try:
            target = int(self.predict_entry.get().strip())
        except:
            messagebox.showerror("Error", "Valid block number")
            return
        with self.cache_lock:
            current = max(int(h) for h in self.cache.keys())
        if target <= current:
            with self.cache_lock:
                block = self.cache[str(target)]
            dt = datetime.fromtimestamp(block["time"])
            self.log_area.insert(tk.END, f"✅ Block {target:,} mined: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            self.log_area.see(tk.END)
            return
        with self.cache_lock:
            all_heights = sorted(int(h) for h in self.cache.keys())
            use = all_heights[-2016:] if len(all_heights) > 2016 else all_heights
            t_start = self.cache[str(use[0])]["time"]
            t_end = self.cache[str(use[-1])]["time"]
            avg_sec = (t_end - t_start) / (use[-1] - use[0]) if len(use) > 1 else 600
            last_ts = self.cache[str(current)]["time"]
        est_ts = last_ts + int((target - current) * avg_sec)
        delta_days = (est_ts - (GENESIS_TIMESTAMP + target * 600)) / 86400.0
        est_dt = datetime.fromtimestamp(est_ts)
        self.log_area.insert(tk.END, f"🚀 Prediction {target:,} → {est_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (Δ {delta_days:+.2f} days)\n")
        self.log_area.see(tk.END)

    def show_recent_rate(self):
        if len(self.cache) < 3:
            messagebox.showwarning("Too few blocks", "Need at least 3 blocks!")
            return
        with self.cache_lock:
            all_heights = sorted(int(h) for h in self.cache.keys())
            use = all_heights[-2016:] if len(all_heights) > 2016 else all_heights
            t_start = self.cache[str(use[0])]["time"]
            t_end = self.cache[str(use[-1])]["time"]
            avg = (t_end - t_start) / (use[-1] - use[0]) if len(use) > 1 else 600
        messagebox.showinfo("Recent Rate", f"Recent average: {avg:.2f} sec/block (using {len(use):,} blocks)")

    def update_status(self):
        n = len(self.cache)
        tip = self.get_current_height()
        if n > 0:
            with self.cache_lock:
                heights = [int(h) for h in self.cache.keys()]
                min_h = min(heights)
                max_h = max(heights)
                block = self.cache[str(max_h)]
                ideal = GENESIS_TIMESTAMP + max_h * 600
                delta = (block["time"] - ideal) / 86400.0

                self.current_tip_height = max_h
                self.current_tip_nonce = block.get("nonce")

                hash_str = str(block.get("hash", ""))
                stripped = hash_str.lstrip("0")
                leading_zeros = len(hash_str) - len(stripped) if hash_str else 0
                display_hash = stripped[:16] + "..." if len(stripped) > 16 else stripped or "—"

                epoch = (max_h // DIFFICULTY_EPOCH) + 1

            self.status_cached.config(text=f"Cached Blocks: {n:,}")
            self.status_range.config(text=f"Cached: {min_h:,} – {max_h:,}")
            self.status_network.config(text=f"Network Tip: {max_h:,} / {tip:,}")
            self.status_drift.config(text=f"Drift: {delta:+.2f} days")

            self.tip_block_num.config(text=f"Block Number: {max_h:,}")
            self.tip_epoch.config(text=f"Epoch: {epoch}")
            self.tip_hash.config(text=f"Hash: {display_hash}")
            self.tip_leading_zeros.config(text=f"Leading 0s: {leading_zeros}")
            self.tip_price.config(text=f"Price: ${block.get('price_usd', 0):,.2f}")
            self.tip_hr.config(text=f"HR: {block.get('estimated_hashrate', 0):.4f} EH/s")

        else:
            self.status_cached.config(text="Cached Blocks: 0")
            self.status_range.config(text="Cached: — – —")
            self.status_network.config(text=f"Network Tip: 0 / {tip:,}")
            self.status_drift.config(text="Drift: —")

    def show_tip_nonce(self):
        if self.current_tip_nonce is None:
            messagebox.showinfo("Tip Nonce", "No nonce data yet for current tip.")
            return
        messagebox.showinfo("🔑 Tip Block Nonce",
                            f"Block {self.current_tip_height:,}\n\n"
                            f"Nonce: {self.current_tip_nonce:,}\n\n"
                            f"(Full integer value from the blockchain)")

    def periodic_new_block_checker(self):
        if time.time() - self.last_new_block_check >= 33.1 * 60:
            self.last_new_block_check = time.time()
            threading.Thread(target=self.check_and_fetch_new_blocks, daemon=True).start()
        self.after(60000, self.periodic_new_block_checker)

    def check_and_fetch_new_blocks(self):
        with self.cache_lock:
            cached_max = max((int(h) for h in self.cache.keys()), default=0)
        tip = self.get_current_height()
        if tip > cached_max + 5:
            self.queue_update(f"🕒 Periodic: {tip - cached_max} new blocks – enriching...")
            for h in range(cached_max + 1, tip + 1):
                self.get_full_block(h)
            self.queue_update("✅ New blocks added")

    def periodic_notebook_refresh(self):
        if not self.cooldown_active:
            self.after(60000, self.periodic_notebook_refresh)
            return
        time.sleep(60)
        self.after(60000, self.periodic_notebook_refresh)

    def create_widgets(self):
        ttk.Label(self, text="🟠 BTC Block Time Predictor – OPTIMIZED DYNAMIC VERSION", font=("Helvetica", 18, "bold")).pack(pady=10)

        sf = ttk.LabelFrame(self, text="Live Status", padding=10)
        sf.pack(fill="x", padx=15, pady=5)
        self.status_cached = ttk.Label(sf, text="Cached Blocks: 0", anchor="center")
        self.status_cached.grid(row=0, column=0, sticky="ew", padx=10)
        self.status_range = ttk.Label(sf, text="Cached: — – —", anchor="center", foreground="#0066cc")
        self.status_range.grid(row=0, column=1, sticky="ew", padx=10)
        self.status_network = ttk.Label(sf, text="Network Tip: — / —", anchor="center")
        self.status_network.grid(row=1, column=0, sticky="ew", padx=10)
        self.status_drift = ttk.Label(sf, text="Drift: —", anchor="center")
        self.status_drift.grid(row=1, column=1, sticky="ew", padx=10)
        sf.columnconfigure(0, weight=1)
        sf.columnconfigure(1, weight=1)

        pf = ttk.LabelFrame(self, text="Live Fetch Progress", padding=8)
        pf.pack(fill="x", padx=15, pady=4)
        self.live_progress = ttk.Label(pf, text="→ Ready", foreground="#0066cc", font=("Consolas", 11), anchor="center")
        self.live_progress.pack(fill="x")

        cf = ttk.LabelFrame(self, text="Actions", padding=12)
        cf.pack(fill="x", padx=15, pady=8)
        self.btn_quick = ttk.Button(cf, text="🔥 Quick Sync Recent", command=lambda: self._start_sync("quick"))
        self.btn_quick.grid(row=0, column=0, padx=6, pady=4, sticky="ew")
        self.btn_backward = ttk.Button(cf, text="🔄 Full Backward Sync", command=lambda: self._start_sync("full"))
        self.btn_backward.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        self.btn_refresh = ttk.Button(cf, text="🔄 Refresh Existing Blocks", command=self.refresh_cached_blocks)
        self.btn_refresh.grid(row=0, column=2, padx=6, pady=4, sticky="ew")
        self.btn_stop = ttk.Button(cf, text="⏹️ Stop Sync", command=self.stop_sync, state="disabled")
        self.btn_stop.grid(row=0, column=3, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📈 Build Rate Curve", command=lambda: threading.Thread(target=self.build_curve_thread, daemon=True).start()).grid(row=1, column=0, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📊 Recent Rate", command=self.show_recent_rate).grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📖 BTC Notebook", command=self.open_notebook).grid(row=1, column=2, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📐 Maths", command=self.open_maths_window).grid(row=1, column=3, padx=6, pady=4, sticky="ew")
        for i in range(4):
            cf.columnconfigure(i, weight=1)

        pred_live_frame = ttk.LabelFrame(self, text="Live Predictions", padding=12)
        pred_live_frame.pack(fill="x", padx=15, pady=8)
        self.lbl_diff = ttk.Label(pred_live_frame, text="Next Diff Adj: —", anchor="w")
        self.lbl_diff.grid(row=0, column=0, padx=12, pady=4, sticky="w")
        self.lbl_hr = ttk.Label(pred_live_frame, text="Est Hashrate: —", anchor="w")
        self.lbl_hr.grid(row=0, column=1, padx=12, pady=4, sticky="w")
        self.lbl_price = ttk.Label(pred_live_frame, text="Est Price: —", anchor="w")
        self.lbl_price.grid(row=0, column=2, padx=12, pady=4, sticky="w")
        self.lbl_ratio = ttk.Label(pred_live_frame, text="HR/Price: —", anchor="w")
        self.lbl_ratio.grid(row=0, column=3, padx=12, pady=4, sticky="w")
        self.lbl_tx = ttk.Label(pred_live_frame, text="Est Tx: —", anchor="w")
        self.lbl_tx.grid(row=1, column=0, padx=12, pady=4, sticky="w")
        self.lbl_nonce = ttk.Label(pred_live_frame, text="Est Nonce: —", anchor="w")
        self.lbl_nonce.grid(row=1, column=1, padx=12, pady=4, sticky="w")
        self.lbl_win_nonce = ttk.Label(pred_live_frame, text="Potential Winning Nonce: —", anchor="w")
        self.lbl_win_nonce.grid(row=1, column=2, padx=12, pady=4, sticky="w", columnspan=2)
        for i in range(4):
            pred_live_frame.columnconfigure(i, weight=1)

        tip_frame = ttk.LabelFrame(self, text="Tip Data", padding=12)
        tip_frame.pack(fill="x", padx=15, pady=8)
        self.tip_block_num = ttk.Label(tip_frame, text="Block Number: —", anchor="w")
        self.tip_block_num.grid(row=0, column=0, padx=12, pady=4, sticky="w")
        self.tip_epoch = ttk.Label(tip_frame, text="Epoch: —", anchor="w")
        self.tip_epoch.grid(row=0, column=1, padx=12, pady=4, sticky="w")
        self.tip_hash = ttk.Label(tip_frame, text="Hash: —", anchor="w")
        self.tip_hash.grid(row=0, column=2, padx=12, pady=4, sticky="w")
        self.tip_leading_zeros = ttk.Label(tip_frame, text="Leading 0s: —", anchor="w")
        self.tip_leading_zeros.grid(row=0, column=3, padx=12, pady=4, sticky="w")
        self.tip_price = ttk.Label(tip_frame, text="Price: —", anchor="w")
        self.tip_price.grid(row=1, column=0, padx=12, pady=4, sticky="w")
        self.tip_hr = ttk.Label(tip_frame, text="HR: —", anchor="w")
        self.tip_hr.grid(row=1, column=1, padx=12, pady=4, sticky="w")
        ttk.Button(tip_frame, text="🔑 Reveal Nonce", command=self.show_tip_nonce).grid(row=1, column=2, padx=12, pady=4, sticky="w")
        tip_frame.columnconfigure(0, weight=1)
        tip_frame.columnconfigure(1, weight=1)
        tip_frame.columnconfigure(2, weight=1)
        tip_frame.columnconfigure(3, weight=1)

        pred_input_frame = ttk.LabelFrame(self, text="Predict Block", padding=10)
        pred_input_frame.pack(fill="x", padx=15, pady=8)
        ttk.Label(pred_input_frame, text="Predict block:").pack(side="left")
        self.predict_entry = ttk.Entry(pred_input_frame, width=14)
        self.predict_entry.pack(side="left", padx=6)
        self.predict_entry.insert(0, "1000000")
        ttk.Button(pred_input_frame, text="🚀 Predict", command=self.predict_block).pack(side="left", padx=6)

        lf = ttk.LabelFrame(self, text="Log & Results", padding=8)
        lf.pack(fill="both", expand=True, padx=15, pady=8)
        self.log_area = scrolledtext.ScrolledText(lf, height=14, font=("Consolas", 10))
        self.log_area.pack(fill="both", expand=True)

        welcome = "👋 OPTIMIZED DYNAMIC VERSION LOADED!\n"
        if self.new_cache_created_on_startup:
            welcome += f"🆕 Created new persistent file: {CACHE_FILE}\n"
        welcome += "• Quick Sync newest-first (backward)\n"
        welcome += "• Full Backward Sync now fetches ALL blocks from tip → Genesis (0)\n"
        welcome += "• Cache keyed by real block height\n"
        welcome += "• Live Status now shows Cached range\n"
        welcome += "• New Tip Data section with nonce reveal\n"
        welcome += "• Sticky nonce predictions (update on new blocks only)\n"
        welcome += "• MATHS WINDOW now GitHub-style pretty\n\n"
        self.log_area.insert(tk.END, welcome)

        ttk.Label(self, text=f"Persistent file: {CACHE_FILE} | Temp file: {TEMP_FILE} (auto-cleaned)", font=("Helvetica", 9), foreground="gray").pack(pady=5)


if __name__ == "__main__":
    app = BTCBlockPredictorGUI()
    app.mainloop()
