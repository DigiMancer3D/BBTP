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
                "nonce": None,
                "bits": None,
                "weight": None,
                "difficulty": None,
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

        self.load_cache()
        self.create_widgets()
        self.update_status()
        self.after(1000, self.periodic_new_block_checker)
        self.after(60000, self.periodic_notebook_refresh)
        self.after(300, self.live_timer)   # very fast live refresh

    def _is_complete_block(self, block: dict) -> bool:
        required = ["time", "hash", "size", "tx_count", "difficulty", "estimated_hashrate", "price_usd"]
        return all(block.get(k) is not None for k in required)

    def load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    raw = json.load(f)
                for h_str, v in list(raw.items()):
                    if isinstance(v, int):
                        raw[h_str] = {"time": v}
                self.cache = raw
                complete = sum(1 for b in self.cache.values() if self._is_complete_block(b))
                self.queue_update(f"✅ Loaded {len(self.cache):,} blocks ({complete} complete)")
            except Exception as e:
                self.queue_update(f"⚠️ Error reading {CACHE_FILE}: {e}")
                self.cache = {}
        else:
            self.cache = {}
            self.save_cache()
            self.queue_update(f"🆕 Created new file: {CACHE_FILE}")

    def save_cache(self):
        with open(CACHE_FILE, "w") as f:
            json.dump(self.cache, f, indent=2)
        if os.path.exists(TEMP_FILE):
            try:
                os.remove(TEMP_FILE)
            except:
                pass

    def get_full_block(self, height: int) -> Optional[dict]:
        data = self.fetcher.get_full_block(height, self.cache)
        if data:
            self.save_cache()
            self._enrich_block(str(height))
            self.after(10, self.update_status)
            self.after(10, self.auto_update_predictions)
        return data

    def _enrich_block(self, h_str: str):
        block = self.cache.get(h_str)
        if not block or not block.get("time"):
            return
        ts = block["time"]
        if "price_usd" not in block or block["price_usd"] is None:
            price = self.enricher.get_price_at_timestamp(ts)
            if price is not None:
                block["price_usd"] = price
        if "difficulty" in block and block["difficulty"] and ("estimated_hashrate" not in block or block["estimated_hashrate"] is None):
            hr = self.enricher.estimate_hashrate(block["difficulty"])
            if hr is not None:
                block["estimated_hashrate"] = hr
        self.cache[h_str] = block
        self.save_cache()

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
            partial = {h: b for h, b in self.cache.items() if not self._is_complete_block(b)}
            if not partial:
                self.queue_update("✅ All blocks complete")
                return
            self.queue_update(f"🔄 Found {len(partial):,} partial blocks")
            with open(TEMP_FILE, "w") as f:
                json.dump(partial, f, indent=2)
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
                    self.queue_update(f"   Refreshed {refreshed:,}/{len(partial):,} partial blocks")
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
            cached_max = max((int(h) for h in self.cache.keys()), default=0)
            gap = tip - cached_max

            if gap > 0:
                self.queue_update(f"🔼 Phase 1: Catching up {gap:,} new blocks...")
                self.session_oldest = tip
                self.session_top = tip
                for h in range(cached_max + 1, tip + 1):
                    if self.sync_stop_event.is_set():
                        break
                    if str(h) not in self.cache:
                        self.get_full_block(h)
                    self.session_fetched += 1
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                    self.after(10, self.update_status)
                    time.sleep(0.35)

            self.queue_update("🔄 Phase 2: Checking partial blocks only...")
            partial = {h: b for h, b in self.cache.items() if not self._is_complete_block(b)}
            if partial:
                self.queue_update(f"   Found {len(partial):,} partial blocks")
                with open(TEMP_FILE, "w") as f:
                    json.dump(partial, f, indent=2)
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
                self.queue_update("   All blocks already complete")

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
        self.after(100, self.auto_update_predictions)   # keep predictions alive

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
        current = max(int(h) for h in self.cache.keys())
        if target <= current:
            return
        all_heights = sorted(int(h) for h in self.cache.keys())
        use = all_heights[-2016:] if len(all_heights) > 2016 else all_heights
        t_start = self.cache[str(use[0])]["time"]
        t_end = self.cache[str(use[-1])]["time"]
        avg_sec = (t_end - t_start) / (use[-1] - use[0]) if len(use) > 1 else 600

        avg_diff = sum(b.get("difficulty", 0) for b in self.cache.values() if "difficulty" in b) / len(self.cache) if self.cache else 1
        avg_hr = sum(b.get("estimated_hashrate", 0) for b in self.cache.values() if "estimated_hashrate" in b) / len(self.cache) if self.cache else 600
        avg_price = sum(b.get("price_usd", 0) for b in self.cache.values() if "price_usd" in b) / len(self.cache) if self.cache else 70000
        avg_tx = sum(b.get("tx_count", 0) for b in self.cache.values() if "tx_count" in b) / len(self.cache) if self.cache else 3000

        blocks_until_adjustment = DIFFICULTY_EPOCH - (current % DIFFICULTY_EPOCH)
        est_hr = round(avg_hr * (1 + (target - current) * 0.0001), 4)
        est_price = round(avg_price * (1 + (target - current) * 0.00005), 2)
        est_tx = int(avg_tx * 1.02)
        est_nonce = 1234567890
        potential_winning_nonce = est_nonce + 1337

        self.lbl_diff.config(text=f"Next Diff Adj: {blocks_until_adjustment}")
        self.lbl_hr.config(text=f"Est Hashrate: {est_hr} EH/s")
        self.lbl_price.config(text=f"Est Price: ${est_price:,.2f}")
        self.lbl_ratio.config(text=f"HR/Price: {est_hr/est_price:.6f}")
        self.lbl_tx.config(text=f"Est Tx: {est_tx:,}")
        self.lbl_nonce.config(text=f"Est Nonce: {est_nonce}")
        self.lbl_win_nonce.config(text=f"Potential Winning Nonce: {potential_winning_nonce}")

    def open_maths_window(self):
        if hasattr(self, "maths_win") and self.maths_win.winfo_exists():
            self.maths_win.lift()
            return
        self.maths_win = tk.Toplevel(self)
        self.maths_win.title("📐 Maths Behind Predictions")
        self.maths_win.geometry("940x760")
        txt = scrolledtext.ScrolledText(self.maths_win, font=("Consolas", 11), wrap=tk.WORD)
        txt.pack(fill="both", expand=True, padx=15, pady=15)
        explanation = """📐 HOW THE LIVE PREDICTION SYSTEM WORKS

Uses ALL stored blocks (minimum 3).

1. Average block time:
   avg_sec = (last_timestamp - first_timestamp) / (last_height - first_height)

2. Estimated timestamp for target block:
   est_ts = last_ts + (target - current) * avg_sec

3. Next Difficulty Adjustment:
   Bitcoin adjusts every 2016 blocks.
   Blocks until next adjustment = 2016 - (current_height % 2016)

4. Estimated Hashrate / Price / Tx Count:
   Rolling average of all stored blocks + small linear growth factor.

All values update automatically after every new or refreshed block.
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
        self.after(10, self.process_queue)

    def queue_progress(self, count: int, current: int, oldest: int, top: int):
        api = self.fetcher.last_api_used or "API"
        txt = f"{api} → Block(s) {count} fetched: Last Seen {current:,} | Oldest {oldest:,} | Top {top:,}"
        self.update_queue.put(("progress", txt))
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
        if len(self.cache) < 3:
            messagebox.showwarning("Too few blocks", "Need at least 3 blocks!")
            return
        try:
            target = int(self.predict_entry.get().strip())
        except:
            messagebox.showerror("Error", "Valid block number")
            return
        current = max(int(h) for h in self.cache.keys())
        if target <= current:
            block = self.cache[str(target)]
            dt = datetime.fromtimestamp(block["time"])
            self.log_area.insert(tk.END, f"✅ Block {target:,} mined: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            self.log_area.see(tk.END)
            return
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
        all_heights = sorted(int(h) for h in self.cache.keys())
        use = all_heights[-2016:] if len(all_heights) > 2016 else all_heights
        t_start = self.cache[str(use[0])]["time"]
        t_end = self.cache[str(use[-1])]["time"]
        avg = (t_end - t_start) / (use[-1] - use[0]) if len(use) > 1 else 600
        messagebox.showinfo("Recent Rate", f"Recent average: {avg:.2f} sec/block (using {len(use):,} blocks)")

    def update_status(self):
        n = len(self.cache)
        if n > 0:
            mx = max(int(h) for h in self.cache.keys())
            tip = self.get_current_height()
            block = self.cache[str(mx)]
            ideal = GENESIS_TIMESTAMP + mx * 600
            delta = (block["time"] - ideal) / 86400.0
            self.status_cached.config(text=f"Cached Blocks: {n:,}")
            self.status_network.config(text=f"Network Tip: {mx:,} / {tip:,}")
            self.status_drift.config(text=f"Drift: {delta:+.2f} days")
        else:
            self.status_cached.config(text="Cached Blocks: 0")
            self.status_network.config(text="Network Tip: — / —")
            self.status_drift.config(text="Drift: —")

    def periodic_new_block_checker(self):
        if time.time() - self.last_new_block_check >= 33.1 * 60:
            self.last_new_block_check = time.time()
            threading.Thread(target=self.check_and_fetch_new_blocks, daemon=True).start()
        self.after(60000, self.periodic_new_block_checker)

    def check_and_fetch_new_blocks(self):
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
        self.status_cached = ttk.Label(sf, text="Cached Blocks: 0")
        self.status_cached.grid(row=0, column=0, sticky="w", padx=10)
        self.status_network = ttk.Label(sf, text="Network Tip: — / —")
        self.status_network.grid(row=0, column=1, sticky="w", padx=10)
        self.status_drift = ttk.Label(sf, text="Drift: —")
        self.status_drift.grid(row=1, column=0, sticky="w", padx=10)

        pf = ttk.LabelFrame(self, text="Live Fetch Progress", padding=8)
        pf.pack(fill="x", padx=15, pady=4)
        self.live_progress = ttk.Label(pf, text="→ Ready", foreground="#0066cc", font=("Consolas", 11))
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

        pred_live_frame = ttk.LabelFrame(self, text="Live Predictions", padding=12)
        pred_live_frame.pack(fill="x", padx=15, pady=8)
        self.lbl_diff = ttk.Label(pred_live_frame, text="Next Diff Adj: —")
        self.lbl_diff.pack(side="left", padx=12)
        self.lbl_hr = ttk.Label(pred_live_frame, text="Est Hashrate: —")
        self.lbl_hr.pack(side="left", padx=12)
        self.lbl_price = ttk.Label(pred_live_frame, text="Est Price: —")
        self.lbl_price.pack(side="left", padx=12)
        self.lbl_ratio = ttk.Label(pred_live_frame, text="HR/Price: —")
        self.lbl_ratio.pack(side="left", padx=12)
        self.lbl_tx = ttk.Label(pred_live_frame, text="Est Tx: —")
        self.lbl_tx.pack(side="left", padx=12)
        self.lbl_nonce = ttk.Label(pred_live_frame, text="Est Nonce: —")
        self.lbl_nonce.pack(side="left", padx=12)
        self.lbl_win_nonce = ttk.Label(pred_live_frame, text="Potential Winning Nonce: —")
        self.lbl_win_nonce.pack(side="left", padx=12)

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
        self.log_area.insert(tk.END, "👋 OPTIMIZED DYNAMIC VERSION LOADED!\n"
                                      "• Everything updates live during sync\n"
                                      "• Live data stays visible after Stop\n"
                                      "• Only partial blocks are refreshed\n\n")

        ttk.Label(self, text=f"Persistent file: {CACHE_FILE}  |  Temp file: {TEMP_FILE} (auto-cleaned)", font=("Helvetica", 9), foreground="gray").pack(pady=5)

if __name__ == "__main__":
    app = BTCBlockPredictorGUI()
    app.mainloop()
