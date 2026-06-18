from pathlib import Path
import time
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# STATE_FILE = "state.json"
# EMAIL = "helen.mars250@gmail.com"
# EMAIL2 = "haylenma001@gmail.com"
URL = "https://store.babyssb.co.jp/en"


def safe_click(locator, retries=3, wait=1.5):
    for i in range(retries):
        try:
            locator.click(timeout=3000)
            return
        except PlaywrightTimeoutError:
            if i == retries - 1:
                raise
            time.sleep(wait)


def safe_fill(locator, text, retries=3, wait=1.5):
    for i in range(retries):
        try:
            locator.fill(text, timeout=3000)
            return
        except PlaywrightTimeoutError:
            if i == retries - 1:
                raise
            time.sleep(wait)


def login(browser, email=None, save_path="state.json"):

    """登录并保存 state 到指定文件

    Args:
        browser: Playwright browser 对象
        email: 用于登录的邮箱
        save_path: state 保存路径，如 "state1.json"
    """



    if Path(save_path).exists():
        context = browser.new_context(storage_state=save_path)
        page = context.new_page() 
        # page.goto(URL, wait_until="domcontentloaded")
        page.goto(
            "https://shopify.com/58599768157/account/orders",
            wait_until="domcontentloaded"
        )

        page.wait_for_timeout(3000)

        if "/account/orders" in page.url:
            print("✅ 登录状态有效")

            return context, page
        
        else:
            print("❌ state无效，需要重新登录")
            context.close()
            # 重新登录

    # 需要登录一次获取 state.json
    context = browser.new_context()

    page = context.new_page()

    page.goto(URL, wait_until="domcontentloaded")

    page.get_by_role(
        "link",
        name="Log in"
    ).click()


    choice = input("输入 1 或 2: ").strip()

    # 使用shopify登录会弹出一个新的窗口
    if choice == "1":
        with page.expect_popup() as popup_info:
            safe_click(
                page.get_by_role(
                    "button",
                    name="Continue with Shop"
                )
            )

        shop_page = popup_info.value

        email_input = shop_page.get_by_test_id(
            "IdentityEmailForm-email-input"
        )

        email_input.wait_for()

        safe_fill(email_input, email)
        time.sleep(0.5)

        print("邮箱内容:", email_input.input_value())
        print("当前URL:", shop_page.url)


        shop_page.get_by_role("button", name="Continue").click(timeout=15000)

        time.sleep(2)

        print("Continue 后 URL:", shop_page.url)
        print("Continue 后标题:", shop_page.title())
        # cloundflare 可能会在这个时候弹出 hCaptcha 验证



        # 手动完成 hCaptcha 验证
        input("请观察页面，确认邮箱提交后按回车...")

        print("=" * 60)
        print("请手动完成 hCaptcha")
        print("=" * 60)

        input("完成 hCaptcha 后按回车...")

        # 等待 OTP 按钮出现
        # 等待 OTP 按钮出现（兼容 Cloudflare + hCaptcha）
        while True:

            try:
                body_text = shop_page.locator("body").inner_text(timeout=3000)
            except:
                body_text = ""

            # Cloudflare 检测
            if (
                "Verify you are human" in body_text
                or "connection needs to be verified" in body_text
            ):
                print("\n⚠️ 检测到 Cloudflare 验证")
                print("请手动点击 Verify you are human")
                input("完成后按 Enter 继续检查...")
                continue

            # OTP 按钮检测
            try:
                btn = shop_page.get_by_role(
                    "button",
                    name="Email me code instead"
                )

                btn.wait_for(timeout=3000)

                print("✅ 找到 OTP 按钮")

                btn.click()

                print("✅ OTP 按钮点击成功")

                break

            except PlaywrightTimeoutError:

                print("\n⏳ OTP 按钮还没出现")
                print("当前 URL:", shop_page.url)

                action = input(
                    "完成验证后按 Enter 继续检查，输入 q 退出："
                )

                if action.lower() == "q":
                    browser.close()
                    return


        # 邮箱验证码输入
        otp_box = shop_page.get_by_role(
            "textbox",
            name="Confirm it’s you"
        )

        otp_box.wait_for(timeout=30000)

        otp = input("请输入邮箱验证码: ")

        otp_box.fill(otp)

        shop_page.keyboard.press("Enter")

        print("验证码已提交")

        input("如果页面已经显示登录成功，请按回车...")

        print("登录后URL:", shop_page.url)

        # 确认成功后再保存
        save = input("确认已经登录成功？(y/n): ")

        if save.lower() == "y":
            context.storage_state(path=save_path)
            print(f"✅ state 已保存到 {save_path}")
        else:
            print("❌ 未保存 state")



    # 直接使用邮箱登录（不弹新窗口）
    elif choice == "2":
        # ===== 直接邮箱登录（在当前页面）=====
        page.get_by_role("textbox", name="Email").click()
        page.get_by_role("textbox", name="Email").fill(email)
        page.get_by_role("button", name="Continue", exact=True).click()

        # 手动处理 Cloudflare 验证 + 输入验证码
        print("=" * 60)
        print("请在页面中手动完成：")
        print("1. Cloudflare 验证")
        print("2. 输入验证码并完成登录")
        print("完成后按 Enter 继续...")
        print("=" * 60)
        input()

                # ===== 新增：检测登录是否成功 =====
        page.wait_for_timeout(2000)
        body_text = page.locator("body").inner_text(timeout=5000)

        if "Couldn't sign you in" in body_text or "check your connection" in body_text:
            print("⚠️ 登录失败：验证码无效或链接过期")
            raise Exception("登录失败：验证码无效或链接过期")


        print("登录后URL:", page.url)

        # 确认成功后再保存
        save = input("确认已经登录成功？(y/n): ")

        if save.lower() == "y":
            context.storage_state(path=save_path)
            print(f"✅ state 已保存到 {save_path}")
        else:
            print("❌ 未保存 state")


        if context is None or page is None:
            raise Exception("登录失败")
        
    return context, page



