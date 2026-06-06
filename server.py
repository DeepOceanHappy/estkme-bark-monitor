import json
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ESTKME_DATA_DIR", ROOT)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
INDEX_PATH = os.path.join(ROOT, "index.html")

DEFAULT_CONFIG = {
    "product_api": "https://api.estk.me/user/shop/products/1",
    "product_page": "https://store.estk.me/products/1",
    "variant_title": "ESTKme Max",
    "interval_seconds": 60,
    "bark_key": "",
    "bark_server": "https://api.day.app",
    "bark_sound": "glass",
    "notify_on_startup_if_available": True,
}

DEFAULT_STATE = {
    "last_snapshot": None,
    "last_error": None,
    "last_notified_at": None,
    "last_notify_reason": None,
    "last_check_started_at": None,
    "next_check_at": None,
    "logs": [],
}

ALLOWED_CONFIG_KEYS = set(DEFAULT_CONFIG.keys())

lock = threading.RLock()
wake_event = threading.Event()
config = {}
state = {}


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path, fallback):
    if not os.path.exists(path):
        return dict(fallback)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        merged = dict(fallback)
        if isinstance(data, dict):
            merged.update({k: data[k] for k in fallback.keys() if k in data})
        return merged
    except Exception:
        return dict(fallback)


def save_json(path, payload):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def add_log(level, message):
    entry = {"time": now_text(), "level": level, "message": message}
    with lock:
        state.setdefault("logs", [])
        state["logs"].insert(0, entry)
        del state["logs"][80:]
        save_json(STATE_PATH, state)


def normalize_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def env_bool(value):
    if value is None or value == "":
        return None
    return normalize_bool(value)


def apply_env_config(cfg):
    env_map = {
        "ESTKME_PRODUCT_API": "product_api",
        "ESTKME_PRODUCT_PAGE": "product_page",
        "ESTKME_VARIANT_TITLE": "variant_title",
        "ESTKME_INTERVAL_SECONDS": "interval_seconds",
        "BARK_KEY": "bark_key",
        "BARK_SERVER": "bark_server",
        "BARK_SOUND": "bark_sound",
    }
    for env_name, cfg_name in env_map.items():
        value = os.environ.get(env_name)
        if value is None or value == "":
            continue
        if cfg_name == "interval_seconds":
            value = normalize_int(value, DEFAULT_CONFIG["interval_seconds"], minimum=15, maximum=3600)
        cfg[cfg_name] = value

    startup_notify = env_bool(os.environ.get("ESTKME_NOTIFY_ON_STARTUP_IF_AVAILABLE"))
    if startup_notify is not None:
        cfg["notify_on_startup_if_available"] = startup_notify
    return cfg


def public_status():
    with lock:
        return {
            "config": dict(config),
            "state": dict(state),
            "server_time": now_text(),
        }


