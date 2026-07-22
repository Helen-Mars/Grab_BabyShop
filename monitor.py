import re
import time
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from utils import get_logger

# 配置 logger
logger = get_logger(__name__)

LOAD_ERROR_TEXTS = (
    "There was a problem loading",
    "Try refreshing the page",
)

CLOUDFLARE_TEXTS = (
    "Verify you are human",
    "connection needs to be verified",
)


def _contains_any(text, patterns):
    normalized_text = (text or "").lower()
    return any(pattern.lower() in normalized_text for pattern in patterns)


def _get_page_snapshot_text(page):
    page_content = ""
    body_text = ""

    try:
        page_content = page.content()
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=1000)
    except Exception:
        pass

    return page_content, body_text


def monitor_and_auto_buy(page, product_url, check_interval=1, color_selection_enabled=False, target_color=None):
    """实时监控商品，有货就自动加入购物车（数量固定为1）

    Args:
        page: Playwright page 对象
        product_url: 商品链接
        check_interval: 检测间隔（秒），默认 5
    """
    logger.info("开始实时监控...")

    while True:
        try:
            response = page.goto(product_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)

            # ===== 优先识别页面错误 / Cloudflare / 真实 429 限流 =====
            page_content, body_text = _get_page_snapshot_text(page)
            snapshot_text = f"{page_content}\n{body_text}"
            response_status = response.status if response is not None else None
            if response_status == 429:
                logger.warning(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"⚠️ 检测到商品页被限流（status={response_status}），按检测间隔重试"
                )
                time.sleep(check_interval)
                continue

            # ===== 检测页面加载错误 =====
            if _contains_any(snapshot_text, LOAD_ERROR_TEXTS):
                logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 检测到页面加载错误，3秒后刷新重试")
                time.sleep(3)
                page.reload(wait_until="domcontentloaded")
                continue

            # ===== Cloudflare 检测 =====
            if _contains_any(body_text, CLOUDFLARE_TEXTS):
                logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 检测到 Cloudflare 验证")
                logger.info("请手动完成验证后按 Enter 继续...")
                input()
                continue


            # 有 "Sold out" 按钮 → 全部售罄
            if page.get_by_role("button", name="Sold out").count() > 0:
                logger.warning(f"[{time.strftime('%H:%M:%S')}] ❌ 商品已售罄")
                time.sleep(check_interval)
                continue

            # 有货
            
            # ===== 颜色选择功能（仅在启用时执行） =====
            if color_selection_enabled:
                # ===== 等待颜色选项加载 =====
                color_section = page.locator(
                    "variant-selects fieldset",
                    has=page.locator(
                        "legend",
                        has_text=re.compile(r"Color|色", re.IGNORECASE),
                    ),
                ).first
                
                color_inputs = color_section.locator('input[type="radio"]')
                
                try:
                    # 等待颜色选项加载
                    color_inputs.first.wait_for(
                        state="attached",
                        timeout=10000,
                    )
                except PlaywrightTimeoutError:
                    logger.warning(
                        f"[{time.strftime('%H:%M:%S')}] "
                        "⚠️ 商品页已打开，但颜色选项尚未加载完成"
                    )
                    time.sleep(check_interval)
                    continue
                
                # ===== 确定要匹配的颜色 =====
                search_color = target_color if target_color is not None else "ピンク|Pink"
                logger.info(f"[{time.strftime('%H:%M:%S')}] 正在查找颜色: {search_color}")
                
                # ===== 优先级 1: 精确匹配（颜色开头） =====
                primary_pattern = re.compile(
                    rf"^\s*(?:{search_color})(?:\s*[×xX/・-]|\s|$)",
                    re.IGNORECASE,
                )
                
                # ===== 优先级 2: 模糊匹配（包含颜色） =====
                fuzzy_pattern = re.compile(search_color, re.IGNORECASE)
                
                primary_match = None
                fuzzy_match = None
                
                for index in range(color_inputs.count()):
                    current_radio = color_inputs.nth(index)
                    color_value = (current_radio.get_attribute("value") or "").strip()
                    
                    # 优先匹配主选项
                    if primary_pattern.search(color_value):
                        primary_match = current_radio
                        logger.info(f"[{time.strftime('%H:%M:%S')}] 找到主匹配颜色: {color_value}")
                        break
                    
                    # 其次模糊匹配
                    if fuzzy_match is None and fuzzy_pattern.search(color_value):
                        fuzzy_match = current_radio
                        logger.info(f"[{time.strftime('%H:%M:%S')}] 找到模糊匹配颜色: {color_value}")
                
                selected_radio = primary_match if primary_match is not None else fuzzy_match
                
                if selected_radio is None:
                    available_colors = []
                    for index in range(color_inputs.count()):
                        value = color_inputs.nth(index).get_attribute("value")
                        if value:
                            available_colors.append(value.strip())
                    logger.error(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"❌ 未找到目标颜色选项，当前颜色：{available_colors}"
                    )
                    time.sleep(check_interval)
                    continue
                
                # ===== 判断颜色是否已售罄 =====
                selected_color = (selected_radio.get_attribute("value") or "").strip()
                
                if (
                    selected_radio.is_disabled()
                    or selected_radio.get_attribute("aria-disabled") == "true"
                    or "disabled" in (selected_radio.get_attribute("class") or "").split()
                ):
                    logger.warning(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"❌ 目标颜色已售罄：{selected_color}"
                    )
                    time.sleep(check_interval)
                    continue
                
                # ===== 点击对应的 label =====
                try:
                    radio_id = selected_radio.get_attribute("id")
                    if not radio_id:
                        raise RuntimeError("颜色 radio 缺少 id 属性")
                    
                    # 点击对应 label
                    if not selected_radio.is_checked():
                        color_label = page.locator(f'label[for="{radio_id}"]').first
                        color_label.wait_for(state="visible", timeout=3000)
                        color_label.click()
                    
                    # 或者直接通过 radio 选择
                    option_value_id = selected_radio.get_attribute("data-option-value-id")
                    if option_value_id:
                        fresh_radio = page.locator(
                            "variant-selects "
                            f'input[data-option-value-id="{option_value_id}"]'
                        ).first
                    else:
                        fresh_radio = page.locator(
                            f'input[id="{radio_id}"]'
                        ).first
                    
                    # 确认颜色已选中
                    color_selected = False
                    for _ in range(10):
                        if fresh_radio.count() > 0 and fresh_radio.is_checked():
                            color_selected = True
                            break
                        page.wait_for_timeout(100)
                    
                    if not color_selected:
                        logger.warning(
                            f"[{time.strftime('%H:%M:%S')}] "
                            f"❌ 颜色无法选择：{selected_color}"
                        )
                        time.sleep(check_interval)
                        continue
                    
                    logger.info(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"✅ 已选择颜色：{selected_color}"
                    )
                    page.wait_for_timeout(1000)  # 等待更久一点，让页面状态完全更新
                except Exception as e:
                    logger.error(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"❌ 颜色选择异常：{e}"
                    )
                    time.sleep(check_interval)
                    continue
                # ===== 颜色选择完成 =====
            else:
                logger.info(f"[{time.strftime('%H:%M:%S')}] 颜色选择功能未启用，使用页面默认选择")
            
            # 检查 Add to cart 按钮状态
            add_btn = page.get_by_role("button", name=re.compile(r"^Add to cart$", re.IGNORECASE))
            btn_count = add_btn.count()
            logger.info(f"[{time.strftime('%H:%M:%S')}] 找到 {btn_count} 个 'Add to cart' 按钮")
            
            if btn_count > 0:
                btn_enabled = add_btn.first.is_enabled()
                btn_visible = add_btn.first.is_visible()
                logger.info(f"[{time.strftime('%H:%M:%S')}] 按钮状态 - enabled: {btn_enabled}, visible: {btn_visible}")
            
            if add_btn.count() > 0 and add_btn.first.is_enabled() and add_btn.first.is_visible():
                logger.info(f"[{time.strftime('%H:%M:%S')}] 🎉 商品补货了！正在加入购物车...")

                # 方案4：先以数量1加入购物车，不设置数量（默认就是1）
                # 加入购物车
                add_btn.first.click()
                page.wait_for_timeout(1000)
                logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ 已成功加入购物车（数量1）")

                # 优先点击 View cart 按钮，或点击 Checkout
                view_cart_btn = page.get_by_role("link", name=re.compile(r"View cart", re.IGNORECASE))
                checkout_btn = page.get_by_role("button", name="Check out")
                if view_cart_btn.count() > 0:
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 找到 View cart 按钮，点击进入购物车")
                    view_cart_btn.first.click()
                    page.wait_for_timeout(1500)
                    current_url = page.url
                    logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ 已跳转到购物车页面: {current_url}")
                elif checkout_btn.count() > 0 and checkout_btn.first.is_enabled():
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 找到 Checkout 按钮，点击进入结算页面")
                    checkout_btn.first.click()
                    page.wait_for_timeout(1500)
                    current_url = page.url
                    logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ 已跳转到结算页面: {current_url}")
                else:
                    # 保底方案：直接跳转购物车
                    logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 没有找到合适按钮，直接跳转到购物车页面")
                    page.goto("https://store.babyssb.co.jp/en/cart", wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                
                # ===== 验证是否成功跳转到购物车或结算页面 =====
                current_url = page.url
                is_valid_page = "/cart" in current_url or "/checkout" in current_url or "shop.app/checkout" in current_url
                
                if not is_valid_page:
                    logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 当前不在购物车或结算页面，尝试直接跳转购物车")
                    page.goto("https://store.babyssb.co.jp/en/cart", wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                
                # 最终打印当前页面，确认衔接正确
                final_url = page.url
                logger.info(f"[{time.strftime('%H:%M:%S')}] 🎯 最终页面: {final_url}")
                logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ 准备进入购物车数量修改和结算流程")

                return True

            time.sleep(check_interval)
        except Exception as e:
            logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 监控异常: {e}")
            logger.info("   等待 3 秒后继续监控...")
            time.sleep(3)
            continue
