#!/usr/bin/env python3
"""
GrabBabyShop - 图形界面版本
使用 NiceGUI 构建的自动化抢购工具
"""

import sys

WORKER_ARG = "--worker"

if WORKER_ARG in sys.argv:
    from grab_worker import main as worker_main

    raise SystemExit(worker_main())

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from nicegui import core, ui
from playwright.sync_api import sync_playwright

from utils import load_config, save_config

# 全局状态
IS_FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
APP_ENTRY = Path(sys.executable).resolve() if IS_FROZEN else Path(__file__).resolve()
STATE_PATH = BASE_DIR / "state.json"
TEMP_STATE_PATH = BASE_DIR / "state.pending.json"
PROFILE_DIR = (BASE_DIR / "pw_profile").resolve()
HELP_DOC_PATH = BASE_DIR / "help_doc.md"
LOGIN_START_URL = "https://store.babyssb.co.jp/en"
LOGIN_CHECK_URL = "https://shopify.com/58599768157/account/orders"
PRODUCT_URL_PREFIX = "https://store.babyssb.co.jp/en/products/"
_STDIO_FALLBACK_STREAMS = []

is_running = False
log_display = None
log_rendered_count = 0
grab_process = None
process_stop_requested = False
login_in_progress = False
login_run_id = 0
login_btn = None
check_login_btn = None
start_btn = None
stop_btn = None
state = None  # 先声明

# App 状态类
class AppState:
    def __init__(self):
        self.config = load_config()
        self.log_messages = []

# 全局状态
state = AppState()  # 初始化
state.log_messages = [
    "[18:15:00] 应用已启动！",
    "[18:15:01] 第一次使用，请先登录",
    "[18:15:02] 登录成功后再开始抢购",
]

def append_log_entry(entry: str):
    """直接追加一条日志文本到界面状态"""
    if not entry:
        return
    state.log_messages.append(entry)
    if len(state.log_messages) > 100:
        state.log_messages = state.log_messages[-100:]

def add_log(msg, level="info"):
    """添加日志，然后 ui.timer 会自动更新"""
    timestamp = time.strftime("%H:%M:%S")
    append_log_entry(f"[{timestamp}] {msg}")


def _extract_product_code(product_url: str) -> str:
    value = (product_url or "").strip().rstrip("/")
    marker = "/products/"
    if marker in value:
        return value.split(marker, 1)[1]
    return value


def _build_product_url(product_code: str) -> str:
    code = (product_code or "").strip().strip("/")
    return f"{PRODUCT_URL_PREFIX}{code}"


def _ensure_windowed_stdio():
    """PyInstaller --windowed 下可能没有 stdout/stderr，uvicorn 初始化日志时会报错。"""
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name, None) is None:
            fallback_stream = open(os.devnull, "w", encoding="utf-8", errors="replace")
            _STDIO_FALLBACK_STREAMS.append(fallback_stream)
            setattr(sys, stream_name, fallback_stream)


def _load_help_markdown() -> str:
    try:
        return HELP_DOC_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return f"# 使用帮助\n\n无法读取帮助文档：`{HELP_DOC_PATH.name}`\n\n错误信息：`{e}`"


def _apply_storage_state(context, page, state_file: Path):
    if not state_file.exists():
        return

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        add_log(f"⚠️ 读取 {state_file.name} 失败: {e}")
        return

    cookies = data.get("cookies") or []
    if cookies:
        try:
            context.add_cookies(cookies)
        except Exception as e:
            add_log(f"⚠️ 写入 cookies 失败: {e}")

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


def _launch_persistent_login_context(playwright):
    launch_kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
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


def _launch_validation_browser(playwright):
    launch_kwargs = dict(headless=True)
    try:
        return playwright.chromium.launch(channel="chrome", **launch_kwargs)
    except Exception:
        return playwright.chromium.launch(**launch_kwargs)

