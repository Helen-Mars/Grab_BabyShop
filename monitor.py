import re
import time


def check_and_add_to_cart(page, product_url, quantity=1):
    """检测商品是否有货，有货则加入购物车（页面自动选择有货的颜色）

    Args:
        page: Playwright page 对象
        product_url: 商品链接
        quantity: 购买数量，默认 1
    """
    page.goto(product_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)

    # 有 "Sold out" 按钮 → 全部售罄
    if page.get_by_role("button", name="Sold out").count() > 0:
        print("❌ 商品已售罄")
        return False

    # 没有 "Sold out" 按钮 → 有货，页面已自动选中有货的颜色
    add_btn = page.get_by_role("button", name=re.compile(r"^Add to cart$", re.IGNORECASE))

    if add_btn.count() > 0 and add_btn.first.is_enabled() and add_btn.first.is_visible():
        print("✅ 商品有货")

        # 设置数量
        if quantity > 1:
            plus_btn = page.get_by_role("button", name=re.compile(r"increase quantity", re.IGNORECASE))
            if plus_btn.count() > 0:
                for _ in range(quantity - 1):
                    plus_btn.first.click()
                    page.wait_for_timeout(200)
                print(f"  已设置数量: {quantity}")

        # 加入购物车
        print("  正在加入购物车...")
        add_btn.first.click()
        page.wait_for_timeout(500)
        print("✅ 已加入购物车")
        return True

    print("⚠️ 无法确定商品状态")
    return False


def monitor_and_auto_buy(page, product_url, quantity=1, check_interval=1):
    """实时监控商品，有货就自动加入购物车

    Args:
        page: Playwright page 对象
        product_url: 商品链接
        quantity: 购买数量，默认 1
        check_interval: 检测间隔（秒），默认 5
    """
    print("开始实时监控...")

    while True:
        try:

            page.goto(product_url, wait_until="commit")
            page.wait_for_timeout(1000)

            # ===== Cloudflare 检测 =====
            body_text = page.locator("body").inner_text(timeout=1000)
            if "Verify you are human" in body_text or "connection needs to be verified" in body_text:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 检测到 Cloudflare 验证")
                print("请手动完成验证后按 Enter 继续...")
                input()
                continue


            # 有 "Sold out" 按钮 → 全部售罄
            if page.get_by_role("button", name="Sold out").count() > 0:
                print(f"[{time.strftime('%H:%M:%S')}] ❌ 商品已售罄")
                time.sleep(check_interval)
                continue

            # 有货
            add_btn = page.get_by_role("button", name=re.compile(r"^Add to cart$", re.IGNORECASE))
            if add_btn.count() > 0 and add_btn.first.is_enabled() and add_btn.first.is_visible():
                print(f"[{time.strftime('%H:%M:%S')}] 🎉 商品补货了！正在加入购物车...")

                # 设置数量
                if quantity > 1:
                    plus_btn = page.get_by_role("button", name=re.compile(r"increase quantity", re.IGNORECASE))
                    if plus_btn.count() > 0:
                        for _ in range(quantity - 1):
                            plus_btn.first.click()
                            page.wait_for_timeout(200)

                # 加入购物车
                add_btn.first.click()
                page.wait_for_timeout(500)
                print(f"[{time.strftime('%H:%M:%S')}] ✅ 已成功购买！")


                # # 验证是否真的加购成功
                # cart_page_url = "https://store.babyssb.co.jp/en/cart"
                # page.goto(cart_page_url, wait_until="commit")
                # page.wait_for_timeout(1000)
                # body = page.locator("body").inner_text()

                # if "Your cart is empty" in body:
                #     print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 加购失败，购物车为空，继续监测...")
                #     time.sleep(check_interval)
                #     continue

                # print(f"[{time.strftime('%H:%M:%S')}] ✅ 已成功购买！")


                return True

            time.sleep(check_interval)

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 监控异常: {e}")
            print("   等待 3 秒后继续监控...")
            time.sleep(3)
            continue

