import re
import time


def monitor_cart(page, check_interval=1):
    """监测购物车，有商品就点击 Checkout 到支付页面，空就继续监测

    Args:
        page: Playwright page 对象
        check_interval: 检测间隔（秒），默认 5
    """
    print("开始监测购物车...")

    while True:
        try:
            page.goto("https://store.babyssb.co.jp/en/cart", wait_until="commit")
            page.wait_for_timeout(1000)

            body = page.locator("body").inner_text()

            # 购物车有商品时，"Your cart is empty" 不会出现，且有 "Check out" 按钮
            if "Your cart is empty" not in body:
                page.goto("https://store.babyssb.co.jp/en/cart/checkout", wait_until="commit")
                page.wait_for_timeout(1000)
                if "/checkouts/" in page.url or "shop.app/checkout/" in page.url:
                    print("成功获取到支付页面链接，正在跳转...")
                    print(f"[{time.strftime('%H:%M:%S')}] ✅ 已到达支付页面: {page.url}")
                    return True
                
                # 有时候直接跳转到 checkout 页面可能失败，这时尝试点击 Checkout 按钮

                checkout_btn = page.get_by_role("button", name=re.compile(r"^Check out$", re.IGNORECASE))
                if checkout_btn.count() > 0 and checkout_btn.first.is_enabled():
                    print(f"[{time.strftime('%H:%M:%S')}] 发现 Checkout 按钮，正在点击...")
                    checkout_btn.first.click()
                    page.wait_for_timeout(1000)
                    print(f"[{time.strftime('%H:%M:%S')}] ✅ 已到达支付页面: {page.url}")
                    return True

            print(f"[{time.strftime('%H:%M:%S')}] ❌ 购物车为空，继续监测...")
            time.sleep(check_interval)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 监测购物车异常: {e}")
            print("   等待 3 秒后继续监测...")
            time.sleep(3)
            continue


        
def fill_checkout_info(page, shipping_info, card_info, resident_id):
    """自动填充结算页面的地址、信用卡、身份信息（失败自动重试）"""
    print("开始填充结算信息...")
    
    max_retries = 10
    retry_delay = 3

    for attempt in range(1, max_retries + 1):
        print(f"\n--- 第 {attempt}/{max_retries} 次尝试填充 ---")

        try:
            page.wait_for_timeout(1000)

            # ===== 1. 选择国家/地区 =====
            all_selects = page.locator("select")
            for i in range(all_selects.count()):
                options = all_selects.nth(i).locator("option")
                for j in range(options.count()):
                    opt_text = options.nth(j).inner_text()
                    if "China" in opt_text or "中国" in opt_text:
                        all_selects.nth(i).select_option(index=j)
                        print(f"✅ 已选择国家: {opt_text}")
                        break
                else:
                    continue
                break

            page.wait_for_timeout(500)

            # ===== 2. 填写收货地址 =====
            page.get_by_role("textbox", name="First name").fill(shipping_info["first_name"])
            page.get_by_role("textbox", name="Last name").fill(shipping_info["last_name"])
            page.get_by_role("textbox", name="Address").fill(shipping_info["address"])
            page.get_by_role("textbox", name="City").fill(shipping_info["city"])

            # 选择省份
            province_selects = page.locator("select")
            for i in range(province_selects.count()):
                options = province_selects.nth(i).locator("option")
                for j in range(options.count()):
                    opt_text = options.nth(j).inner_text()
                    if "JS" in opt_text or "江苏" in opt_text or "Jiangsu" in opt_text:
                        province_selects.nth(i).select_option(index=j)
                        print(f"✅ 已选择省份: {opt_text}")
                        break

            page.get_by_role("textbox", name="Postal code").fill(shipping_info["postal_code"])
            page.get_by_role("textbox", name="Phone").fill(shipping_info["phone"])
            print("✅ 已填写收货地址")

            page.wait_for_timeout(500)

            # ===== 3. 填写信用卡信息（在 iframe 中）=====
            card_number_frame = page.locator('iframe[name*="card-fields-number"]')
            if card_number_frame.count() > 0:
                card_number_frame.content_frame.get_by_role("textbox", name="Card number").fill(card_info["card_number"])
                print("✅ 已填写卡号")

            expiry_frame = page.locator('iframe[name*="card-fields-expiry"]')
            if expiry_frame.count() > 0:
                expiry_frame.content_frame.get_by_role("textbox", name=re.compile(r"Expiration date", re.I)).fill(card_info["expiry"])
                print("✅ 已填写有效期")

            cvv_frame = page.locator('iframe[name*="card-fields-verification_value"]')
            if cvv_frame.count() > 0:
                cvv_frame.content_frame.get_by_role("textbox", name="Security code").fill(card_info["cvv"])
                print("✅ 已填写安全码")

            name_frame = page.locator('iframe[name*="card-fields-name"]')
            if name_frame.count() > 0:
                name_frame.content_frame.get_by_role("textbox", name="Name on card").fill(card_info["cardholder_name"])
                print("✅ 已填写持卡人姓名")

            page.wait_for_timeout(1000)

            # ===== 4. 填写 Resident ID =====
            page.get_by_role("textbox", name="Resident ID number").fill(resident_id)
            print("✅ 已填写 Resident ID")

            page.wait_for_timeout(1000)

            # ===== 5. 点击 Pay now =====
            # 注释掉，避免真实支付。需要时取消注释
            # pay_btn = page.get_by_role("button", name="Pay now")
            # if pay_btn.count() > 0 and pay_btn.first.is_enabled():
            #     pay_btn.first.click()
            #     print("✅ 已点击 Pay now")
            #     return True

            print("✅ 结算信息填充完成")
            return True

        except Exception as e:
            print(f"⚠️ 第 {attempt} 次填充失败: {e}")
            if attempt < max_retries:
                print(f"   等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
                # 尝试刷新页面重新开始
                try:
                    page.reload(wait_until="domcontentloaded")
                except:
                    pass
            else:
                print(f"❌ 已重试 {max_retries} 次，填充失败")
                return False