def set_running_state(running: bool):
    """统一维护按钮状态和运行标记"""
    global is_running
    is_running = running
    if start_btn:
        if running:
            start_btn.disable()
        else:
            start_btn.enable()
    if stop_btn:
        if running:
            stop_btn.enable()
        else:
            stop_btn.disable()

def set_login_state(in_progress: bool):
    """维护登录流程状态，不禁用登录相关按钮，允许重复点击重试。"""
    global login_in_progress
    login_in_progress = in_progress

def finalize_process(process):
    """在子进程结束后恢复 GUI 状态"""
    global grab_process, process_stop_requested

    return_code = process.wait()
    if process.stdout:
        process.stdout.close()

    if process_stop_requested:
        add_log("⏹️ 抢购子进程已停止")
    elif return_code == 0:
        add_log("✅ 抢购子进程执行完成")
    else:
        add_log(f"❌ 抢购子进程异常退出，返回码: {return_code}")

    if grab_process is process:
        grab_process = None
        process_stop_requested = False
        set_running_state(False)

def stream_process_output(process):
    """把子进程 stdout/stderr 实时回显到 GUI"""
    if not process.stdout:
        return
    for line in process.stdout:
        message = line.rstrip("\r\n")
        if message:
            append_log_entry(message)

def terminate_process_tree(process):
    """强制结束抢购子进程及其子孙进程，并确认进程退出。"""
    if process.poll() is not None:
        return True

    try:
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
            if result.returncode != 0 and process.poll() is None:
                append_log_entry(result.stdout.strip() or "⚠️ taskkill 执行失败")
        else:
            process.kill()
        process.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        add_log("⚠️ 抢购子进程在 5 秒内未完全退出")
        return False
    except Exception as e:
        add_log(f"⚠️ 停止抢购子进程失败: {e}")
        return False


def shutdown_gui_service():
    """关闭 GUI 服务，并在退出前终止抢购子进程。"""
    global process_stop_requested

    add_log("⚠️ 正在关闭 GUI 服务...")
    if grab_process and grab_process.poll() is None:
        process_stop_requested = True
        add_log(f"⚠️ 关闭前终止抢购子进程，PID: {grab_process.pid}")
        terminated = terminate_process_tree(grab_process)
        if terminated:
            add_log("✅ 已确认抢购子进程退出")
        else:
            add_log("⚠️ 未能确认抢购子进程完全退出，但仍将关闭 GUI")

    def delayed_shutdown():
        time.sleep(0.5)
        core.stop_and_exit()

    threading.Thread(target=delayed_shutdown, daemon=True).start()

