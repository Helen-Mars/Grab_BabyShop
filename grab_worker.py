#!/usr/bin/env python3
"""
GrabBabyShop 抢购子进程入口
由 app.py 通过 subprocess 启动，负责执行独立的自动化抢购流程。
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from cart import fill_checkout_info
from monitor import monitor_and_auto_buy
from utils import get_logger, load_config, setup_logger

IS_FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"
CONFIG_PATH = BASE_DIR / "config.json"
PROFILE_DIR = (BASE_DIR / "pw_profile").resolve()

setup_logger()
logger = get_logger(__name__)


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


def _launch_grab_context(playwright):
    launch_kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=True,
        locale="en-US",
        timezone_id="Asia/Tokyo",
        viewport={"width": 1280, "height": 800},
    )
    try:
        return playwright.chromium.launch_persistent_context(
            channel="chrome",
            **launch_kwargs,
        )
    except Exception:
        return playwright.chromium.launch_persistent_context(**launch_kwargs)


def main() -> int:
    config = load_config(CONFIG_PATH)

    if not STATE_PATH.exists():
        logger.error("❌ 未找到 state.json，请先完成登录")
        return 1

    logger.info("🚀 抢购子进程已启动")
    logger.info(f"📦 目标商品: {config.product_url}")

    context = None
    with sync_playwright() as p:
        try:
            context = _launch_grab_context(p)
            page = context.pages[0] if context.pages else context.new_page()
            _apply_storage_state(context, page, STATE_PATH)

            page.goto("https://shopify.com/58599768157/account/orders", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            if "/account/orders" not in page.url:
                logger.error("❌ 当前浏览器会话未登录，请先在 GUI 中完成登录并更新 state.json")
                return 1

            page.goto("https://store.babyssb.co.jp/en", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            success = monitor_and_auto_buy(
                page,
                config.product_url,
                check_interval=config.check_interval,
                color_selection_enabled=config.color_selection_enabled,
                target_color=config.target_color,
            )

            if not success:
                logger.error("❌ 抢购流程未成功加入购物车")
                return 1

            logger.info("🎉 成功加入购物车，开始购物车数量修改和结算流程")

            card_info = {
                "card_number": config.card_number,
                "expiry": config.card_expiry,
                "cvv": config.card_cvv,
                "cardholder_name": config.cardholder_name,
            }

            checkout_success = fill_checkout_info(
                page,
                card_info,
                config.resident_id,
                target_quantity=config.target_quantity,
                auto_pay=config.auto_pay,
            )

            if not checkout_success:
                logger.error("❌ 结算信息填充失败")
                return 1

            if config.auto_pay:
                logger.info("✅ 抢购流程完成，已尝试自动支付")
            else:
                logger.info("✅ 抢购流程完成，未自动支付")
            return 0
        except Exception as e:
            logger.exception(f"❌ 抢购子进程异常退出: {e}")
            return 1
        finally:
            if context is not None:
                context.close()


if __name__ == "__main__":
    raise SystemExit(main())
