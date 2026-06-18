from playwright.sync_api import sync_playwright
from login import login
from monitor import check_and_add_to_cart, monitor_and_auto_buy
from cart import monitor_cart, fill_checkout_info
from dotenv import load_dotenv
import os
import time

EMAIL = "haylenma001@gmail.com"


load_dotenv()  # 从 .env 文件加载环境变量

CHECKOUT_CONFIG = {
    "shipping": {
        "email": os.getenv("EMAIL"),
        "first_name": os.getenv("FIRST_NAME"),
        "last_name": os.getenv("LAST_NAME"),
        "address": os.getenv("ADDRESS"),
        "city": os.getenv("CITY"),
        "province": os.getenv("PROVINCE"),
        "postal_code": os.getenv("POSTAL_CODE"),
        "phone": os.getenv("PHONE"),
    },
    "payment": {
        "card_number": os.getenv("CARD_NUMBER"),
        "expiry": os.getenv("CARD_EXPIRY"),
        "cvv": os.getenv("CARD_CVV"),
        "cardholder_name": os.getenv("CARD_NAME"),
    },
    "resident_id": os.getenv("RESIDENT_ID"),
}


PRODUCT_URL = "https://store.babyssb.co.jp/en/products/b50uk868"
PRODUCT_URL2 = "https://store.babyssb.co.jp/en/products/b50sc816"
PRODUCT_URL3 = "https://store.babyssb.co.jp/en/products/b50uk856"
CART_URL = "https://store.babyssb.co.jp/en/cart"




if __name__ == "__main__":
    with sync_playwright() as p:
        context, page = None, None
        for attempt in range(1,4):
            try:
                browser = p.chromium.launch(headless=False)
                context, page = login(browser, email=EMAIL, save_path="state.json")
                break  # 登录成功，跳出重试循环
            except Exception as e:
                print(f"⚠️ 第 {attempt} 次登录失败: {e}")
                if attempt < 3:
                    print("   等待 5 秒后重试...")
                    time.sleep(5)
                else:
                    print("❌ 登录失败，程序退出")
                    raise

        # browser = p.chromium.launch(headless=False)
        # context, page = login(browser)

        # 登录完成后，在这里写后续操作
        print(f"当前页面: {page.url}")
        print("✅ 登录完成，可以继续执行后续操作")

        # 登录完成。关闭有头浏览器
        context.close()
        browser.close()

        # 无头模式读取state.json，继续后续操作
        browser = p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled",  # 反检测
            "--no-sandbox",  # 沙箱模式可能会导致某些环境下无法正常运行，尤其是在 Linux 上
            "--disable-web-security",  # 可能需要禁用同源策略，视具体情况而定
        ])
        context = browser.new_context(storage_state="state.json",
                                      user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        page = context.new_page()

        # check_and_add_to_cart(page, PRODUCT_URL2,quantity=2)
        monitor_and_auto_buy(page, PRODUCT_URL2, quantity=2, check_interval=1)

        # 监测购物车并自动结账
        monitor_cart(page)

        # 自动填充结算信息（请根据实际情况修改 shipping_info、card_info 和 resident_id）
        fill_checkout_info(page, CHECKOUT_CONFIG["shipping"], CHECKOUT_CONFIG["payment"], CHECKOUT_CONFIG["resident_id"])

        input("按回车退出...")
        browser.close()