def validate_state_file(state_path: Path = STATE_PATH, log_result: bool = True) -> bool:
    """验证指定 state 文件是否存在且可用。"""
    if not state_path.exists():
        if log_result:
            add_log("⚠️ 未检测到 state.json")
        return False

    playwright = None
    browser = None
    context = None
    try:
        playwright = sync_playwright().start()
        browser = _launch_validation_browser(playwright)
        context = browser.new_context(
            storage_state=str(state_path),
            locale="en-US",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(LOGIN_CHECK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if "/account/orders" in page.url:
            if log_result:
                add_log("✅ state.json 校验通过，当前登录状态可用")
            return True

        if log_result:
            add_log("⚠️ state.json 存在，但登录状态已失效，请重新登录")
        return False
    except Exception as e:
        if log_result:
            add_log(f"⚠️ state.json 校验失败: {e}")
        return False
    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()


def get_active_login_page(context, fallback_page):
    """获取当前登录流程中正在使用的页面，优先返回最新打开的弹窗。"""
    for candidate in reversed(context.pages):
        try:
            if not candidate.is_closed():
                return candidate
        except Exception:
            continue
    return fallback_page


def is_login_success_page(page) -> bool:
    """仅在真正进入账号页后，才认为登录成功。"""
    try:
        current_url = page.url.lower()
    except Exception:
        return False

    return "/account/orders" in current_url or "/account" in current_url


def prepare_login_page(context, page, email: str):
    """直接走当前页邮箱登录路径，并仅预填邮箱，避免自动提交触发异常。"""
    page.goto(LOGIN_START_URL, wait_until="domcontentloaded")
    page.get_by_role("link", name="Log in").click(timeout=5000)

    try:
        email_box = page.get_by_role("textbox", name="Email")
        email_box.wait_for(timeout=10000)
        email_box.fill(email, timeout=5000)
        add_log("✅ 已进入邮箱登录页并自动填入邮箱")
        add_log("➡️ 请手动点击 Continue，并完成验证码或邮箱验证码登录")
    except Exception as e:
        add_log(f"⚠️ 未能自动填入邮箱，请手动继续登录: {e}")

    return page

def run_login_flow(run_id: int):
    """在后台线程中打开浏览器，等待用户手动登录并自动保存 state.json。"""
    playwright = None
    context = None
    state_saved = False
    keep_browser_open = False

    try:
        playwright = sync_playwright().start()
        context = _launch_persistent_login_context(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        _apply_storage_state(context, page, STATE_PATH)

        page.goto(LOGIN_CHECK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if "/account/orders" in page.url:
            add_log("✅ 当前 Chrome 持久化会话已登录，开始更新 state.json")
            state_saved = True
            context.storage_state(path=str(TEMP_STATE_PATH))
            if validate_state_file(state_path=TEMP_STATE_PATH, log_result=False):
                TEMP_STATE_PATH.replace(STATE_PATH)
                add_log("✅ state.json 已生成并验证成功，现在可以开始抢购")
                return
            add_log("⚠️ 已检测到登录态，但本次 state.json 校验未通过，请手动检测登录状态")
            return

        page = prepare_login_page(context, page, state.config.email)

        add_log("🔐 已打开 Chrome 持久化登录浏览器，请在浏览器中完成登录/验证码")
        add_log("⏳ 登录成功后会自动生成并校验 state.json")
        add_log("🛡️ 当前会优先复用 pw_profile 和已有 state.json，降低风控概率")

        while True:
            if run_id != login_run_id:
                add_log("ℹ️ 检测到新的登录请求，当前登录流程已结束")
                break

            active_page = get_active_login_page(context, page)

            if active_page.is_closed():
                add_log("⚠️ 登录浏览器已关闭，登录流程结束")
                break

            try:
                body_text = active_page.locator("body").inner_text(timeout=1000)
                if "Couldn't sign you in" in body_text or "check your connection" in body_text:
                    add_log("⚠️ 当前邮箱登录失败：Couldn't sign you in or check your connection")
                    add_log("💡 登录失败时浏览器将保持打开，方便你继续观察或手动处理")
                    keep_browser_open = True
                    break
            except Exception:
                pass

            try:
                if not state_saved and is_login_success_page(active_page):
                    state_saved = True
                    add_log("✅ 检测到已进入账号页，开始生成并校验 state.json")
                    context.storage_state(path=str(TEMP_STATE_PATH))
                    if validate_state_file(state_path=TEMP_STATE_PATH, log_result=False):
                        TEMP_STATE_PATH.replace(STATE_PATH)
                        add_log("✅ state.json 已生成并验证成功，现在可以开始抢购")
                        break
                    add_log("⚠️ 已进入账号页，但本次 state.json 校验未通过，请重新登录或手动检测登录状态")
            except Exception:
                pass

            time.sleep(1)
    except Exception as e:
        add_log(f"❌ 登录流程启动失败: {e}")
    finally:
        if TEMP_STATE_PATH.exists():
            try:
                TEMP_STATE_PATH.unlink()
            except Exception:
                pass
        should_close_browser = not keep_browser_open
        if should_close_browser:
            if context is not None:
                context.close()
            if playwright is not None:
                playwright.stop()
        if run_id == login_run_id:
            set_login_state(False)

def open_login():
    """打开登录浏览器，让用户手动完成登录流程。"""
    global login_run_id
    if login_in_progress:
        add_log("⚠️ 检测到已有登录流程，正在重新打开登录窗口")
    if not state.config.email:
        add_log("❌ 请先在配置中填写 Email 再进行登录")
        return

    login_run_id += 1
    add_log("开始启动登录流程...")
    set_login_state(True)
    threading.Thread(target=run_login_flow, args=(login_run_id,), daemon=True).start()

def check_login_status():
    """检测当前登录状态是否可用。"""
    add_log("正在检测登录状态...")
    threading.Thread(
        target=validate_state_file,
        kwargs={"log_result": True},
        daemon=True,
    ).start()

def start_grab():
    """开始抢购任务"""
    global grab_process, process_stop_requested
    
    if is_running:
        add_log("任务已经在运行中！")
        return

    process_stop_requested = False
    set_running_state(True)
    add_log("=" * 50)
    add_log("开始启动抢购子进程...")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = [sys.executable, WORKER_ARG] if IS_FROZEN else [sys.executable, "-u", str(APP_ENTRY), WORKER_ARG]
    try:
        grab_process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except Exception as e:
        set_running_state(False)
        add_log(f"❌ 启动抢购子进程失败: {e}")
        return

    add_log(f"✅ 抢购子进程已启动，PID: {grab_process.pid}")
    threading.Thread(target=stream_process_output, args=(grab_process,), daemon=True).start()
    threading.Thread(target=finalize_process, args=(grab_process,), daemon=True).start()

def stop_grab():
    """停止任务"""
    global process_stop_requested
    if not is_running:
        add_log("当前没有正在运行的抢购任务")
        return
    if not grab_process:
        add_log("⚠️ 当前没有可停止的抢购子进程")
        set_running_state(False)
        return

    process_stop_requested = True
    stop_btn.disable()
    add_log(f"⚠️ 正在强制停止抢购子进程，PID: {grab_process.pid}")
    threading.Thread(target=terminate_process_tree, args=(grab_process,), daemon=True).start()

# === 主页面 ===
@ui.page('/')
def main_page():
    global login_btn, check_login_btn, start_btn, stop_btn
    page_log_display = None
    page_log_rendered_count = 0
    timer_holder = {'timer': None}
    help_markdown = _load_help_markdown()

    def save_payment_field(event, field_name: str):
        """Persist payment fields after editing is complete, not per keystroke."""
        setattr(state.config, field_name, event.sender.value)
        save_config(state.config)

    def save_product_code_field(event):
        product_code = (event.value or "").strip()
        event.sender.value = product_code
        setattr(state.config, 'product_url', _build_product_url(product_code))
        save_config(state.config)
    
    with ui.header(elevated=True).classes('bg-gradient-to-r from-purple-600 to-blue-600 text-white'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('🛒 GrabBabyShop - 自动抢购助手').classes('text-2xl font-bold')
            with ui.row().classes('items-center gap-2'):
                with ui.dialog() as shutdown_dialog, ui.card().classes('min-w-[320px]'):
                    ui.label('确认关闭程序？').classes('text-lg font-bold')
                    ui.label('关闭后会先终止当前抢购子进程，再退出 GUI 服务。')
                    with ui.row().classes('w-full justify-end gap-2 mt-2'):
                        ui.button('取消', on_click=shutdown_dialog.close).props('outline')
                        ui.button('确认关闭', on_click=lambda: (shutdown_dialog.close(), shutdown_gui_service())).props('color=negative')
                with ui.dialog() as help_dialog:
                    with ui.card().classes('w-[920px] max-w-[95vw] max-h-[85vh] overflow-auto'):
                        with ui.row().classes('w-full items-center justify-between mb-2'):
                            ui.label('📘 使用帮助').classes('text-2xl font-bold')
                            ui.button('关闭', on_click=help_dialog.close).props('flat color=gray')
                        ui.markdown(help_markdown)

                        with ui.row().classes('w-full justify-end mt-4'):
                            ui.button('我知道了', on_click=help_dialog.close).props('color=primary')
                ui.button('📘 使用帮助', on_click=help_dialog.open).props('outline color=white').classes('font-bold')
                ui.button('关闭程序', on_click=shutdown_dialog.open).props('color=negative')
    
    # 居中显示的容器 - 使用 justify-center
    with ui.column().classes('w-full items-center mt-8'):
        with ui.row().classes('w-full max-w-7xl gap-4 items-stretch'):
            
            # === 第一列：配置 ===
            with ui.column().classes('w-80'):
                with ui.card().classes('w-full'):
                    ui.label('⚙️ 配置').classes('text-2xl font-bold mb-4')
                    
                    ui.label('基础配置').classes('font-bold text-sm text-gray-600 mb-2')
                    with ui.row().classes('w-full'):
                        ui.input('Email', value=state.config.email, 
                                 on_change=lambda e: (setattr(state.config, 'email', e.value), save_config(state.config))).classes('w-full')
                    
                    with ui.row().classes('w-full'):
                        ui.input(
                            '产品编码',
                            value=_extract_product_code(state.config.product_url),
                            placeholder='例如: b50js216',
                        ).on('blur', save_product_code_field).classes('w-full')
                    
                    with ui.row().classes('w-full gap-2'):
                        ui.number('目标数量', value=state.config.target_quantity, 
                                 on_change=lambda e: (setattr(state.config, 'target_quantity', int(e.value)), save_config(state.config)), min=1).classes('flex-1')
                        ui.number('检查间隔(秒)', value=state.config.check_interval, 
                                 on_change=lambda e: (setattr(state.config, 'check_interval', float(e.value)), save_config(state.config)), min=0.1, step=0.1).classes('flex-1')
                    
                    ui.separator()
                    
                    ui.label('颜色选择').classes('font-bold text-sm text-gray-600 mb-2')
                    with ui.row().classes('w-full'):
                        ui.switch('启用颜色选择', value=state.config.color_selection_enabled,
                                 on_change=lambda e: (setattr(state.config, 'color_selection_enabled', e.value), save_config(state.config)))
                    
                    with ui.row().classes('w-full'):
                        ui.input('目标颜色 (正则)', value=state.config.target_color or "", 
                                 placeholder='例如: ピンク|Pink', 
                                 on_change=lambda e: (setattr(state.config, 'target_color', e.value or None), save_config(state.config))).classes('w-full')
                    
                    ui.separator()
                    
                    ui.label('支付信息').classes('font-bold text-sm text-gray-600 mb-2')
                    with ui.row().classes('w-full'):
                        ui.input('卡号', value=state.config.card_number).on(
                            'blur', lambda e: save_payment_field(e, 'card_number')
                        ).classes('w-full')
                    
                    with ui.row().classes('w-full gap-2'):
                        ui.input('有效期 (MM/YY)', value=state.config.card_expiry).on(
                            'blur', lambda e: save_payment_field(e, 'card_expiry')
                        ).classes('flex-1')
                        ui.input('CVV', value=state.config.card_cvv).on(
                            'blur', lambda e: save_payment_field(e, 'card_cvv')
                        ).classes('flex-1')
                    
                    with ui.row().classes('w-full'):
                        ui.input('持卡人姓名', value=state.config.cardholder_name).on(
                            'blur', lambda e: save_payment_field(e, 'cardholder_name')
                        ).classes('w-full')
                    
                    with ui.row().classes('w-full'):
                        ui.input('Resident ID', value=state.config.resident_id,
                                 on_change=lambda e: (setattr(state.config, 'resident_id', e.value), save_config(state.config))).classes('w-full')
                    
                    with ui.row().classes('w-full'):
                        ui.switch('自动支付 (⚠️ 慎用)', value=state.config.auto_pay,
                                 on_change=lambda e: (setattr(state.config, 'auto_pay', e.value), save_config(state.config)))
            
            # === 第二列：运行控制 ===
            with ui.column().classes('w-64'):
                with ui.card().classes('w-full'):
                    ui.label('▶️ 运行控制').classes('text-2xl font-bold mb-4')
                    
                    with ui.column().classes('gap-4 items-center w-full'):
                        start_btn = ui.button('▶️ 开始抢购', on_click=start_grab).props('color=positive').classes('w-full text-lg py-4')
                        stop_btn = ui.button('⏹️ 停止', on_click=stop_grab).props('color=negative').classes('w-full text-lg py-4').disable()
                    
                    ui.separator()
                    
                    ui.label('快速操作').classes('font-bold mb-2')
                    with ui.column().classes('gap-2 w-full'):
                        def test_log():
                            """测试日志显示"""
                            add_log("这是一条测试的 INFO 日志！")
                            add_log("这是一条测试的 WARNING 日志！")
                            add_log("这是一条测试的 ERROR 日志！")
                        
                        ui.button('📝 测试日志', on_click=test_log).props('outline color=purple').classes('w-full')
                        login_btn = ui.button('🔐 登录', on_click=open_login).props('outline color=blue').classes('w-full')
                        check_login_btn = ui.button('🔎 检测登录状态', on_click=check_login_status).props('outline color=teal').classes('w-full')
                        def reset_config():
                            ui.notify('已禁用内置默认重置，请直接编辑 config.json')
                        ui.button('🔄 清空配置', on_click=reset_config).props('outline color=orange').classes('w-full')
            
            # === 第三列：日志 ===
            with ui.column().classes('flex-1 min-w-80 max-w-2xl self-stretch'):
                with ui.card().classes('w-full h-full'):
                    with ui.column().classes('w-full h-full gap-4'):
                        ui.label('📜 运行日志').classes('text-2xl font-bold')
                        page_log_display = ui.log(max_lines=100).classes('w-full flex-1 bg-gray-900 text-green-400 p-4 rounded')
                        page_log_rendered_count = 0
                        for message in state.log_messages:
                            page_log_display.push(message, classes='text-green-400 font-mono text-sm whitespace-pre-wrap')
                        page_log_rendered_count = len(state.log_messages)
                        
                        def clear_log():
                            nonlocal page_log_rendered_count
                            state.log_messages.clear()
                            page_log_display.clear()
                            page_log_rendered_count = 0
                            page_log_display.update()
                        ui.button('清空日志', on_click=clear_log).props('outline color=gray').classes('mt-auto')
    
    # 定时器定期更新日志，确保即使其他线程也能显示
    def update_log_display():
        nonlocal page_log_rendered_count
        if not page_log_display:
            return
        try:
            set_login_state(login_in_progress)
            if len(state.log_messages) < page_log_rendered_count:
                page_log_display.clear()
                page_log_rendered_count = 0
            if len(state.log_messages) > page_log_rendered_count:
                for message in state.log_messages[page_log_rendered_count:]:
                    page_log_display.push(message, classes='text-green-400 font-mono text-sm whitespace-pre-wrap')
                page_log_rendered_count = len(state.log_messages)
        except RuntimeError as e:
            if "client this element belongs to has been deleted" in str(e).lower():
                if timer_holder['timer'] is not None:
                    timer_holder['timer'].cancel(with_current_invocation=True)
                return
            raise
    
    timer_holder['timer'] = ui.timer(0.1, update_log_display)

if __name__ in {"__main__", "__mp_main__"}:
    _ensure_windowed_stdio()
    ui.run(
        title="GrabBabyShop",
        port=8085,
        reload=False
    )
