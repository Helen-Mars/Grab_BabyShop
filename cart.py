import re
import time
from utils import get_logger

# 配置 logger
logger = get_logger(__name__)


class FieldFillError(ValueError):
    """单个结算字段在当前页面内多次重试后仍未成功填写。"""


def _normalize_field_value(value: str, mode: str) -> str:
    value = value or ""
    if mode == "digits":
        return re.sub(r"\D", "", value)
    if mode == "compact":
        return re.sub(r"\s+", "", value)
    return value.strip()


def _assert_field_filled(locator, expected: str, field_name: str, mode: str = "exact"):
    """轮询读取输入框当前值，并确认该字段已按预期填入。"""
    locator.wait_for(timeout=5000)
    normalized_expected = _normalize_field_value(expected, mode)
    deadline = time.monotonic() + 5
    last_actual = ""

    while time.monotonic() < deadline:
        actual = locator.input_value(timeout=5000)
        last_actual = actual
        normalized_actual = _normalize_field_value(actual, mode)
        if normalized_actual == normalized_expected:
            logger.info(f"✅ 已确认{field_name}填写完成")
            return
        time.sleep(0.2)

    if not _normalize_field_value(last_actual, mode):
        raise ValueError(f"{field_name} 为空，可能未填写成功")

    raise ValueError(
        f"{field_name} 校验失败，期望: {expected}，实际: {last_actual}"
    )


def _clear_and_type(page, locator, value: str, delay: int = 50):
    locator.click()
    page.wait_for_timeout(300)
    page.keyboard.press("Control+a")
    page.wait_for_timeout(100)
    page.keyboard.press("Delete")
    page.wait_for_timeout(100)
    page.keyboard.type(value, delay=delay)
    page.wait_for_timeout(300)


def _fill_field_with_retry(page, locator, value: str, field_name: str, mode: str = "exact", delay: int = 50, retries: int = 3):
    last_error = None

    for field_attempt in range(1, retries + 1):
        try:
            _clear_and_type(page, locator, value, delay=delay)
            _assert_field_filled(locator, value, field_name, mode=mode)
            return
        except Exception as e:
            last_error = e
            logger.warning(
                f"⚠️ {field_name} 第 {field_attempt}/{retries} 次填写失败: {e}"
            )
            if field_attempt < retries:
                page.wait_for_timeout(500)

    raise FieldFillError(f"{field_name} 连续 {retries} 次填写失败: {last_error}")


def _wait_for_payment_fields_ready(page):
    """在首次填写卡号前，等待支付 iframe 和输入框真正稳定。"""
    card_iframe = page.locator('iframe[name*="card-fields-number"]').first
    card_iframe.wait_for(state="visible", timeout=10000)

    frame = page.frame_locator('iframe[name*="card-fields-number"]')
    card_number_input = frame.get_by_role("textbox", name="Card number")
    card_number_input.wait_for(timeout=10000)

    # 首次进入支付页时，Shopify 的卡号 iframe 常会先可见、后可输入。
    # 这里给它一个短暂的稳定时间，降低第一次输入被吞掉的概率。
    card_number_input.click()
    page.wait_for_timeout(800)


def monitor_cart(page, check_interval=1):
    """监测购物车，有商品就点击 Checkout 到支付页面，空就继续监测

    Args:
        page: Playwright page 对象
        check_interval: 检测间隔（秒），默认 5
    """
    logger.info("开始监测购物车...")

    while True:
        try:
            page.goto("https://store.babyssb.co.jp/en/cart", wait_until="commit")
            page.wait_for_timeout(1000)

            body = page.locator("body").inner_text()


            # 第一次检测为空，reload 再确认一次（防止时序问题）
            if "Your cart is empty" in body:
                page.reload(wait_until="commit")
                page.wait_for_timeout(1000)
                body = page.locator("body").inner_text()


            # 购物车有商品时，"Your cart is empty" 不会出现，且有 "Check out" 按钮
            if "Your cart is empty" not in body:
                page.goto("https://store.babyssb.co.jp/en/cart/checkout", wait_until="commit")
                page.wait_for_timeout(1000)
                if "/checkouts/" in page.url or "shop.app/checkout/" in page.url:
                    logger.info("成功获取到支付页面链接，正在跳转...")
                    logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ 已到达支付页面: {page.url}")
                    return True
                
                # 有时候直接跳转到 checkout 页面可能失败，这时尝试点击 Checkout 按钮

                checkout_btn = page.get_by_role("button", name=re.compile(r"^Check out$", re.IGNORECASE))
                if checkout_btn.count() > 0 and checkout_btn.first.is_enabled():
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 发现 Checkout 按钮，正在点击...")
                    checkout_btn.first.click()
                    page.wait_for_timeout(1000)
                    logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ 已到达支付页面: {page.url}")
                    return True

            logger.warning(f"[{time.strftime('%H:%M:%S')}] ❌ 购物车为空，继续监测...")
            time.sleep(check_interval)
        except Exception as e:
            logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 监测购物车异常: {e}")
            logger.info("   等待 3 秒后继续监测...")
            time.sleep(3)
            continue

       