def http_json(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "estkme-bark-monitor/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def find_variant(product, wanted_title):
    items = product.get("items") or []
    wanted = (wanted_title or "").strip().lower()

    for item in items:
        if str(item.get("title", "")).strip().lower() == wanted:
            return item

    for item in items:
        if wanted and wanted in str(item.get("title", "")).strip().lower():
            return item

    if items:
        available = ", ".join(str(item.get("title", "")) for item in items)
        raise RuntimeError(f"没有找到规格 {wanted_title}，当前可见规格：{available}")

    raise RuntimeError("接口没有返回商品规格 items")


def format_presale_time(value):
    if not value:
        return "无"
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def fetch_snapshot(cfg):
    payload = http_json(cfg["product_api"])
    if payload.get("code") not in (0, "0", None):
        raise RuntimeError(f"接口返回异常：{payload.get('message') or payload.get('code')}")

    product = ((payload.get("data") or {}).get("product") or {})
    if not product:
        raise RuntimeError("接口没有返回 data.product")

    variant = find_variant(product, cfg["variant_title"])
    stock = normalize_int(variant.get("stock"), 0)
    status = normalize_int(variant.get("status"), 0)
    is_presale = normalize_bool(variant.get("is_presale"))
    purchasable = stock > 0 and status == 1 and not is_presale

    return {
        "ok": True,
        "product_id": product.get("id"),
        "product_title": product.get("title") or "",
        "variant_id": variant.get("id"),
        "variant_title": variant.get("title") or cfg["variant_title"],
        "price": str(variant.get("price") or ""),
        "stock": stock,
        "status": status,
        "is_presale": is_presale,
        "presale_time": format_presale_time(variant.get("presale_time")),
        "purchasable": purchasable,
        "checked_at": now_text(),
        "api": cfg["product_api"],
        "page": cfg["product_page"],
    }


def bark_root(cfg):
    key = str(cfg.get("bark_key") or "").strip()
    if not key:
        return ""
    if key.startswith("http://") or key.startswith("https://"):
        return key.rstrip("/")
    server = str(cfg.get("bark_server") or DEFAULT_CONFIG["bark_server"]).rstrip("/")
    return server + "/" + urllib.parse.quote(key, safe="")


def build_bark_body(snapshot, reason):
    return "\n".join(
        [
            f"商品系列：{snapshot['product_title']}",
            f"规格：{snapshot['variant_title']}",
            f"价格：{snapshot['price']}",
            f"库存：{snapshot['stock']}",
            f"状态：{snapshot['status']}",
            f"预售：{'是' if snapshot['is_presale'] else '否'}",
            f"预售时间：{snapshot['presale_time']}",
            f"提醒原因：{reason}",
            f"检测时间：{snapshot['checked_at']}",
            f"接口：{snapshot['api']}",
            f"页面：{snapshot['page']}",
        ]
    )


def send_bark(snapshot, reason):
    with lock:
        cfg = dict(config)
    root = bark_root(cfg)
    if not root:
        add_log("warn", "检测到可购买，但还没有填写 Bark Key，已跳过推送。")
        return False

    title = "ESTKme 上架提醒"
    body = build_bark_body(snapshot, reason)
    query = {"url": snapshot["page"], "group": "ESTKme"}
    if cfg.get("bark_sound"):
        query["sound"] = str(cfg["bark_sound"]).strip()
    url = (
        root
        + "/"
        + urllib.parse.quote(title, safe="")
        + "/"
        + urllib.parse.quote(body, safe="")
        + "?"
        + urllib.parse.urlencode(query)
    )

    request = urllib.request.Request(url, headers={"User-Agent": "estkme-bark-monitor/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()
    add_log("success", f"Bark 推送成功：{reason}")
    return True


def should_notify(previous, snapshot, manual=False):
    if not snapshot.get("purchasable"):
        return None

    previous_stock = 0
    previous_purchasable = False
    if isinstance(previous, dict):
        previous_stock = normalize_int(previous.get("stock"), 0)
        previous_purchasable = normalize_bool(previous.get("purchasable"))

    if previous is None and config.get("notify_on_startup_if_available"):
        return f"启动检测时商品可购买，库存为 {snapshot['stock']}"
    if not previous_purchasable and snapshot["purchasable"]:
        return f"商品从不可购买变为可购买，库存从 {previous_stock} 变为 {snapshot['stock']}"
    if previous_stock <= 0 < snapshot["stock"]:
        return f"库存从 {previous_stock} 变为 {snapshot['stock']}"
    if manual and previous is None:
        return f"手动检测到商品可购买，库存为 {snapshot['stock']}"
    return None


def check_once(manual=False):
    with lock:
        cfg = dict(config)
        previous = state.get("last_snapshot")
        state["last_check_started_at"] = now_text()
        save_json(STATE_PATH, state)

    try:
        snapshot = fetch_snapshot(cfg)
        reason = None
        with lock:
            reason = should_notify(previous, snapshot, manual=manual)
            state["last_snapshot"] = snapshot
            state["last_error"] = None
            save_json(STATE_PATH, state)

        if snapshot["purchasable"]:
            add_log("success", f"检测完成：{snapshot['variant_title']} 可购买，库存 {snapshot['stock']}。")
        else:
            add_log("info", f"检测完成：{snapshot['variant_title']} 暂不可购买，库存 {snapshot['stock']}。")

        if reason:
            send_bark(snapshot, reason)
            with lock:
                state["last_notified_at"] = now_text()
                state["last_notify_reason"] = reason
                save_json(STATE_PATH, state)
        return {"ok": True, "snapshot": snapshot, "notified": bool(reason), "reason": reason}
    except Exception as exc:
        message = str(exc)
        with lock:
            state["last_error"] = {
                "time": now_text(),
                "message": message,
                "trace": traceback.format_exc(limit=3),
            }
            save_json(STATE_PATH, state)
        add_log("error", f"检测失败：{message}")
        return {"ok": False, "error": message}


def test_bark():
    snapshot = {
        "product_title": "ESTKme P-series",
        "variant_title": config.get("variant_title", "ESTKme Max"),
        "price": "200.00",
        "stock": 1,
        "status": 1,
        "is_presale": False,
        "presale_time": "无",
        "checked_at": now_text(),
        "api": config.get("product_api"),
        "page": config.get("product_page"),
    }
    try:
        sent = send_bark(snapshot, "测试推送")
        return {"ok": sent}
    except Exception as exc:
        add_log("error", f"Bark 测试失败：{exc}")
        return {"ok": False, "error": str(exc)}


def update_config(payload):
    changed = {}
    with lock:
        for key, value in payload.items():
            if key not in ALLOWED_CONFIG_KEYS:
                continue
            if key == "interval_seconds":
                value = normalize_int(value, DEFAULT_CONFIG["interval_seconds"], minimum=15, maximum=3600)
            elif key == "notify_on_startup_if_available":
                value = normalize_bool(value)
            elif isinstance(value, str):
                value = value.strip()
            config[key] = value
            changed[key] = value
        save_json(CONFIG_PATH, config)
    wake_event.set()
    add_log("info", "配置已保存。")
    return changed


def monitor_loop():
    check_once(manual=False)
    while True:
        with lock:
            interval = normalize_int(config.get("interval_seconds"), 60, minimum=15, maximum=3600)
            state["next_check_at"] = datetime.fromtimestamp(time.time() + interval).strftime("%Y-%m-%d %H:%M:%S")
            save_json(STATE_PATH, state)

        woke = wake_event.wait(interval)
        wake_event.clear()
        if woke:
            continue
        check_once(manual=False)


def host_port_from_args():
    host = os.environ.get("ESTKME_HOST", "127.0.0.1")
    port = normalize_int(
        os.environ.get("ESTKME_PORT") or os.environ.get("PORT"),
        8765,
        minimum=1024,
        maximum=65535,
    )

    args = sys.argv[1:]
    if args:
        port = normalize_int(args[0], port, minimum=1024, maximum=65535)
    if len(args) >= 2:
        host = args[1]
    return host, port


class Handler(BaseHTTPRequestHandler):
    server_version = "ESTKmeBarkMonitor/1.0"

    def log_message(self, fmt, *args):
        return

    def send_payload(self, status, content_type, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_payload(status, "application/json; charset=utf-8", body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in {"/", "/index.html"}:
            with open(INDEX_PATH, "rb") as fh:
                self.send_payload(200, "text/html; charset=utf-8", fh.read())
            return
        if path == "/api/status":
            self.send_json(public_status())
            return
        self.send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/config":
                payload = self.read_json_body()
                changed = update_config(payload)
                self.send_json({"ok": True, "changed": changed, "status": public_status()})
                return
            if path == "/api/check":
                result = check_once(manual=True)
                self.send_json(result)
                return
            if path == "/api/test-bark":
                self.send_json(test_bark())
                return
            self.send_json({"ok": False, "error": "not found"}, status=404)
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "JSON 格式错误"}, status=400)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)


def main():
    global config, state
    os.makedirs(DATA_DIR, exist_ok=True)
    host, port = host_port_from_args()

    config = apply_env_config(load_json(CONFIG_PATH, DEFAULT_CONFIG))
    save_json(CONFIG_PATH, config)
    state = load_json(STATE_PATH, DEFAULT_STATE)
    save_json(STATE_PATH, state)

    add_log("info", "监控服务已启动。")
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()

    server = ThreadingHTTPServer((host, port), Handler)
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/"
    print(f"ESTKme Bark Monitor is running: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
