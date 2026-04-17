import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import requests
import json
import time
from datetime import datetime
import os
from typing import Dict, Optional, List
import random
from threading import RLock
import sys
import textwrap
import re

CACHE_FILE = "BBTP.crumbs"
BTC_CHAIN_FILE = "BTC.chain"
BR_CURVE_FILE = "BR.curve"
BRC_ARCH_FILE = "BRC.arch"
BR_MATHS_FILE = "BR.maths"
PREDICTS_FILE = "predicts.block"
LIVEP_FILE = "LiveP.btc"
DATA_SETTINGS_FILE = "data_settings.json"
API_SETTINGS_FILE = "api_settings.json"
LOG_FILE = "BBTP.log"
TEMP_FILE = "BBTP.temp"

GENESIS_TIMESTAMP = 1231006505
DIFFICULTY_EPOCH = 2016

class RichBlockFetcher:
    def __init__(self, data_settings, api_settings, api_flags):
        self.apis = [
            {"name": "Mempool.space", "get": self._mempool_get},
            {"name": "Blockstream.info", "get": self._blockstream_get},
            {"name": "Chain.so", "get": self._chainso_get},
            {"name": "Blockchair.com", "get": self._blockchair_get},
            {"name": "Blockcypher.com", "get": self._blockcypher_get},
        ]
        self.idx = 0
        self.last_api_used = ""
        self.data_settings = data_settings
        self.api_settings = api_settings
        self.api_flags = api_flags

    def _update_api_flag(self, name: str, success: bool, error_type: str = None):
        if name not in self.api_flags:
            self.api_flags[name] = {"status": "green", "cooldown_until": 0, "error_count": 0}
        flag = self.api_flags[name]
        now = time.time()
        if success:
            flag["status"] = "green"
            flag["error_count"] = 0
            flag["cooldown_until"] = 0
        else:
            flag["error_count"] += 1
            if flag["error_count"] >= 3:
                flag["status"] = "red"
                flag["cooldown_until"] = now + 77 * 60
            elif flag["error_count"] == 2:
                flag["status"] = "orange"
                flag["cooldown_until"] = now + 5 * 60
            elif error_type == "cooldown":
                flag["status"] = "blue"
            else:
                flag["status"] = "yellow"
        return flag

    def _mempool_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Mempool.space"
        try:
            r = requests.get(f"https://mempool.space/api/block-height/{height}", timeout=8)
            r.raise_for_status()
            bh = r.text.strip()
            r = requests.get(f"https://mempool.space/api/block/{bh}", timeout=8)
            r.raise_for_status()
            data = r.json()
            self._update_api_flag("Mempool.space", True)
            return self._filter_block_data({
                "time": data.get("timestamp") or data.get("time"),
                "hash": data.get("id"),
                "size": data.get("size"),
                "tx_count": data.get("tx_count"),
                "nonce": data.get("nonce"),
                "difficulty": data.get("difficulty"),
            })
        except Exception as e:
            self._update_api_flag("Mempool.space", False, str(e))
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
            self._update_api_flag("Blockstream.info", True)
            return self._filter_block_data({
                "time": data.get("timestamp"),
                "hash": data.get("id"),
                "size": data.get("size"),
                "tx_count": data.get("tx_count"),
                "nonce": data.get("nonce"),
                "difficulty": data.get("difficulty"),
            })
        except Exception as e:
            self._update_api_flag("Blockstream.info", False, str(e))
            return None

    def _chainso_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Chain.so"
        try:
            r = requests.get(f"https://chain.so/api/v3/block/BTC/{height}", timeout=8)
            r.raise_for_status()
            data = r.json().get("data", {})
            self._update_api_flag("Chain.so", True)
            return self._filter_block_data({
                "time": data.get("time"),
                "hash": data.get("hash"),
                "size": data.get("size"),
                "tx_count": data.get("n_tx"),
                "nonce": data.get("nonce"),
                "difficulty": data.get("difficulty"),
            })
        except Exception as e:
            self._update_api_flag("Chain.so", False, str(e))
            return None

    def _blockchair_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Blockchair.com"
        try:
            r = requests.get(f"https://api.blockchair.com/bitcoin/blocks?q=height({height})", timeout=8)
            r.raise_for_status()
            data = r.json()["data"][0]
            self._update_api_flag("Blockchair.com", True)
            return self._filter_block_data({
                "time": data.get("time"),
                "hash": data.get("hash"),
                "size": data.get("size"),
                "tx_count": data.get("transaction_count"),
                "nonce": data.get("nonce"),
                "difficulty": data.get("difficulty"),
            })
        except Exception as e:
            self._update_api_flag("Blockchair.com", False, str(e))
            return None

    def _blockcypher_get(self, height: int) -> Optional[dict]:
        self.last_api_used = "Blockcypher.com"
        try:
            r = requests.get(f"https://api.blockcypher.com/v1/btc/main/blocks/{height}", timeout=8)
            r.raise_for_status()
            data = r.json()
            self._update_api_flag("Blockcypher.com", True)
            return self._filter_block_data({
                "time": data.get("time"),
                "hash": data.get("hash"),
                "size": data.get("size"),
                "tx_count": data.get("n_tx"),
                "nonce": data.get("nonce"),
                "difficulty": data.get("difficulty"),
            })
        except Exception as e:
            self._update_api_flag("Blockcypher.com", False, str(e))
            return None

    def _filter_block_data(self, block: dict) -> dict:
        filtered = {}
        for k, v in block.items():
            if self.data_settings.get(k, True):
                filtered[k] = v
        return filtered

    def get_full_block(self, height: int, cache: Dict[str, dict]) -> Optional[dict]:
        h_str = str(height)
        existing = cache.get(h_str)
        block_data = None
        start = self.idx
        for _ in range(len(self.apis)):
            api = self.apis[self.idx]
            name = api["name"]
            if self.api_settings.get(name, True):
                flag = self.api_flags.get(name, {"status": "green", "cooldown_until": 0})
                if flag["status"] not in ("red", "blue") or time.time() > flag["cooldown_until"]:
                    block_data = api["get"](height)
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
    def __init__(self, data_settings):
        self.data_settings = data_settings

    def get_price_at_timestamp(self, ts: int) -> Optional[float]:
        if not self.data_settings.get("price", True):
            return None
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
        self.title("🟠 BTC Block Time Predictor [BBTP]")
        self.geometry("1420x980")
        self.minsize(900, 650)
        self.resizable(True, True)

        # === LOAD bbtp-icon.png FOR WINDOW / TASK MANAGER ===
        self.set_window_icon()

        self.update_queue = queue.Queue()
        self.cache: Dict[str, dict] = {}
        self.chain: Dict[str, dict] = {}
        self.predicts: List[dict] = []
        self.livep: List[dict] = []
        self.api_flags: Dict[str, dict] = {}
        self.prediction_adjusters = {"hr_trend": 0, "price_trend": 0, "error_rate": 0.0, "last_trend_adjust": 0}
        self.fetcher = None
        self.enricher = None
        self.sync_stop_event = threading.Event()
        self.sync_running = False
        self.refresh_running = False
        self.pause_needed = False
        self.last_new_block_check = time.time()
        self.cooldown_active = False
        self.session_fetched = 0
        self.session_oldest = 0
        self.session_top = 0
        self.cache_lock = RLock()
        self.last_price_fetch = 0
        self.data_api_cooldown_until = 0
        self.extra_api_cooldown_until = 0
        self.last_est_nonce = 0
        self.last_win_nonce = 1337
        self.current_tip_height = 0
        self.current_tip_nonce = None
        self.new_cache_created_on_startup = not os.path.exists(CACHE_FILE)
        self.last_save_time = 0.0
        self.bulk_save_interval = 2.5
        self.last_progress_text = "→ Ready"
        self.current_sync_total = 0
        self.current_sync_fetched = 0
        self.current_sync_phase = 0
        self.current_sync_mode = ""
        self.window_width = 1420
        self.window_height = 980
        self.unfinished_work = []
        self.debug_active = False

        self.data_settings = {
            "timestamp": True, "hash": True, "size": True, "tx_count": True,
            "nonce": True, "difficulty": True, "hashrate": True, "price": True,
            "merkle_root": False, "version": False, "prev_hash": False,
            "bits_raw": False, "full_tx": False
        }
        self.api_settings = {
            "Mempool.space": True, "Blockstream.info": True, "Chain.so": True,
            "Blockchair.com": False, "Blockcypher.com": False
        }
        self.online_mode = True
        self.log_settings = {
            "debug_data": False, "welcome_kit": True, "smart_welcome": False,
            "dumb_welcome": False, "no_seq_repeats": False, "no_repeats": False,
            "export_logs": False, "persistence_logs": False
        }

        self.load_all_settings()
        self.load_api_flags()
        self.fetcher = RichBlockFetcher(self.data_settings, self.api_settings, self.api_flags)
        self.enricher = DataEnricher(self.data_settings)

        try:
            self.load_cache()
            self.load_chain()
            self.load_predicts()
            self.load_livep()
            self.load_temp_state()
            if not self.cache and os.path.exists(BTC_CHAIN_FILE):
                self.bootstrap_from_chain()
            self.merge_complete_to_chain()
            self._update_sticky_nonce_predictions(force=True)
        except Exception as e:
            print(f"⚠️ Startup error: {e}")
            self.cache = {}
            self.chain = {}
            self.predicts = []
            self.livep = []
            self.api_flags = {}

        self.create_widgets()
        self._build_dynamic_welcome()
        self.update_status()
        self.after(500, self.pre_fill_all_notebooks)
        self.after(1000, self.periodic_new_block_checker)
        self.after(60000, self.periodic_notebook_refresh)
        self.after(300, self.live_timer)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def set_window_icon(self):
        """Load bbtp-icon.png for window / task manager"""
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bbtp-icon.png")
        try:
            if os.path.exists(icon_path):
                photo = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, photo)
                self._icon_image = photo
                print("✅ Loaded bbtp-icon.png for window / task manager")
                return
            else:
                print("⚠️ bbtp-icon.png not found next to BBTP.py")
        except Exception as e:
            print(f"⚠️ Window icon load failed: {e}")
        print("⚠️ Using no icon for window (PNG missing)")

    # === ALL OTHER METHODS (unchanged) ===
    def advanced_math_wrap(self, text, width=48):
        if not text or len(str(text)) <= width:
            return str(text)
        text = re.sub(r'([=+*/(),;:\[\]{}])', r' \1 ', str(text))
        text = re.sub(r'\s+', ' ', text).strip()
        wrapped = textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=True, replace_whitespace=True)
        return wrapped

    def scroll_notebook_y(self, *args):
        if hasattr(self, "tree"):
            self.tree.yview(*args)

    def set_notebook_scroll(self, first, last):
        if hasattr(self, "hsb_notebook"):
            self.hsb_notebook.set(first, last)

    def scroll_predicts_y(self, *args):
        if hasattr(self, "predict_tree"):
            self.predict_tree.yview(*args)

    def set_predicts_scroll(self, first, last):
        if hasattr(self, "hsb_predicts"):
            self.hsb_predicts.set(first, last)

    def scroll_livep_y(self, *args):
        if hasattr(self, "livep_tree"):
            self.livep_tree.yview(*args)

    def set_livep_scroll(self, first, last):
        if hasattr(self, "hsb_livep"):
            self.hsb_livep.set(first, last)

    def scroll_maths_y(self, *args):
        if hasattr(self, "maths_tree"):
            self.maths_tree.yview(*args)

    def set_maths_scroll(self, first, last):
        if hasattr(self, "hsb_maths"):
            self.hsb_maths.set(first, last)

    def refresh_notebook_view(self):
        if not hasattr(self, "tree"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "__settings__" in data:
                data.pop("__settings__")
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
            hash_str = str(b.get("hash", ""))
            stripped = hash_str.lstrip("0")
            leading_zeros = len(hash_str) - len(stripped) if hash_str else 0
            display_hash = f"{stripped[:6]}...{stripped[-6:]}" if len(stripped) > 12 else stripped or "—"
            self.tree.insert("", "end", values=(
                h, b.get("time", 0), leading_zeros, display_hash,
                b.get("size", ""), b.get("tx_count", ""), b.get("nonce", ""),
                f"{b.get('difficulty', 0):.2f}" if b.get("difficulty") else "",
                f"{b.get('estimated_hashrate', 0):.4f}" if b.get("estimated_hashrate") else "",
                f"${b.get('price_usd', 0):,.2f}" if b.get("price_usd") else ""
            ))
        self.page_label.config(text=f"Page {self.current_page + 1} / {max(1, total_pages)}")

    def clear_notebook_filters(self):
        self.filter_min.delete(0, tk.END)
        self.filter_max.delete(0, tk.END)
        self.search_var.set("")
        self.current_page = 0
        self.refresh_notebook_view()

    def refresh_predicts_view(self):
        if not hasattr(self, "predict_tree"):
            return
        for item in self.predict_tree.get_children():
            self.predict_tree.delete(item)
        term = self.predict_search_var.get().strip().lower()
        filtered = self.predicts
        if term:
            filtered = [p for p in self.predicts if term in str(p.get("target", "")) or term in str(p.get("est_time_str", ""))]
        total_pages = (len(filtered) + self.predict_page_size - 1) // self.predict_page_size
        start = self.predict_current_page * self.predict_page_size
        page_data = filtered[start:start + self.predict_page_size]
        for p in page_data:
            self.predict_tree.insert("", "end", values=(
                p.get("target", ""),
                p.get("est_time_str", ""),
                f"{p.get('delta_days', 0):+.2f}",
                p.get("est_hr", ""),
                p.get("est_price", ""),
                p.get("est_tx", ""),
                p.get("timestamp_str", "")
            ))
        self.predict_page_label.config(text=f"Page {self.predict_current_page + 1} / {max(1, total_pages)}")

    def clear_predicts_filters(self):
        self.predict_search_var.set("")
        self.predict_current_page = 0
        self.refresh_predicts_view()

    def refresh_livep_view(self):
        if not hasattr(self, "livep_tree"):
            return
        for item in self.livep_tree.get_children():
            self.livep_tree.delete(item)
        term = self.livep_search_var.get().strip().lower()
        filtered = self.livep
        if term:
            filtered = [p for p in self.livep if term in str(p.get("timestamp", ""))]
        total_pages = (len(filtered) + self.livep_page_size - 1) // self.livep_page_size
        start = self.livep_current_page * self.livep_page_size
        page_data = filtered[start:start + self.livep_page_size]
        for p in page_data:
            self.livep_tree.insert("", "end", values=(
                p.get("timestamp", ""),
                p.get("next_diff_adj", ""),
                p.get("est_hr", ""),
                p.get("est_price", ""),
                p.get("est_tx", ""),
                p.get("est_nonce", ""),
                p.get("win_nonce", "")
            ))
        self.livep_page_label.config(text=f"Page {self.livep_current_page + 1} / {max(1, total_pages)}")

    def clear_livep_filters(self):
        self.livep_search_var.set("")
        self.livep_current_page = 0
        self.refresh_livep_view()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_notebook_view()

    def next_page(self):
        self.current_page += 1
        self.refresh_notebook_view()

    def prev_predict_page(self):
        if self.predict_current_page > 0:
            self.predict_current_page -= 1
            self.refresh_predicts_view()

    def next_predict_page(self):
        self.predict_current_page += 1
        self.refresh_predicts_view()

    def prev_livep_page(self):
        if self.livep_current_page > 0:
            self.livep_current_page -= 1
            self.refresh_livep_view()

    def next_livep_page(self):
        self.livep_current_page += 1
        self.refresh_livep_view()

    def pre_fill_all_notebooks(self):
        self.queue_update("🔄 Pre-filling notebook data at startup...")

    def load_api_flags(self):
        for name in self.api_settings:
            self.api_flags[name] = {"status": "green", "cooldown_until": 0, "error_count": 0}

    def _safe_timestamp(self, time_val):
        if isinstance(time_val, (int, float)):
            return int(time_val)
        if isinstance(time_val, str):
            try:
                clean = time_val.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean)
                return int(dt.timestamp())
            except:
                pass
        return 0

    def load_all_settings(self):
        for f, d in [(DATA_SETTINGS_FILE, self.data_settings), (API_SETTINGS_FILE, self.api_settings)]:
            if os.path.exists(f):
                try:
                    with open(f, "r", encoding="utf-8") as file:
                        loaded = json.load(file)
                    d.update(loaded)
                except:
                    pass

    def save_all_settings(self):
        for f, d in [(DATA_SETTINGS_FILE, self.data_settings), (API_SETTINGS_FILE, self.api_settings)]:
            try:
                with open(f, "w", encoding="utf-8") as file:
                    json.dump(d, file, indent=2)
            except:
                pass

    def _build_dynamic_welcome(self):
        n = len(self.cache)
        tip = self.get_current_height()
        cached_max = max((int(h) for h in self.cache.keys()), default=0) if n > 0 else 0
        welcome = "👋 Thank you for using BBTP!\n"
        if self.new_cache_created_on_startup:
            welcome += f"🆕 Created new persistent file: {CACHE_FILE}\n"
        welcome += f"🆕 BTC.chain archive ready\n"
        welcome += f"📊 Loaded {n:,} blocks • Tip at {cached_max:,} / Network {tip:,}\n"
        welcome += "• Quick Sync = recent blocks only (fast)\n"
        welcome += "• Full Backward = everything from genesis (slow)\n"
        welcome += "• Refresh = fixes incomplete blocks\n"
        welcome += "• Use ⚙️ L&R to control what appears in this log\n"
        self.log_area.insert(tk.END, welcome + "\n")

    def on_closing(self):
        answer = messagebox.askyesnocancel(
            "Shutdown Confirmation",
            "A Shutdown has begun...\nDo you want to proceed?"
        )
        if answer is None or answer is False:
            return
        if self.sync_running or self.refresh_running:
            self.sync_stop_event.set()
            time.sleep(1.2)
        self.save_window_size()
        self.save_all_settings()
        try:
            self.destroy()
        except:
            pass
        sys.exit(0)

    def save_window_size(self):
        try:
            self.window_width = self.winfo_width()
            self.window_height = self.winfo_height()
            temp_data = {
                "width": self.window_width,
                "height": self.window_height,
                "unfinished_work": self.unfinished_work if self.unfinished_work else [],
                "api_flags": self.api_flags,
                "prediction_adjusters": self.prediction_adjusters,
                "log_settings": self.log_settings
            }
            with open(TEMP_FILE, "w", encoding="utf-8") as f:
                json.dump(temp_data, f)
        except:
            pass

    def load_temp_state(self):
        if os.path.exists(TEMP_FILE):
            try:
                with open(TEMP_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.geometry(f"{data.get('width', 1420)}x{data.get('height', 980)}")
                self.unfinished_work = data.get("unfinished_work", [])
                self.api_flags = data.get("api_flags", {})
                self.prediction_adjusters = data.get("prediction_adjusters", {"hr_trend": 0, "price_trend": 0, "error_rate": 0.0, "last_trend_adjust": 0})
                self.log_settings.update(data.get("log_settings", self.log_settings))
                if self.unfinished_work:
                    self.after(500, self.show_unfinished_work_popup)
            except:
                pass

    def show_unfinished_work_popup(self):
        win = tk.Toplevel(self)
        win.title("Previous Session Work")
        win.geometry("620x300")
        ttk.Label(win, text="Previous session had unfinished/paused work.\nDo you want to carry-on and carry-over this work?", font=("Helvetica", 12)).pack(pady=20)
        frame = ttk.Frame(win)
        frame.pack(pady=10)
        ttk.Button(frame, text="Yes Carry-Over", command=lambda: self._carry_over_work(win)).pack(side="left", padx=10)
        ttk.Button(frame, text="Not Yet", command=lambda: self._defer_work(win)).pack(side="left", padx=10)
        ttk.Button(frame, text="No!", command=lambda: self._cancel_work(win)).pack(side="left", padx=10)

    def _carry_over_work(self, win):
        win.destroy()
        self.queue_update("🔄 Resuming previous unfinished work...")
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)

    def _defer_work(self, win):
        win.destroy()

    def _cancel_work(self, win):
        win.destroy()
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)

    def _is_complete_block(self, block: dict) -> bool:
        required = ["time", "hash", "size", "tx_count", "difficulty", "estimated_hashrate", "price_usd"]
        return all(block.get(k) is not None for k in required)

    def load_cache(self):
        with self.cache_lock:
            try:
                if os.path.exists(CACHE_FILE):
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if "__settings__" in raw:
                        self.data_settings.update(raw.pop("__settings__"))
                    for h_str, v in list(raw.items()):
                        if not isinstance(v, dict):
                            raw[h_str] = {"time": v} if isinstance(v, (int, float)) else {}
                    self.cache = raw
                else:
                    self.cache = {}
                    with open(CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump({"__settings__": self.data_settings}, f, indent=None, separators=(',', ':'))
            except Exception as e:
                print(f"⚠️ Cache load failed: {e}")
                self.cache = {}

    def load_chain(self):
        with self.cache_lock:
            try:
                if os.path.exists(BTC_CHAIN_FILE):
                    with open(BTC_CHAIN_FILE, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, list):
                        self.chain = {str(item["height"]): item for item in raw if isinstance(item, dict) and "height" in item}
                    else:
                        self.chain = {str(k): v for k, v in raw.items()}
                else:
                    self.chain = {}
                    with open(BTC_CHAIN_FILE, "w", encoding="utf-8") as f:
                        json.dump([], f, indent=2)
            except Exception as e:
                print(f"⚠️ BTC.chain load failed: {e}")
                self.chain = {}

    def load_predicts(self):
        if os.path.exists(PREDICTS_FILE):
            try:
                with open(PREDICTS_FILE, "r", encoding="utf-8") as f:
                    self.predicts = [json.loads(line) for line in f if line.strip()]
            except:
                self.predicts = []
        else:
            self.predicts = []
            with open(PREDICTS_FILE, "w", encoding="utf-8") as f:
                pass

    def load_livep(self):
        if os.path.exists(LIVEP_FILE):
            try:
                with open(LIVEP_FILE, "r", encoding="utf-8") as f:
                    self.livep = [json.loads(line) for line in f if line.strip()]
            except:
                self.livep = []
        else:
            self.livep = []
            with open(LIVEP_FILE, "w", encoding="utf-8") as f:
                pass

    def save_predicts(self):
        try:
            with open(PREDICTS_FILE, "w", encoding="utf-8") as f:
                for p in self.predicts:
                    f.write(json.dumps(p) + "\n")
        except Exception as e:
            print(f"⚠️ Predicts save failed: {e}")

    def save_livep(self):
        try:
            with open(LIVEP_FILE, "w", encoding="utf-8") as f:
                for p in self.livep:
                    f.write(json.dumps(p) + "\n")
        except:
            pass

    def save_chain(self):
        with self.cache_lock:
            try:
                chain_list = sorted(
                    [{"height": int(h), **block} for h, block in self.chain.items()],
                    key=lambda x: x["height"], reverse=True
                )
                with open(BTC_CHAIN_FILE, "w", encoding="utf-8") as f:
                    json.dump(chain_list, f, indent=2)
            except Exception as e:
                print(f"⚠️ Chain save failed: {e}")

    def merge_complete_to_chain(self):
        try:
            with self.cache_lock:
                added = 0
                for h_str, block in list(self.cache.items()):
                    if self._is_complete_block(block) and h_str not in self.chain:
                        self.chain[h_str] = block.copy()
                        added += 1
            if added > 0:
                self.save_chain()
                self.queue_update(f"✅ Merged {added:,} complete blocks into BTC.chain")
        except Exception as e:
            print(f"⚠️ Merge to chain failed: {e}")

    def get_temp_cache_file(self, method: str) -> str:
        filename = f"{method}_cache.crumbs"
        if not os.path.exists(filename):
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({}, f)
        return filename

    def clear_temp_cache_if_empty(self, filename: str):
        try:
            if os.path.exists(filename):
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data:
                    os.remove(filename)
        except:
            pass

    def save_cache(self, force=False):
        with self.cache_lock:
            try:
                now = time.time()
                if not force and (now - self.last_save_time < self.bulk_save_interval):
                    return
                self.last_save_time = now
                data_to_save = {"__settings__": self.data_settings}
                data_to_save.update(self.cache)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data_to_save, f, indent=None, separators=(',', ':'))
            except Exception as e:
                print(f"⚠️ Save failed: {e}")

    def get_full_block(self, height: int, force_save=False) -> Optional[dict]:
        h_str = str(height)
        with self.cache_lock:
            data = self.fetcher.get_full_block(height, self.cache)
        if data:
            self._enrich_block(h_str)
            self._update_sticky_nonce_predictions()
            if self._is_complete_block(data):
                with self.cache_lock:
                    if h_str not in self.chain:
                        self.chain[h_str] = data.copy()
            if force_save or time.time() - self.last_save_time > self.bulk_save_interval:
                self.save_cache(force=True)
                self.save_chain()
            self.after(10, self.update_status)
            self.after(10, self.auto_update_predictions)
            self._save_live_prediction()
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
                    price = self.enricher.get_price_at_timestamp(self._safe_timestamp(ts))
                    self.last_price_fetch = now
                    if price is not None:
                        block["price_usd"] = price
            if "difficulty" in block and block["difficulty"] and ("estimated_hashrate" not in block or block["estimated_hashrate"] is None):
                hr = self.enricher.estimate_hashrate(block["difficulty"])
                if hr is not None:
                    block["estimated_hashrate"] = hr
            self.cache[h_str] = block

    def _update_sticky_nonce_predictions(self, force=False):
        if len(self.cache) < 10 and not force:
            return
        with self.cache_lock:
            nonces = [b.get("nonce") for b in self.cache.values()
                      if isinstance(b.get("nonce"), (int, float)) and b.get("nonce") > 1000000]
            if not nonces:
                self.last_est_nonce = 0
            else:
                min_n = min(nonces)
                max_n = max(nonces)
                range_est = random.randint(int(min_n / 3), int(max_n * 3))
                recent_nonces = nonces[-100:]
                mean_n = sum(recent_nonces) // len(recent_nonces)
                spread = max(10000000, (max(recent_nonces) - min(recent_nonces)) * 2)
                mean_est = random.randint(max(0, mean_n - spread), mean_n + spread)
                last_n = recent_nonces[-1]
                last_est = random.randint(max(0, last_n - 50000000), last_n + 50000000)
                avg_est = (range_est + mean_est + last_est) // 3
                self.last_est_nonce = max(0, min(avg_est, 4294967295))
            self.last_win_nonce = self.last_est_nonce + 1337

    def _save_live_prediction(self):
        if len(self.cache) < 3:
            return
        with self.cache_lock:
            current = max(int(h) for h in self.cache.keys())
            block = self.cache[str(current)]
            entry = {
                "timestamp": int(time.time()),
                "next_diff_adj": DIFFICULTY_EPOCH - (current % DIFFICULTY_EPOCH),
                "est_hr": block.get("estimated_hashrate", 0),
                "est_price": block.get("price_usd", 0),
                "est_tx": block.get("tx_count", 0),
                "est_nonce": self.last_est_nonce,
                "win_nonce": self.last_win_nonce
            }
            self.livep.insert(0, entry)
            if len(self.livep) > 500:
                self.livep = self.livep[:500]
        self.save_livep()

    def calculate_trends(self):
        if len(self.cache) < 50:
            return
        with self.cache_lock:
            sorted_h = sorted(self.cache.keys(), key=int, reverse=True)
            recent = [self.cache[h] for h in sorted_h[:50]]
            last = self.cache[sorted_h[0]]
            prev = self.cache[sorted_h[1]] if len(sorted_h) > 1 else last
            hr_trend = 2 if last.get("estimated_hashrate", 0) > prev.get("estimated_hashrate", 0) else 1 if last.get("estimated_hashrate", 0) < prev.get("estimated_hashrate", 0) else 0
            price_trend = 2 if last.get("price_usd", 0) > prev.get("price_usd", 0) else 1 if last.get("price_usd", 0) < prev.get("price_usd", 0) else 0
            self.prediction_adjusters["hr_trend"] = hr_trend
            self.prediction_adjusters["price_trend"] = price_trend
            self.prediction_adjusters["last_trend_adjust"] = time.time()

    def adjust_prediction(self, est_value: float, field: str) -> float:
        self.calculate_trends()
        trend = self.prediction_adjusters.get(field + "_trend", 0)
        error_rate = self.prediction_adjusters.get("error_rate", 0.0)
        multiplier = 1.0
        if trend == 2:
            multiplier = 1.04
        elif trend == 1:
            multiplier = 0.96
        if error_rate > 0.2:
            multiplier *= 0.85
        return round(est_value * multiplier, 4 if field == "hr" else 2)

    def refresh_cached_blocks(self):
        if self.sync_running or self.refresh_running:
            messagebox.showinfo("Busy", "Wait for current operation")
            return
        if time.time() < self.data_api_cooldown_until:
            self.queue_update("⏳ Data APIs on cooldown")
            return

        with self.cache_lock:
            partial_count = sum(1 for b in self.cache.values() if not self._is_complete_block(b))
        if partial_count > 200:
            win = tk.Toplevel(self)
            win.title("⚠️ Large Refresh Detected")
            win.geometry("620x420")
            ttk.Label(win, text=f"Found {partial_count:,} incomplete blocks.\nRefresh may take a long time.", font=("Helvetica", 12, "bold")).pack(pady=15)
            frame = ttk.Frame(win)
            frame.pack(pady=10)
            ttk.Button(frame, text="Proceed (All Passes)", command=lambda: self._start_refresh(win, "all")).grid(row=0, column=0, padx=5)
            ttk.Button(frame, text="1st Pass Only", command=lambda: self._start_refresh(win, "pass1")).grid(row=0, column=1, padx=5)
            ttk.Button(frame, text="1st & 2nd Passes Only", command=lambda: self._start_refresh(win, "pass12")).grid(row=1, column=0, padx=5)
            ttk.Button(frame, text="Top Half Only", command=lambda: self._start_refresh(win, "half")).grid(row=1, column=1, padx=5)
            ttk.Button(frame, text="Top Quarter Only", command=lambda: self._start_refresh(win, "quarter")).grid(row=2, column=0, padx=5)
            ttk.Button(frame, text="Cancel Refresh", command=win.destroy).grid(row=2, column=1, padx=5)
            return

        self._start_refresh(None, "all")

    def _start_refresh(self, win, mode):
        if win:
            win.destroy()
        self.refresh_running = True
        self.btn_refresh.config(state="disabled")
        self.btn_quick.config(state="disabled")
        self.btn_backward.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.current_sync_mode = "Refresh"
        self._update_sync_progress_label()
        threading.Thread(target=self._refresh_thread, args=(mode,), daemon=True).start()

    def _refresh_thread(self, mode="all"):
        try:
            self.queue_update("🔄 Scanning for incomplete blocks...")
            temp_file = self.get_temp_cache_file("refresh")
            with self.cache_lock:
                partial = {h_str: b for h_str, b in self.cache.items() if not self._is_complete_block(b)}
            if not partial:
                self.queue_update("✅ All blocks already complete")
                self.clear_temp_cache_if_empty(temp_file)
                return
            self.queue_update(f"🔄 Found {len(partial):,} incomplete blocks")
            total_attempted = 0
            successful = 0
            failed = 0
            max_passes = 3 if mode == "all" else 1 if mode == "pass1" else 2 if mode == "pass12" else 3
            for pass_num in range(1, max_passes + 1):
                if self.sync_stop_event.is_set():
                    break
                self.queue_update(f"🔄 Pass {pass_num}/{max_passes} – updating incomplete blocks")
                refreshed_this_pass = 0
                for h_str in list(partial.keys()):
                    if self.sync_stop_event.is_set():
                        break
                    if self.pause_needed:
                        self.queue_update("⏸️ Refresh paused – waiting for APIs")
                        time.sleep(60)
                        continue
                    h = int(h_str)
                    result = self.get_full_block(h, force_save=(refreshed_this_pass % 20 == 0))
                    total_attempted += 1
                    if result and self._is_complete_block(result):
                        successful += 1
                        if h_str in partial:
                            del partial[h_str]
                    else:
                        failed += 1
                    refreshed_this_pass += 1
                    if refreshed_this_pass % 30 == 0:
                        self.queue_update(f"🔄 Pass {pass_num}: {refreshed_this_pass:,}/{len(partial):,} blocks processed")
                    time.sleep(0.65)
                with self.cache_lock:
                    partial = {h_str: b for h_str, b in self.cache.items() if not self._is_complete_block(b)}
                if not partial:
                    break
            self.merge_complete_to_chain()
            self.save_cache(force=True)
            self.save_chain()
            self.clear_temp_cache_if_empty(temp_file)
            self.queue_update(f"✅ Refresh complete – all {total_attempted:,} incomplete blocks updated")
        except Exception as e:
            self.queue_update(f"❌ Refresh error: {e}")
        finally:
            self.refresh_running = False
            self.btn_refresh.config(state="normal")
            self.btn_quick.config(state="normal")
            self.btn_backward.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.current_sync_mode = ""
            self._update_sync_progress_label()
            self.after(200, self.update_status)

    def _start_sync(self, mode: str = "quick"):
        if self.sync_running or self.refresh_running:
            messagebox.showinfo("Busy", "Wait for current operation")
            return
        if time.time() < self.data_api_cooldown_until:
            self.queue_update("⏳ Data APIs on cooldown")
            return
        if mode == "full":
            if not messagebox.askyesno("⚠️ FULL HISTORICAL SYNC", "This will fetch EVERY block from tip to Genesis.\n\nContinue?"):
                return
        self.sync_running = True
        self.sync_stop_event.clear()
        self.btn_stop.config(state="normal")
        self.btn_quick.config(state="disabled")
        self.btn_backward.config(state="disabled")
        self.btn_refresh.config(state="disabled")
        self.session_fetched = 0
        self.session_oldest = 0
        self.session_top = 0
        self.current_sync_fetched = 0
        self.current_sync_total = 0
        self.current_sync_phase = 0
        self.current_sync_mode = mode.capitalize()
        self.sync_progress_var.set(0)
        self._update_sync_progress_label()
        threading.Thread(target=self.sync_thread, args=(mode,), daemon=True).start()

    def sync_thread(self, mode: str):
        try:
            self.queue_update(f"🚀 Starting {mode.upper()} sync...")
            self.live_progress.config(text=f"🚀 Starting {mode.upper()} sync...")
            tip = self.get_current_height()
            if tip == 0:
                self.queue_update("❌ Cannot reach network tip")
                return
            with self.cache_lock:
                cached_max = max((int(h) for h in self.cache.keys()), default=0)
            gap = tip - cached_max
            self.session_oldest = tip
            self.session_top = tip
            fetched_in_batch = 0
            if mode == "quick":
                self.current_sync_total = min(2000, gap + 1) + 100
            elif mode == "full":
                self.current_sync_total = tip + 1 + 500
            else:
                self.current_sync_total = gap + 1 + 100
            if gap > 0:
                self.current_sync_phase = 1
                self.queue_update(f"🔼 Catching up {gap:,} new blocks...")
                for h in range(tip, cached_max, -1):
                    if self.sync_stop_event.is_set():
                        break
                    if self.pause_needed:
                        self.queue_update("⏸️ Sync paused – waiting for APIs")
                        time.sleep(60)
                        continue
                    if str(h) not in self.cache or not self._is_complete_block(self.cache.get(str(h), {})):
                        self.get_full_block(h, force_save=(fetched_in_batch % 30 == 0))
                    self.session_fetched += 1
                    fetched_in_batch += 1
                    self.current_sync_fetched = fetched_in_batch
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    if fetched_in_batch % 3 == 0:
                        self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                        self._safe_update_sync_progress()
                    time.sleep(0.35)
            if mode == "full":
                self.current_sync_phase = 2
                self.queue_update(f"🔄 FULL HISTORICAL BACKWARD SYNC...")
                for h in range(tip, -1, -1):
                    if self.sync_stop_event.is_set():
                        break
                    if self.pause_needed:
                        self.queue_update("⏸️ Sync paused – waiting for APIs")
                        time.sleep(60)
                        continue
                    if str(h) not in self.cache or not self._is_complete_block(self.cache.get(str(h), {})):
                        self.get_full_block(h, force_save=(fetched_in_batch % 30 == 0))
                    self.session_fetched += 1
                    fetched_in_batch += 1
                    self.current_sync_fetched = fetched_in_batch
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    if fetched_in_batch % 3 == 0:
                        self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                        self._safe_update_sync_progress()
                    time.sleep(0.50)
            elif mode == "quick":
                self.current_sync_phase = 2
                lower = max(cached_max, tip - 2000)
                self.queue_update(f"🔼 Quick backward sync...")
                for h in range(tip, lower - 1, -1):
                    if self.sync_stop_event.is_set():
                        break
                    if self.pause_needed:
                        self.queue_update("⏸️ Sync paused – waiting for APIs")
                        time.sleep(60)
                        continue
                    if str(h) not in self.cache or not self._is_complete_block(self.cache.get(str(h), {})):
                        self.get_full_block(h, force_save=(fetched_in_batch % 30 == 0))
                    self.session_fetched += 1
                    fetched_in_batch += 1
                    self.current_sync_fetched = fetched_in_batch
                    self.session_oldest = min(self.session_oldest, h)
                    self.session_top = max(self.session_top, h)
                    if fetched_in_batch % 3 == 0:
                        self.queue_progress(self.session_fetched, h, self.session_oldest, self.session_top)
                        self._safe_update_sync_progress()
                    time.sleep(0.42)
            self.current_sync_phase = 3
            self.queue_update("🔄 Phase 3: Checking partial blocks...")
            temp_file = self.get_temp_cache_file("sync")
            with self.cache_lock:
                partial = {h: b for h, b in self.cache.items() if not self._is_complete_block(b)}
            if partial:
                self.queue_update(f" Found {len(partial):,} partial blocks")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(partial, f, indent=2)
                phase3_count = 0
                for h_str in list(partial.keys()):
                    if self.sync_stop_event.is_set():
                        break
                    self.get_full_block(int(h_str), force_save=True)
                    phase3_count += 1
                    self.current_sync_fetched += 1
                    if phase3_count % 3 == 0:
                        self._safe_update_sync_progress()
                    self.after(10, self.update_status)
                    time.sleep(0.65)
            else:
                self.queue_update("✅ All blocks already complete")
            self.merge_complete_to_chain()
            self.save_cache(force=True)
            self.save_chain()
            self.clear_temp_cache_if_empty(temp_file)
            self.queue_update(f"✅ {mode.upper()} dynamic sync finished")
        except Exception as e:
            self.queue_update(f"❌ Sync error: {e}")
        finally:
            self.sync_running = False
            self.btn_stop.config(state="disabled")
            self.btn_quick.config(state="normal")
            self.btn_backward.config(state="normal")
            self.btn_refresh.config(state="normal")
            self.last_progress_text = "→ Ready"
            self.live_progress.config(text="→ Ready")
            self.sync_progress_var.set(0)
            self.current_sync_mode = ""
            self._update_sync_progress_label()
            self.after(200, self.update_status)

    def _safe_update_sync_progress(self):
        if self.current_sync_total > 0:
            pct = min(100.0, (self.current_sync_fetched / self.current_sync_total) * 100)
            self.after(0, lambda p=pct: self.sync_progress_var.set(p))
            self.after(0, lambda p=pct: self._update_sync_progress_label(p))

    def _update_sync_progress_label(self, pct=None):
        if not hasattr(self, "sync_progress_label"):
            return
        if not (self.sync_running or self.refresh_running):
            self.sync_progress_label.config(text="✅ Idle – Ready for next operation")
            return
        if self.pause_needed:
            self.sync_progress_label.config(text="⏸️ Sync Paused – waiting for APIs")
            return
        mode_str = self.current_sync_mode or "Processing"
        phase_names = {1: "Catching up", 2: "Historical", 3: "Partial check"}
        phase = phase_names.get(self.current_sync_phase, "")
        display_pct = min(99, int(pct) if pct is not None else 0)
        emoji = "🔥" if mode_str == "Quick" else "🔄" if mode_str in ("Full", "Refresh") else "📊"
        self.sync_progress_label.config(text=f"{emoji} {mode_str} – {phase} – {display_pct}%")

    def stop_sync(self):
        self.sync_stop_event.set()
        self.queue_update("⏹️ Stop signal sent...")
        self.btn_stop.config(state="disabled")

    def live_timer(self):
        self.update_status()
        self.auto_update_predictions()
        self.check_cooldown_status()
        self.after(300, self.live_timer)

    def check_cooldown_status(self):
        now = time.time()
        if now < self.data_api_cooldown_until:
            remaining = int(self.data_api_cooldown_until - now)
            self.live_progress.config(text=f"⏳ DATA COOLDOWN: {remaining}s")
        elif now < self.extra_api_cooldown_until:
            remaining = int(self.extra_api_cooldown_until - now)
            self.live_progress.config(text=f"⏳ EXTRA COOLDOWN: {remaining}s")
        else:
            self.live_progress.config(text=self.last_progress_text)

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
            est_hr = self.adjust_prediction(avg_hr * (1 + (target - current) * 0.0000235), "hr")
            est_price = self.adjust_prediction(avg_price * (1 + (target - current) * 0.00002), "price")
            est_tx = int(avg_tx * 1.015)
        nonce_text = f"{self.last_est_nonce}" if self.last_est_nonce is not None else "0"
        win_text = f"{self.last_win_nonce}" if self.last_win_nonce is not None else "1337"
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
        self.maths_win.title("📐 Maths Behind BBTP")
        self.maths_win.minsize(900, 650)
        width = self.winfo_width()
        self.maths_win.geometry(f"{width}x700")

        nav = ttk.Frame(self.maths_win)
        nav.pack(side="bottom", fill="x", padx=10, pady=5)
        ttk.Label(nav, text="Page 1 / 1").pack(side="left")
        ttk.Button(nav, text="◀ Prev", state="disabled").pack(side="left", padx=5)
        ttk.Button(nav, text="Next ▶", state="disabled").pack(side="left")
        self.hsb_maths = ttk.Scrollbar(nav, orient="horizontal", command=self.scroll_maths_y)
        self.hsb_maths.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(nav, text="↑", command=lambda: self.maths_tree.yview_scroll(-3, "units") if hasattr(self, "maths_tree") else None).pack(side="left")
        ttk.Button(nav, text="↓", command=lambda: self.maths_tree.yview_scroll(3, "units") if hasattr(self, "maths_tree") else None).pack(side="left")

        cols = ("Function", "Formula", "Live Example", "Extra Formula", "Notes")
        style = ttk.Style()
        style.configure("Treeview", rowheight=110)
        self.maths_tree = ttk.Treeview(self.maths_win, columns=cols, show="headings", height=28, style="Treeview")
        for col in cols:
            self.maths_tree.heading(col, text=col)
            self.maths_tree.column(col, width=220 if col != "Notes" else 340, anchor="w", stretch=True, minwidth=200)
        self.maths_tree.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        self.maths_tree.configure(yscrollcommand=self.set_maths_scroll)

        data = [
            ("Average Block Time", "avg_sec = (last_ts - first_ts) / (last_h - first_h)", f"avg_sec = {600} sec", "", "Used for all predictions"),
            ("Estimated Timestamp", "est_ts = last_ts + (target - current) * avg_sec", "est_ts = 1745000000", "", "Future block time"),
            ("Drift", "drift_days = (actual_time - ideal_time) / 86400", "Drift: +3.45 days", "ideal_time = GENESIS + height*600", "Positive = behind schedule"),
            ("BTD", "BTD = (t_hvb - t_hvb1) - (t_hvb1 - t_hvb2)", "BTD: 05:12", "Last diff: 09:45", "Short-term speed change"),
            ("Next Diff Adj", "blocks_until_adj = 2016 - (current % 2016)", "Next Diff Adj: 1234", "", "Blocks until next difficulty adjustment"),
            ("Est Hashrate", "est_hr = avg_hr * (1 + (target - current) * 0.0000235)", "Est Hashrate: 612.34 EH/s", "", "Linear growth estimate"),
            ("Est Price", "est_price = avg_price * (1 + (target - current) * 0.00002)", "Est Price: $82,548.19", "", "Linear growth estimate"),
            ("HR/Price", "hr_price = est_hr / est_price", "HR/Price: 0.00742", "", "Ratio of hashrate to price"),
            ("Est Tx", "est_tx = avg_tx * 1.015", "Est Tx: 3124", "", "Slight linear growth"),
            ("Est Nonce", "Est Nonce = averaged estimators", "Est Nonce: 1234567890", "", "Smart nonce blending"),
            ("Potential Winning Nonce", "PWN = Est Nonce + 1337", "PWN: 1234569227", "", "Lucky offset"),
            ("Predict Block", "est_ts = last_ts + (target - current) * avg_sec", "est_ts = 1745000000", "", "Full prediction using average block time"),
        ]

        for row in data:
            wrapped_row = list(row)
            wrapped_row[1] = self.advanced_math_wrap(wrapped_row[1], width=45)
            wrapped_row[2] = self.advanced_math_wrap(wrapped_row[2], width=38)
            wrapped_row[4] = self.advanced_math_wrap(wrapped_row[4], width=55)
            self.maths_tree.insert("", "end", values=tuple(wrapped_row))

    def open_notebook(self):
        if hasattr(self, "notebook_win") and self.notebook_win.winfo_exists():
            self.notebook_win.lift()
            return
        self.notebook_win = tk.Toplevel(self)
        self.notebook_win.title("📖 BTC Notebook – BBTP.crumbs")
        self.notebook_win.minsize(900, 650)
        width = self.winfo_width()
        self.notebook_win.geometry(f"{width}x780")

        nav = ttk.Frame(self.notebook_win)
        nav.pack(side="bottom", fill="x", padx=10, pady=5)
        self.page_label = ttk.Label(nav, text="Page 1 / ?")
        self.page_label.pack(side="left")
        ttk.Button(nav, text="◀ Prev", command=self.prev_page).pack(side="left", padx=5)
        ttk.Button(nav, text="Next ▶", command=self.next_page).pack(side="left")
        self.hsb_notebook = ttk.Scrollbar(nav, orient="horizontal", command=self.scroll_notebook_y)
        self.hsb_notebook.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(nav, text="↑", command=lambda: self.tree.yview_scroll(-3, "units") if hasattr(self, "tree") else None).pack(side="left")
        ttk.Button(nav, text="↓", command=lambda: self.tree.yview_scroll(3, "units") if hasattr(self, "tree") else None).pack(side="left")

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

        cols = ("Height", "Epoch Time", "Lead 0s", "Hash", "Size", "Tx", "Nonce", "Difficulty", "Hashrate (EH/s)", "Price (USD)")
        style = ttk.Style()
        style.configure("Treeview", rowheight=60)
        self.tree = ttk.Treeview(self.notebook_win, columns=cols, show="headings", height=24, style="Treeview")
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=110, anchor="center", stretch=True)
        self.tree.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        self.tree.configure(yscrollcommand=self.set_notebook_scroll)

        self.page_size = 50
        self.current_page = 0
        self.refresh_notebook_view()

    def open_predicts_notebook(self):
        if hasattr(self, "predicts_win") and self.predicts_win.winfo_exists():
            self.predicts_win.lift()
            return
        self.predicts_win = tk.Toplevel(self)
        self.predicts_win.title("📓 Predicts Notebook – predicts.block")
        self.predicts_win.minsize(900, 650)
        width = self.winfo_width()
        self.predicts_win.geometry(f"{width}x780")

        nav = ttk.Frame(self.predicts_win)
        nav.pack(side="bottom", fill="x", padx=10, pady=5)
        self.predict_page_label = ttk.Label(nav, text="Page 1 / ?")
        self.predict_page_label.pack(side="left")
        ttk.Button(nav, text="◀ Prev", command=self.prev_predict_page).pack(side="left", padx=5)
        ttk.Button(nav, text="Next ▶", command=self.next_predict_page).pack(side="left")
        self.hsb_predicts = ttk.Scrollbar(nav, orient="horizontal", command=self.scroll_predicts_y)
        self.hsb_predicts.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(nav, text="↑", command=lambda: self.predict_tree.yview_scroll(-3, "units") if hasattr(self, "predict_tree") else None).pack(side="left")
        ttk.Button(nav, text="↓", command=lambda: self.predict_tree.yview_scroll(3, "units") if hasattr(self, "predict_tree") else None).pack(side="left")

        top = ttk.Frame(self.predicts_win)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="Search:").pack(side="left")
        self.predict_search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.predict_search_var, width=35)
        search_entry.pack(side="left", padx=5)
        search_entry.bind("<KeyRelease>", lambda e: self.refresh_predicts_view())
        ttk.Button(top, text="Clear", command=self.clear_predicts_filters).pack(side="left", padx=5)

        cols = ("Target Block", "Predicted Time", "Delta Days", "Est Hashrate", "Est Price", "Est Tx", "Timestamp")
        style = ttk.Style()
        style.configure("Treeview", rowheight=60)
        self.predict_tree = ttk.Treeview(self.predicts_win, columns=cols, show="headings", height=24, style="Treeview")
        for col in cols:
            self.predict_tree.heading(col, text=col)
            self.predict_tree.column(col, width=140, anchor="center", stretch=True)
        self.predict_tree.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        self.predict_tree.configure(yscrollcommand=self.set_predicts_scroll)

        self.predict_page_size = 50
        self.predict_current_page = 0
        self.refresh_predicts_view()

    def open_livep_notebook(self):
        if hasattr(self, "livep_win") and self.livep_win.winfo_exists():
            self.livep_win.lift()
            return
        self.livep_win = tk.Toplevel(self)
        self.livep_win.title("📓 Live Predictions Notebook – LiveP.btc")
        self.livep_win.minsize(900, 650)
        width = self.winfo_width()
        self.livep_win.geometry(f"{width}x780")

        nav = ttk.Frame(self.livep_win)
        nav.pack(side="bottom", fill="x", padx=10, pady=5)
        self.livep_page_label = ttk.Label(nav, text="Page 1 / ?")
        self.livep_page_label.pack(side="left")
        ttk.Button(nav, text="◀ Prev", command=self.prev_livep_page).pack(side="left", padx=5)
        ttk.Button(nav, text="Next ▶", command=self.next_livep_page).pack(side="left")
        self.hsb_livep = ttk.Scrollbar(nav, orient="horizontal", command=self.scroll_livep_y)
        self.hsb_livep.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(nav, text="↑", command=lambda: self.livep_tree.yview_scroll(-3, "units") if hasattr(self, "livep_tree") else None).pack(side="left")
        ttk.Button(nav, text="↓", command=lambda: self.livep_tree.yview_scroll(3, "units") if hasattr(self, "livep_tree") else None).pack(side="left")

        top = ttk.Frame(self.livep_win)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="Search:").pack(side="left")
        self.livep_search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.livep_search_var, width=35)
        search_entry.pack(side="left", padx=5)
        search_entry.bind("<KeyRelease>", lambda e: self.refresh_livep_view())
        ttk.Button(top, text="Clear", command=self.clear_livep_filters).pack(side="left", padx=5)

        cols = ("Epoch Time", "Next Diff Adj", "Est Hashrate", "Est Price", "Est Tx", "Est Nonce", "PWN")
        style = ttk.Style()
        style.configure("Treeview", rowheight=60)
        self.livep_tree = ttk.Treeview(self.livep_win, columns=cols, show="headings", height=24, style="Treeview")
        for col in cols:
            self.livep_tree.heading(col, text=col)
            self.livep_tree.column(col, width=140, anchor="center", stretch=True)
        self.livep_tree.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        self.livep_tree.configure(yscrollcommand=self.set_livep_scroll)

        self.livep_page_size = 50
        self.livep_current_page = 0
        self.refresh_livep_view()

    def queue_update(self, message: str):
        if self.log_settings.get("debug_data", False):
            epoch = int(time.time())
            message = f"[{epoch}] {message}"
        self.update_queue.put(("log", message))
        if any(self.log_settings.get(k, False) for k in ["debug_data", "export_logs", "persistence_logs"]):
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
                        header = f"BBTP.log HEADER - Debug: {self.log_settings.get('debug_data')}, Export: {self.log_settings.get('export_logs')}, Persistence: {self.log_settings.get('persistence_logs')}\n"
                        f.write(header)
                    f.write(message + "\n")
            except:
                pass
        if hasattr(self, "log_area"):
            self.after(10, self.process_queue)
        else:
            print(message)

    def queue_progress(self, count: int, current: int, oldest: int, top: int):
        api = self.fetcher.last_api_used or "API"
        txt = f"{api} → Block(s) {count} fetched: Last Seen {current:,} | Oldest {oldest:,} | Top {top:,}"
        self.last_progress_text = txt
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

    def update_chain_progress(self):
        if not hasattr(self, "chain_progress_var"):
            return
        with self.cache_lock:
            cached_count = len(self.cache)
            tip = self.get_current_height() or max((int(h) for h in self.cache.keys()), default=0)
        if tip > 0:
            pct = (cached_count / tip) * 100
            self.chain_progress_var.set(min(100, pct))
            self.chain_tip_label.config(text=f"Tip: {tip:,} | Cached: {cached_count:,}/{tip:,} ({pct:.2f}%)")
        else:
            self.chain_progress_var.set(0)

    def build_curve_and_rate(self):
        self.queue_update("📈 Building full rate curve...")
        self.build_curve_thread()
        self.queue_update("📊 Calculating recent rate...")
        self.show_recent_rate()

    def build_curve_thread(self):
        if len(self.cache) < 3:
            self.queue_update("⚠️ Need at least 3 blocks!")
            return
        self.queue_update("📈 Building full rate curve...")
        curve_data = []
        with self.cache_lock:
            for h_str, block in sorted(self.cache.items(), key=lambda x: int(x[0])):
                h = int(h_str)
                actual = self._safe_timestamp(block["time"])
                ideal = GENESIS_TIMESTAMP + h * 600
                delta_days = (actual - ideal) / 86400.0
                curve_data.append({"height": h, "delta_days": round(delta_days, 4)})
        with open(BR_CURVE_FILE, "w", encoding="utf-8") as f:
            json.dump(curve_data, f, indent=2)
        with open(BRC_ARCH_FILE, "a", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "curve": curve_data}, f)
            f.write("\n")
        self.queue_update(f"✅ Curve saved to {BR_CURVE_FILE} + archived to {BRC_ARCH_FILE}")
        self.queue_update(f"📊 Recent average: {curve_data[-1]['delta_days'] if curve_data else 0:.2f} days drift")

    def predict_block(self):
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
            msg = f"✅ Block {target:,} mined: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            self.log_area.insert(tk.END, msg + "\n")
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
        msg = f"🚀 Prediction {target:,} → {est_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (Δ {delta_days:+.2f} days)"
        self.log_area.insert(tk.END, msg + "\n")
        self.log_area.see(tk.END)
        entry = {
            "target": target,
            "est_time_str": est_dt.strftime('%Y-%m-%d %H:%M:%S UTC'),
            "delta_days": round(delta_days, 2),
            "est_hr": round(sum(b.get("estimated_hashrate", 0) for b in self.cache.values() if "estimated_hashrate" in b) / len(self.cache), 4),
            "est_price": round(sum(b.get("price_usd", 0) for b in self.cache.values() if "price_usd" in b) / len(self.cache), 2),
            "est_tx": int(sum(b.get("tx_count", 0) for b in self.cache.values() if "tx_count" in b) / len(self.cache) * 1.015),
            "timestamp_str": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.predicts.append(entry)
        self.save_predicts()

    def show_recent_rate(self):
        if len(self.cache) < 3:
            self.queue_update("⚠️ Need at least 3 blocks!")
            return
        with self.cache_lock:
            all_heights = sorted(int(h) for h in self.cache.keys())
            use = all_heights[-2016:] if len(all_heights) > 2016 else all_heights
            t_start = self.cache[str(use[0])]["time"]
            t_end = self.cache[str(use[-1])]["time"]
            avg = (t_end - t_start) / (use[-1] - use[0]) if len(use) > 1 else 600
        msg = f"📊 Recent average: {avg:.2f} sec/block (using {len(use):,} blocks)"
        self.queue_update(msg)

    def update_status(self):
        n = len(self.cache)
        tip = self.get_current_height()
        if n > 0:
            with self.cache_lock:
                heights = [int(h) for h in self.cache.keys()]
                min_h = min(heights)
                max_h = max(heights)
                block = self.cache[str(max_h)]
                actual_ts = self._safe_timestamp(block.get("time"))
                ideal = GENESIS_TIMESTAMP + max_h * 600
                delta = (actual_ts - ideal) / 86400.0 if actual_ts > 0 else 0
                self.current_tip_height = max_h
                self.current_tip_nonce = block.get("nonce")
                hash_str = str(block.get("hash", ""))
                stripped = hash_str.lstrip("0")
                leading_zeros = len(hash_str) - len(stripped) if hash_str else 0
                epoch_ts = block.get("time", 0)
            self.status_cached.config(text=f"Cached Blocks: {n:,}")
            self.status_range.config(text=f"Cached: {min_h:,} – {max_h:,}")
            self.status_network.config(text=f"Network Tip: {max_h:,} / {tip:,}")
            self.status_drift.config(text=f"Drift: {delta:+.2f} days")
            self.tip_block_num.config(text=f"Block Number: {max_h:,}")
            self.tip_epoch.config(text=f"Epoch: {epoch_ts}")
            self.tip_price.config(text=f"Price: ${block.get('price_usd', 0):,.2f}")
            self.tip_hr.config(text=f"HR: {block.get('estimated_hashrate', 0):.4f} EH/s")
            self.tip_tx.config(text=f"Tx: {block.get('tx_count', 0):,}")
            self.tip_hr_price.config(text=f"HR/Price: {block.get('estimated_hashrate', 0) / block.get('price_usd', 1):.6f}")
            self.tip_nonce.config(text=f"Nonce: {self.current_tip_nonce}")
            self.tip_leading_zeros.config(text=f"Leading 0s: {leading_zeros}")
            self.tip_hash.config(text=f"Hash: {stripped}")
            self.drift_note.config(text=f"Drift Note: {'Behind' if delta > 0 else 'Ahead' if delta < 0 else 'On-Schedule'}")
            sorted_heights = sorted([int(h) for h in self.cache.keys()], reverse=True)
            if len(sorted_heights) >= 3:
                hvb = sorted_heights[0]
                hvb1 = sorted_heights[1]
                hvb2 = sorted_heights[2]
                t_hvb = self._safe_timestamp(self.cache[str(hvb)]["time"])
                t_hvb1 = self._safe_timestamp(self.cache[str(hvb1)]["time"])
                t_hvb2 = self._safe_timestamp(self.cache[str(hvb2)]["time"])
                diff1 = t_hvb - t_hvb1
                diff2 = t_hvb1 - t_hvb2
                btd_seconds = diff1 - diff2
                minutes = int(btd_seconds // 60)
                seconds = int(btd_seconds % 60)
                last_block_diff = t_hvb - t_hvb1
                ld_minutes = int(last_block_diff // 60)
                ld_seconds = int(last_block_diff % 60)
                self.last_drift.config(text=f"BTD: {minutes:02d}:{seconds:02d} :: LBD: {ld_minutes:02d}:{ld_seconds:02d}")
            else:
                self.last_drift.config(text="BTD: —")
        else:
            self.status_cached.config(text="Cached Blocks: 0")
            self.status_range.config(text="Cached: — – —")
            self.status_network.config(text=f"Network Tip: 0 / {tip:,}")
            self.status_drift.config(text="Drift: —")
            self.drift_note.config(text="Drift Note: —")
            self.last_drift.config(text="BTD: —")
        self.update_chain_progress()

    def periodic_new_block_checker(self):
        if time.time() - self.last_new_block_check >= 9 * 60:
            self.last_new_block_check = time.time()
            threading.Thread(target=self.check_and_fetch_new_blocks, daemon=True).start()
        self.after(540000, self.periodic_new_block_checker)

    def check_and_fetch_new_blocks(self):
        with self.cache_lock:
            cached_max = max((int(h) for h in self.cache.keys()), default=0)
        tip = self.get_current_height()
        if tip > cached_max + 5:
            self.queue_update(f"🕒 Periodic: {tip - cached_max} new blocks – enriching...")
            for h in range(cached_max + 1, tip + 1):
                self.get_full_block(h)
            self.queue_update("✅ New blocks added")
        self.update_chain_progress()

    def periodic_notebook_refresh(self):
        if not self.cooldown_active:
            self.after(60000, self.periodic_notebook_refresh)
            return
        time.sleep(60)
        self.after(60000, self.periodic_notebook_refresh)

    def open_data_settings(self):
        win = tk.Toplevel(self)
        win.title("⚙️ Data Settings")
        win.geometry("620x520")
        ttk.Label(win, text="Choose what data to collect and store", font=("Helvetica", 12, "bold")).pack(pady=10)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=20, pady=10)
        for key, default in self.data_settings.items():
            var = tk.BooleanVar(value=default)
            cb = ttk.Checkbutton(frame, text=key.replace("_", " ").title(), variable=var)
            cb.pack(anchor="center")
            setattr(self, f"data_var_{key}", var)
        ttk.Button(win, text="Save & Apply", command=lambda: self.save_data_settings(win)).pack(pady=10)
        ttk.Button(win, text="Re-scan & Clean Cache", command=self.apply_data_settings).pack(pady=5)

    def save_data_settings(self, win):
        for key in self.data_settings:
            self.data_settings[key] = getattr(self, f"data_var_{key}").get()
        self.save_all_settings()
        self.fetcher.data_settings = self.data_settings
        self.enricher.data_settings = self.data_settings
        win.destroy()
        self.queue_update("✅ Data settings saved and applied")

    def apply_data_settings(self):
        self.queue_update("🔄 Re-scanning and cleaning cache according to new data settings...")
        with self.cache_lock:
            for h_str, block in list(self.cache.items()):
                for k in list(block.keys()):
                    if not self.data_settings.get(k, True):
                        block.pop(k, None)
        self.save_cache(force=True)
        self.queue_update("✅ Cache cleaned according to new data settings")

    def open_api_settings(self):
        win = tk.Toplevel(self)
        win.title("⚙️ API Settings")
        win.geometry("620x520")
        ttk.Label(win, text="Enable / Disable APIs & view status", font=("Helvetica", 12, "bold")).pack(pady=10)
        for api_name in self.api_settings:
            flag = self.api_flags.get(api_name, {"status": "green", "cooldown_until": 0})
            status_emoji = {"green": "🟢", "orange": "🟠", "red": "🔴", "blue": "🔵", "yellow": "🟡"}.get(flag["status"], "⚪")
            cooldown_text = f" (cooldown {int(flag['cooldown_until'] - time.time())}s)" if flag["cooldown_until"] > time.time() else ""
            var = tk.BooleanVar(value=self.api_settings[api_name])
            cb = ttk.Checkbutton(win, text=f"{status_emoji} {api_name}{cooldown_text}", variable=var)
            cb.pack(anchor="center", padx=20)
            setattr(self, f"api_var_{api_name}", var)
        ttk.Button(win, text="Save", command=lambda: self.save_api_settings(win)).pack(pady=10)

    def save_api_settings(self, win):
        for api_name in self.api_settings:
            self.api_settings[api_name] = getattr(self, f"api_var_{api_name}").get()
        self.save_all_settings()
        win.destroy()
        self.queue_update("✅ API settings saved")

    def open_line_settings(self):
        win = tk.Toplevel(self)
        win.title("⚙️ Line / Mode Settings")
        win.geometry("700x500")
        ttk.Label(win, text="Online / Offline Mode", font=("Helvetica", 14, "bold")).pack(pady=10)
        mode_frame = ttk.Frame(win)
        mode_frame.pack(pady=10)
        self.mode_var = tk.BooleanVar(value=self.online_mode)
        ttk.Radiobutton(mode_frame, text="🌐 Online Mode", variable=self.mode_var, value=True).pack(side="left", padx=20)
        ttk.Radiobutton(mode_frame, text="📴 Offline Mode (Local Node)", variable=self.mode_var, value=False).pack(side="left", padx=20)
        ttk.Button(win, text="Save Mode", command=lambda: self.save_line_mode(win)).pack(pady=10)
        rpc_frame = ttk.LabelFrame(win, text="Offline Mode - Bitcoin Core / Knots RPC", padding=10)
        rpc_frame.pack(fill="x", padx=20, pady=10)
        ttk.Label(rpc_frame, text="RPC URL:").pack(anchor="w")
        self.rpc_url_var = tk.StringVar(value="http://127.0.0.1:8332")
        ttk.Entry(rpc_frame, textvariable=self.rpc_url_var, width=50).pack(fill="x")
        ttk.Label(rpc_frame, text="Username:").pack(anchor="w")
        self.rpc_user_var = tk.StringVar(value="bitcoin")
        ttk.Entry(rpc_frame, textvariable=self.rpc_user_var, width=50).pack(fill="x")
        ttk.Label(rpc_frame, text="Password:").pack(anchor="w")
        self.rpc_pass_var = tk.StringVar(value="")
        ttk.Entry(rpc_frame, textvariable=self.rpc_pass_var, width=50, show="*").pack(fill="x")
        ttk.Button(rpc_frame, text="Test Connection", command=self.test_rpc_connection).pack(pady=5)

    def save_line_mode(self, win):
        self.online_mode = self.mode_var.get()
        win.destroy()
        self.queue_update(f"✅ Mode set to {'Online' if self.online_mode else 'Offline'}")

    def test_rpc_connection(self):
        self.queue_update("🔄 Testing RPC connection (placeholder - configure your node credentials)...")

    def open_log_settings(self):
        win = tk.Toplevel(self)
        win.title("⚙️ L&R Settings")
        win.geometry("620x520")
        ttk.Label(win, text="Log & Results Settings", font=("Helvetica", 12, "bold")).pack(pady=10)
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=20, pady=10)
        for key, default in self.log_settings.items():
            var = tk.BooleanVar(value=default)
            cb = ttk.Checkbutton(frame, text=key.replace("_", " ").title(), variable=var)
            cb.pack(anchor="center")
            setattr(self, f"log_var_{key}", var)
        ttk.Button(win, text="Save", command=lambda: self.save_log_settings(win)).pack(pady=10)

    def save_log_settings(self, win):
        for key in self.log_settings:
            self.log_settings[key] = getattr(self, f"log_var_{key}").get()
        if self.log_settings["debug_data"] and not self.log_settings["export_logs"]:
            self.log_settings["export_logs"] = True
            self.queue_update("🔄 Auto-enabled Export Logs because Debug Data is on")
        if not self.log_settings["export_logs"] and self.log_settings["debug_data"]:
            self.log_settings["debug_data"] = False
            self.queue_update("🔄 Auto-disabled Debug Data because Export Logs was turned off")
        self.save_all_settings()
        win.destroy()
        self.queue_update("✅ Log & Results settings saved")

    def create_widgets(self):
        ttk.Label(self, text="🟠 BTC Block Time Predictor", font=("Helvetica", 18, "bold")).pack(pady=10)

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
        self.drift_note = ttk.Label(sf, text="Drift Note: —", anchor="center", foreground="#0066cc")
        self.drift_note.grid(row=2, column=0, sticky="ew", padx=10)
        self.last_drift = ttk.Label(sf, text="BTD: —", anchor="center")
        self.last_drift.grid(row=2, column=1, sticky="ew", padx=10)
        sf.columnconfigure(0, weight=1)
        sf.columnconfigure(1, weight=1)

        pf = ttk.LabelFrame(self, text="Live Fetch Progress", padding=8)
        pf.pack(fill="x", padx=15, pady=4)
        self.live_progress = ttk.Label(pf, text="→ Ready", foreground="#0066cc", font=("Consolas", 11), anchor="center")
        self.live_progress.pack(fill="x")

        chain_frame = ttk.LabelFrame(self, text="Chain Coverage", padding=8)
        chain_frame.pack(fill="x", padx=15, pady=4)
        self.chain_progress_var = tk.DoubleVar(value=0.0)
        self.chain_progress = ttk.Progressbar(chain_frame, orient="horizontal", mode="determinate", variable=self.chain_progress_var, style="info.Horizontal.TProgressbar")
        self.chain_progress.pack(fill="x", padx=5, pady=2)
        chain_labels = ttk.Frame(chain_frame)
        chain_labels.pack(fill="x", padx=5)
        ttk.Label(chain_labels, text="Block 0 (Genesis)", foreground="#666666").pack(side="left")
        self.chain_tip_label = ttk.Label(chain_labels, text="Tip: — | Cached: —", foreground="#0066cc")
        self.chain_tip_label.pack(side="right")

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
        ttk.Button(cf, text="📖 BTC Notebook", command=self.open_notebook).grid(row=1, column=0, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📖 Live Notebook", command=self.open_livep_notebook).grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📊 Build Curve & Rate", command=self.build_curve_and_rate).grid(row=1, column=2, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="📐 Maths", command=self.open_maths_window).grid(row=1, column=3, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="⚙️ Data", command=self.open_data_settings).grid(row=2, column=0, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="⚙️ API", command=self.open_api_settings).grid(row=2, column=1, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="⚙️ Line", command=self.open_line_settings).grid(row=2, column=2, padx=6, pady=4, sticky="ew")
        ttk.Button(cf, text="⚙️ L&R", command=self.open_log_settings).grid(row=2, column=3, padx=6, pady=4, sticky="ew")
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
        self.tip_price = ttk.Label(tip_frame, text="Price: —", anchor="w")
        self.tip_price.grid(row=0, column=2, padx=12, pady=4, sticky="w")
        self.tip_hr = ttk.Label(tip_frame, text="HR: —", anchor="w")
        self.tip_hr.grid(row=0, column=3, padx=12, pady=4, sticky="w")
        self.tip_tx = ttk.Label(tip_frame, text="Tx: —", anchor="w")
        self.tip_tx.grid(row=1, column=0, padx=12, pady=4, sticky="w")
        self.tip_hr_price = ttk.Label(tip_frame, text="HR/Price: —", anchor="w")
        self.tip_hr_price.grid(row=1, column=1, padx=12, pady=4, sticky="w")
        self.tip_nonce = ttk.Label(tip_frame, text="Nonce: —", anchor="w")
        self.tip_nonce.grid(row=1, column=2, padx=12, pady=4, sticky="w")
        self.tip_leading_zeros = ttk.Label(tip_frame, text="Leading 0s: —", anchor="w")
        self.tip_leading_zeros.grid(row=1, column=3, padx=12, pady=4, sticky="w")
        self.tip_hash = ttk.Label(tip_frame, text="Hash: —", anchor="w", wraplength=400)
        self.tip_hash.grid(row=2, column=0, columnspan=4, padx=12, pady=4, sticky="w")
        for i in range(4):
            tip_frame.columnconfigure(i, weight=1)

        pred_input_frame = ttk.LabelFrame(self, text="Predict Block", padding=10)
        pred_input_frame.pack(fill="x", padx=15, pady=8)
        inner = ttk.Frame(pred_input_frame)
        inner.pack(anchor="center", pady=4)
        ttk.Label(inner, text="Predict block:").pack(side="left")
        self.predict_entry = ttk.Entry(inner, width=14)
        self.predict_entry.pack(side="left", padx=6)
        self.predict_entry.insert(0, "1000000")
        ttk.Button(inner, text="🚀 Predict", command=self.predict_block).pack(side="left", padx=6)
        ttk.Button(inner, text="📓 Notebook", command=self.open_predicts_notebook).pack(side="left", padx=6)

        sync_frame = ttk.LabelFrame(self, text="Sync Progress", padding=8)
        sync_frame.pack(fill="x", padx=15, pady=4)
        self.sync_progress_var = tk.DoubleVar(value=0.0)
        self.sync_progress = ttk.Progressbar(sync_frame, orient="horizontal", mode="determinate", variable=self.sync_progress_var, style="info.Horizontal.TProgressbar")
        self.sync_progress.pack(fill="x", padx=5, pady=2)
        self.sync_progress_label = ttk.Label(sync_frame, text="✅ Idle – Ready for next operation", font=("Consolas", 9))
        self.sync_progress_label.pack(anchor="center")

        lf = ttk.LabelFrame(self, text="Log & Results", padding=8)
        lf.pack(fill="both", expand=True, padx=15, pady=8)
        self.log_area = scrolledtext.ScrolledText(lf, height=14, font=("Consolas", 10))
        self.log_area.pack(fill="both", expand=True)

        footer_text = f"Persistent file: {CACHE_FILE} | Chain file: {BTC_CHAIN_FILE} | Predicts: {PREDICTS_FILE} | LiveP: {LIVEP_FILE}"
        ttk.Label(self, text=footer_text, font=("Helvetica", 9), foreground="gray", anchor="center").pack(side="bottom", fill="x", pady=5)

        self.update_idletasks()

if __name__ == "__main__":
    app = BTCBlockPredictorGUI()
    app.mainloop()