def fill_checkout_info(page, card_info, resident_id, target_quantity=1, auto_pay=False):
    """自动填充结算页面的地址、信用卡、身份信息（失败自动重试）

    Args:
        target_quantity: 目标购买数量，如果在购物车页面会修改数量到此值
        auto_pay: 是否自动点击 Pay now 完成支付（默认False，仅填充信息）
    """
    logger.info("开始购物车数量修改和结算流程...")
    
    max_retries = 10
    retry_delay = 3
    quantity_adjusted = target_quantity <= 1
    
    for attempt in range(1, max_retries + 1):
        logger.info(f"\n--- 第 {attempt}/{max_retries} 次尝试填充 ---")

        try:
            page.wait_for_timeout(1000)
            
            current_url = page.url
            logger.info(f"[{time.strftime('%H:%M:%S')}] 当前URL: {current_url}")
            
            if target_quantity > 1 and not quantity_adjusted and attempt == 1:
                is_in_checkout = "/checkout" in current_url or "shop.app/checkout" in current_url
                if is_in_checkout:
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 当前在结算页面且尚未调整数量，跳回购物车修改数量")
                    page.goto("https://store.babyssb.co.jp/en/cart", wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    current_url = page.url
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 跳转后URL: {current_url}")
            
            # ===== 1. 检查是否在购物车页面，修改数量 =====
            
            if "/cart" in current_url and "checkout" not in current_url:
                logger.info(f"[{time.strftime('%H:%M:%S')}] 检测到在购物车页面，尝试修改数量到 {target_quantity}")
                
                # 优先按购物车按钮的 aria-label 精确定位，避免匹配到不可点击的加号元素
                plus_btn = page.locator('button[aria-label*="Increase quantity for"]').first
                if plus_btn.count() == 0:
                    plus_btn = page.get_by_role(
                        "button",
                        name=re.compile(r"^Increase quantity for", re.IGNORECASE),
                    ).first
                quantity_input = page.get_by_role("textbox", name=re.compile(r"quantity", re.IGNORECASE))
                
                # 先尝试获取当前数量
                current_qty = 1
                if quantity_input.count() > 0:
                    try:
                        current_qty = int(quantity_input.first.input_value() or "1")
                        logger.info(f"[{time.strftime('%H:%M:%S')}] 当前数量: {current_qty}")
                    except:
                        pass
                
                # 如果需要增加数量
                if target_quantity > current_qty and plus_btn.count() > 0:
                    clicks_needed = target_quantity - current_qty
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 需要点击 {clicks_needed} 次增加按钮")
                    
                    for i in range(clicks_needed):
                        try:
                            # 记录点击前的数量
                            before_qty = current_qty
                            plus_btn.wait_for(state="visible", timeout=5000)
                            plus_btn.scroll_into_view_if_needed()
                            plus_btn.first.click()
                            page.wait_for_timeout(800)  # 给页面足够时间自动回退数量
                            logger.info(f"[{time.strftime('%H:%M:%S')}] 第 {i+1} 次点击")
                            
                            # ===== 重新读取当前数量 =====
                            if quantity_input.count() > 0:
                                try:
                                    current_qty = int(quantity_input.first.input_value() or "1")
                                    logger.info(f"[{time.strftime('%H:%M:%S')}] 当前数量: {current_qty}")
                                except:
                                    pass
                            
                            # ===== 关键逻辑：如果数量没有增加，说明达到库存上限了 =====
                            if current_qty <= before_qty:
                                logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 数量未增加，已达到库存上限，停止继续")
                                break
                            
                            # ===== 也检查一下库存提示文本作为双重保险 =====
                            out_of_stock_text = page.get_by_text(re.compile(r"Only \d+ item was added to your|insufficient stock|out of stock", re.IGNORECASE))
                            if out_of_stock_text.is_visible():
                                logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 检测到库存不足提示")
                                break
                        except Exception as e:
                            logger.warning(f"[{time.strftime('%H:%M:%S')}] 点击增加按钮失败: {e}")
                            break
                elif target_quantity > current_qty:
                    logger.warning(f"[{time.strftime('%H:%M:%S')}] ⚠️ 未找到可用的增加数量按钮")
                
                quantity_adjusted = True
                
                # 然后点击 Checkout 按钮
                checkout_btn = page.get_by_role("button", name=re.compile(r"^Check out$", re.IGNORECASE))
                if checkout_btn.count() > 0 and checkout_btn.first.is_enabled():
                    logger.info(f"[{time.strftime('%H:%M:%S')}] 点击 Checkout 按钮")
                    checkout_btn.first.click()
                    
                    # ===== 点击 Checkout 后，短轮询检测弹窗，并优先判断是否已到支付页面 =====
                    continue_btn = page.get_by_role("button", name=re.compile(r"Continue checkout", re.IGNORECASE))
                    popup_handled = False
                    payment_page_ready = False
                    
                    for _ in range(8):  # 最多短轮询约 2.4 秒，避免无谓卡住
                        page.wait_for_timeout(300)
                        current_url = page.url
                        
                        if "/checkouts/" in current_url or "shop.app/checkout/" in current_url:
                            logger.info(f"[{time.strftime('%H:%M:%S')}] 已进入支付页面，无需等待数量更新弹窗")
                            payment_page_ready = True
                            break
                        
                        if page.locator('iframe[name*="card-fields-number"]').count() > 0:
                            logger.info(f"[{time.strftime('%H:%M:%S')}] 检测到支付页面卡号 iframe，准备填写支付信息")
                            payment_page_ready = True
                            break
                        
                        if continue_btn.count() > 0 and continue_btn.first.is_visible():
                            logger.info(f"[{time.strftime('%H:%M:%S')}] 检测到 Continue checkout 按钮，点击它")
                            continue_btn.first.click()
                            logger.info(f"[{time.strftime('%H:%M:%S')}] Continue checkout 已点击，等待页面跳转...")
                            page.wait_for_timeout(1000)
                            popup_handled = True
                            break
                    
                    if not popup_handled and not payment_page_ready:
                        logger.info(f"[{time.strftime('%H:%M:%S')}] 短轮询内未检测到数量更新弹窗，继续检查支付页元素")

            # ===== 3. 填写信用卡信息（在 iframe 中）=====
            _wait_for_payment_fields_ready(page)

            # 卡号
            frame = page.frame_locator('iframe[name*="card-fields-number"]')
            card_number_input = frame.get_by_role("textbox", name="Card number")
            _fill_field_with_retry(page, card_number_input, card_info["card_number"], "卡号", mode="digits", delay=50)

            # 有效期
            frame = page.frame_locator('iframe[name*="card-fields-expiry"]')
            expiry_input = frame.get_by_role("textbox", name=re.compile(r"Expiration date", re.I))
            _fill_field_with_retry(page, expiry_input, card_info["expiry"], "有效期", mode="compact", delay=50)

            # 安全码
            frame = page.frame_locator('iframe[name*="card-fields-verification_value"]')
            cvv_input = frame.get_by_role("textbox", name="Security code")
            _fill_field_with_retry(page, cvv_input, card_info["cvv"], "安全码", mode="digits", delay=50)

            # 持卡人姓名
            frame = page.frame_locator('iframe[name*="card-fields-name"]')
            cardholder_name_input = frame.get_by_role("textbox", name="Name on card")
            _fill_field_with_retry(page, cardholder_name_input, card_info["cardholder_name"], "持卡人姓名", delay=50)

            page.wait_for_timeout(1000)
            logger.info("✅ 信用卡信息已全部填写并确认完成")

            # ===== 4. 填写 Resident ID =====
            resident_id_input = page.get_by_role("textbox", name="Resident ID number")
            _fill_field_with_retry(page, resident_id_input, resident_id, "Resident ID", delay=50)

            page.wait_for_timeout(1000)

            # ===== 5. 点击 Pay now（默认关闭，需手动开启） =====
            if auto_pay:
                pay_btn = page.get_by_role("button", name="Pay now")
                if pay_btn.count() > 0 and pay_btn.first.is_enabled():
                    pay_btn.first.click()
                    logger.info("✅ 已点击 Pay now，完成支付")
                    return True
                else:
                    logger.warning("⚠️ 未找到可用的 Pay now 按钮")

            logger.info("✅ 结算信息填充完成（未自动支付）")
            return True

        except FieldFillError as e:
            logger.warning(f"⚠️ 第 {attempt} 次填充失败: {e}")
            if attempt < max_retries:
                logger.info(f"   保持当前页面，等待 {retry_delay} 秒后继续重试...")
                time.sleep(retry_delay)
                continue
            logger.error(f"❌ 已重试 {max_retries} 次，填充失败")
            return False
        except Exception as e:
            logger.warning(f"⚠️ 第 {attempt} 次填充失败: {e}")
            if attempt < max_retries:
                logger.info(f"   等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
                # 尝试刷新页面重新开始
                try:
                    page.reload(wait_until="domcontentloaded")
                except:
                    pass
            else:
                logger.error(f"❌ 已重试 {max_retries} 次，填充失败")
                return False



