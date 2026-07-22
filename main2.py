from playwright.sync_api import sync_playwright
from login import login
from monitor import check_and_add_to_cart, monitor_and_auto_buy
from cart import monitor_cart, fill_checkout_info
from dotenv import load_dotenv
import os
import time
import threading


# 多账号配置

ACCOUNTS = [
    {"file": "state1.json", "email": "w17621251612@gmail.com"},
    {"file": "state2.json", "email": "haylenma001@gmail.com"},
]



load_dotenv()  # 从 .env 文件加载环境变量

CHECKOUT_CONFIG = {
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




def prepare_accounts(browser, accounts):
    """依次登录多个账号，生成各自的 state 文件"""
    successful = []
    i = 0

    while i < len(accounts):
        acc = accounts[i]
        print(f"\n=== ({i+1}/{len(accounts)}) 登录账号: {acc['email']} ===")
        try:
            context, page = login(browser, email=acc["email"], save_path=acc["file"])
            context.close()
            print(f"✅ {acc['email']} 登录完成，state 已保存到 {acc['file']}")
            successful.append(acc)
            i += 1  # 成功就跳到下一个
        except Exception as e:
            print(f"❌ {acc['email']} 登录失败: {e}")

            choice = input("按 1 重新当前账号，按 2 到下一个账号: ").strip()
            if choice == "1":
                continue  # 不增加 i，重新当前账号
            elif choice == "2":
                i += 1  # 跳过当前账号


    # 所有账号处理完毕，打印成功信息并暂停确认
    print("\n" + "=" * 50)
    print("✅ 登录成功的账号:")
    for acc in successful:
        print(f"   - {acc['email']} (state: {acc['file']})")
    print("=" * 50)
    input("\n按回车继续执行抢购流程...")


        # 如果有登录失败的，暂停让用户确认
    if len(successful) < len(accounts):
        choice = input("\n⚠️ 部分账号登录失败，按 1 继续执行，按 2 退出程序: ").strip()
        if choice == "2":
            print("程序退出")
            exit(0)
    else:
        print("\n所有账号登录成功，继续执行抢购流程...")

    return successful

account_result = {}

def run_account(account):
    """单个账号的完整流程"""
    state_file = account["file"]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],  # 反检测
        )
        
        # 加载登录态
        context = browser.new_context(storage_state=state_file)
        page = context.new_page()

        try:
            monitor_and_auto_buy(page, PRODUCT_URL2, quantity=10)
            monitor_cart(page)
            fill_checkout_info(page, CHECKOUT_CONFIG["payment"], CHECKOUT_CONFIG["resident_id"])
            account_result[account["email"]] = "✅ 抢购成功"
        except Exception as e:
            print(f"[{account['email']}] ❌ 异常: {e}")
            account_result[account["email"]] = "❌ 抢购失败"
        finally:
            browser.close()


if __name__ == "__main__":
    print("=== 多账号并发抢购 ===")

    # 先逐个登录，生成 state 文件
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        successful_accounts = prepare_accounts(browser, ACCOUNTS)
        
        browser.close()

    if not successful_accounts:
        print("❌ 没有成功登录的账号，程序退出")
        exit(1)

    # 然后多线程运行抢购流程
    threads = []
    for account in successful_accounts:
        t = threading.Thread(target=run_account, args=(account,))
        t.daemon = True  # 设为守护线程，主线程退出时自动结束
        t.start()
        threads.append(t)
        time.sleep(0.5)  # 错开启动，避免同时请求

    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=1)  # 每秒检查一次，不是死等
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断，正在退出...")

    print("=== 全部完成 ===")
    for email, result in account_result.items():
        print(f"{email}: {result}")