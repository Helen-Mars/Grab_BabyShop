#!/usr/bin/env python3
"""
调试脚本 - 用于手动测试和调试颜色选择逻辑
以非无头模式运行，方便观察页面操作
"""

from playwright.sync_api import sync_playwright
import re
import time

def debug_color_selection():
    """调试颜色选择功能"""
    with sync_playwright() as p:
        # 以非无头模式启动浏览器，方便观察
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(storage_state="state.json")
        page = context.new_page()
        
        # 导航到测试商品页面
        product_url = "https://store.babyssb.co.jp/en/products/B50OJ213"
        print(f"Navigating to: {product_url}")
        page.goto(product_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        
        print("\n===== 开始调试颜色选择 =====")
        
        # ===== 等待颜色选项加载 =====
        color_section = page.locator(
            "variant-selects fieldset",
            has=page.locator(
                "legend",
                has_text=re.compile(r"Color|色", re.IGNORECASE),
            ),
        ).first
        
        color_inputs = color_section.locator('input[type="radio"]')
        
        print(f"找到 {color_inputs.count()} 个颜色选项")
        
        # 列出所有可用颜色
        print("\n可用颜色：")
        available_colors = []
        for index in range(color_inputs.count()):
            current_radio = color_inputs.nth(index)
            color_value = (current_radio.get_attribute("value") or "").strip()
            is_disabled = current_radio.is_disabled() or "disabled" in (current_radio.get_attribute("class") or "")
            status = "❌ 已售罄" if is_disabled else "✅ 有货"
            print(f"  [{index+1}] {color_value} - {status}")
            available_colors.append(color_value)
        
        # ===== 查找粉色选项 =====
        primary_pink_pattern = re.compile(
            r"^\s*(?:ピンク|Pink)(?:\s*[×xX/・-]|\s|$)",
            re.IGNORECASE,
        )
        
        fuzzy_pink_pattern = re.compile(r"ピンク|Pink", re.IGNORECASE)
        
        primary_match = None
        fuzzy_match = None
        
        for index in range(color_inputs.count()):
            current_radio = color_inputs.nth(index)
            color_value = (current_radio.get_attribute("value") or "").strip()
            
            if primary_pink_pattern.search(color_value):
                primary_match = current_radio
                print(f"\n找到主匹配粉色: {color_value}")
                break
            
            if fuzzy_match is None and fuzzy_pink_pattern.search(color_value):
                fuzzy_match = current_radio
                print(f"\n找到模糊匹配粉色: {color_value}")
        
        pink_radio = primary_match if primary_match is not None else fuzzy_match
        
        if pink_radio is None:
            print("\n❌ 未找到任何粉色选项！")
        else:
            selected_color = (pink_radio.get_attribute("value") or "").strip()
            print(f"\n✅ 选择的颜色: {selected_color}")
            
            # 检查是否可用
            is_disabled = (
                pink_radio.is_disabled()
                or pink_radio.get_attribute("aria-disabled") == "true"
                or "disabled" in (pink_radio.get_attribute("class") or "").split()
            )
            
            if is_disabled:
                print(f"❌ 该颜色已售罄！")
            else:
                print(f"✅ 该颜色有货！")
                
                # 尝试点击
                try:
                    radio_id = pink_radio.get_attribute("id")
                    if radio_id:
                        pink_label = page.locator(f'label[for="{radio_id}"]').first
                        pink_label.click()
                        print(f"✅ 已点击选择该颜色")
                        page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"❌ 点击失败: {e}")
        
        print("\n===== 调试完成 =====")
        print("浏览器保持打开状态，你可以手动操作...")
        print("按 Ctrl+C 或关闭浏览器来结束")
        
        try:
            # 保持浏览器打开
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n正在关闭...")
        
        browser.close()

if __name__ == "__main__":
    debug_color_selection()
