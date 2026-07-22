import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from monitor import monitor_and_auto_buy
from cart import fill_checkout_info
import time
from utils import setup_logger, get_logger, load_config

setup_logger()
logger = get_logger(__name__)

CONFIG = load_config()
STATE_FILE = Path("state.json")
PROFILE_DIR = Path("pw_profile").resolve()


def _apply_storage_state(context, page, state_file: Path):
    if not state_file.exists():
        return

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"⚠️ 读取 state.json 失败：{e}")
        return

    cookies = data.get("cookies") or []
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception as e:
            logger.warning(f"⚠️ 写入 cookies 失败：{e}")

    origins = data.get("origins") or []
    for origin in origins:
        origin_url = origin.get("origin")
        local_storage = origin.get("localStorage") or []
        if not origin_url or not local_storage:
            continue

        try:
            page.goto(origin_url, wait_until="domcontentloaded")
            for item in local_storage:
                key = item.get("name")
                value = item.get("value")
                if key is None or value is None:
                    continue
                page.evaluate("(k, v) => localStorage.setItem(k, v)", key, value)
        except Exception:
            continue

if __name__ == "__main__":
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                locale="en-US",
                timezone_id="Asia/Tokyo",
                viewport={"width": 1280, "height": 800},
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                locale="en-US",
                timezone_id="Asia/Tokyo",
                viewport={"width": 1280, "height": 800},
            )

        page = context.pages[0] if context.pages else context.new_page()
        _apply_storage_state(context, page, STATE_FILE)

        page.goto("https://shopify.com/58599768157/account/orders", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if "/account/orders" in page.url:
            logger.info("✅ 登录状态有效")
        else:
            logger.warning("⚠️ 当前会话未登录或登录态无效，请在打开的浏览器中手动完成登录")
            input("完成登录后按 Enter 继续...")

        page.goto("https://store.babyssb.co.jp/en", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # 从配置文件读取并监控商品
        monitor_and_auto_buy(
            page, 
            CONFIG.product_url, 
            check_interval=CONFIG.check_interval,
            color_selection_enabled=CONFIG.color_selection_enabled,
            target_color=CONFIG.target_color
        )

        # 构建支付信息
        card_info = {
            "card_number": CONFIG.card_number,
            "expiry": CONFIG.card_expiry,
            "cvv": CONFIG.card_cvv,
            "cardholder_name": CONFIG.cardholder_name
        }

        # 自动填充结算信息
        fill_checkout_info(
            page, 
            card_info, 
            CONFIG.resident_id, 
            target_quantity=CONFIG.target_quantity,
            auto_pay=CONFIG.auto_pay
        )

        input("按回车退出...")
        context.close()

