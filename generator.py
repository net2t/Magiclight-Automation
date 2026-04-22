"""
generator.py — MagicLight Auto v3.0
=====================================
All Playwright browser automation:
  - Popup/modal dismissal helpers
  - Login / logout
  - Step 1 (story input) → Step 2 (cast) → Step 3 (storyboard) → Step 4 (render + download)
  - _download() — thumbnail + video download via browser
  - _retry_from_user_center() — fallback recovery
  - check_all_accounts_credits()

Extracted from main.py lines 795–2032.
"""

import os
import re
import time
import base64
import requests
from pathlib import Path
from datetime import datetime

from config import (
    EMAIL, PASSWORD, OUT_BASE, OUT_SHOTS,
    STEP1_WAIT, STEP2_WAIT, STEP3_WAIT,
    LOCAL_OUTPUT_ENABLED, DOWNLOADS_DIR, log, DEBUG,
)

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console(highlight=False, emoji=False)

# ── Shared state (set by main.py) ─────────────────────────────────────────────
_shutdown = False
_browser  = None


def set_shutdown(val: bool):
    global _shutdown
    _shutdown = val


def set_browser(b):
    global _browser
    _browser = b


# ── Console helpers ───────────────────────────────────────────────────────────
def _step(label):  console.print(f"\n[bold cyan]🔧 {label}[/bold cyan]")
def _ok(msg):      console.print(f"  [bold green]✅[/bold green] {msg}")
def _warn(msg):    console.print(f"  [bold yellow]⚠️[/bold yellow]  {msg}")
def _err(msg):     console.print(f"  [bold red]❌[/bold red] {msg}")
def _info(msg):    console.print(f"  [dim]ℹ️[/dim] {msg}")
def _dbg(msg):
    if DEBUG: console.print(f"  [dim magenta]🐛[DBG] {msg}[/dim magenta]")


# ── Sleep helpers ─────────────────────────────────────────────────────────────
def sleep_log(seconds, reason=""):
    secs = int(seconds)
    if secs <= 0: return
    label = f" ({reason})" if reason else ""
    _info(f"[wait] {secs}s{label}…")
    for _ in range(secs):
        if _shutdown: return
        time.sleep(1)


def _wait_dismissing(page, seconds, reason=""):
    label = f" ({reason})" if reason else ""
    _info(f"[wait] {seconds}s{label} (popup-watch)…")
    start = time.time()
    last_pct = ""
    while time.time() - start < seconds:
        if _shutdown: return
        pct = min(100, int((time.time() - start) / seconds * 100))
        if str(pct) != last_pct and pct % 5 == 0:
            console.print(f"  [cyan]>[/cyan] Waiting{label}… [bold]{pct}%[/bold]")
            last_pct = str(pct)
        _dismiss_all(page)
        time.sleep(1)


# ── Popup/modal helpers ───────────────────────────────────────────────────────
_CLOSE_SELECTORS = [
    'button.notice-popup-modal__close',
    'button[aria-label="close"]', 'button[aria-label="Close"]',
    '.sora2-modal-close',
    'button:has-text("Got it")', 'button:has-text("Got It")',
    'button:has-text("Later")', 'button:has-text("Not now")',
    'button:has-text("No thanks")', '.notice-bar__close',
    '.arco-modal-close-btn', '.arco-icon-close',
    'button.arco-btn-secondary:has-text("Cancel")',
    'button:has-text("Skip")', 'button.close-btn',
    'span[class*="close"]',
]

_PROMO_CLOSE_JS = """\
() => {
    const promoClose = Array.from(document.querySelectorAll(
        '[class*="privilege-modal"] [class*="close"],' +
        '[class*="new-year"] [class*="close"],' +
        '[class*="promo"] [class*="close"],' +
        '[class*="upgrade"] [class*="close"],' +
        '.arco-modal-close-btn'
    )).filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    if (promoClose.length) { promoClose[0].click(); return 'promo-closed'; }
    const svgBtns = Array.from(document.querySelectorAll(
        '.arco-modal .arco-modal-close-btn, .arco-modal-close-btn'
    )).filter(el => el.getBoundingClientRect().width > 0);
    if (svgBtns.length) { svgBtns[0].click(); return 'modal-x-closed'; }
    return null;
}"""

_POPUP_JS = """\
() => {
    const BAD = ["Got it","Got It","Close","Done","OK","Later","No thanks",
                 "Maybe later","Not now","Dismiss","Close samples","No","Cancel","Skip"];
    let n = 0;
    document.querySelectorAll('button,span,div,a').forEach(el => {
        const t = (el.innerText || el.textContent || '').trim();
        if (BAD.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { el.click(); n++; }
        }
    });
    document.querySelectorAll(
        '.arco-modal-mask,.driver-overlay,.diy-tour__mask,[class*="tour-mask"],[class*="modal-mask"]'
    ).forEach(el => { try { el.style.display='none'; } catch(e){} });
    return n;
}"""

_REAL_DIALOG_JS = """\
() => {
    const masks = Array.from(document.querySelectorAll(
        '.arco-modal-mask,[class*="modal-mask"]'
    )).filter(el => { const r = el.getBoundingClientRect(); return r.width > 100 && r.height > 100; });
    if (!masks.length) return null;
    const chk = Array.from(document.querySelectorAll(
        'input[type="checkbox"],.arco-checkbox-icon,label[class*="checkbox"]'
    )).find(el => {
        const par = el.closest('label') || el.parentElement;
        const txt = ((par && par.innerText) || el.innerText || '').toLowerCase();
        return txt.includes('remind') || txt.includes('again') || txt.includes('ask');
    });
    if (chk) { try { chk.click(); } catch(e) {} }
    const xBtn = document.querySelector(
        '.arco-modal-close-btn,[aria-label="Close"],[aria-label="close"],' +
        '.arco-icon-close,[class*="modal-close"],[class*="close-icon"]'
    );
    if (xBtn && xBtn.getBoundingClientRect().width > 0) { xBtn.click(); return 'dialog: closed X'; }
    const wrapper = document.querySelector('.arco-modal-wrapper');
    if (wrapper) { wrapper.remove(); masks.forEach(m => m.remove()); return 'dialog: removed wrapper'; }
    return 'dialog: mask found but no X';
}"""


def _all_frames(page):
    try:    return page.frames
    except: return [page]


def _dismiss_all(page):
    for fr in _all_frames(page):
        try: page.evaluate(_PROMO_CLOSE_JS)
        except: pass
        try: page.evaluate(_POPUP_JS)
        except: pass
        for sel in _CLOSE_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=1000)
            except: pass


def dismiss_popups(page, timeout=10, sweeps=3):
    for _ in range(sweeps):
        if _shutdown: return
        _dismiss_all(page)
        try:    page.wait_for_timeout(800)
        except: time.sleep(0.8)


def _dismiss_animation_modal(page):
    try:    page.evaluate(_PROMO_CLOSE_JS)
    except: pass
    try:
        r = page.evaluate(_REAL_DIALOG_JS)
        if r: _info(f"[modal] {r}"); time.sleep(2); return
    except: pass
    for sel in ["label:has-text(\"Don't remind again\")", "label:has-text(\"Don't ask again\")"]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500); time.sleep(0.5)
        except: pass
    for sel in ['.arco-modal-close-btn', 'button[aria-label="Close"]', '.arco-icon-close']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(): loc.click(timeout=2000); time.sleep(2); return
        except: pass
    try: page.keyboard.press("Escape"); time.sleep(0.5)
    except: pass


# ── DOM helpers ───────────────────────────────────────────────────────────────
def wait_site_loaded(page, key_locator=None, timeout=60):
    try: page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
    except: pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        try:
            if page.evaluate("document.readyState") in ("interactive", "complete"): break
        except: pass
        time.sleep(0.3)
    if key_locator is not None:
        try:
            key_locator.wait_for(
                state="visible",
                timeout=max(1000, int((deadline - time.time()) * 1000))
            )
        except: return False
    return True


def dom_click_text(page, texts, timeout=60):
    js = """\
(texts) => {
    const all = Array.from(document.querySelectorAll(
        'button,div[class*="btn"],span[class*="btn"],a,' +
        'div[class*="vlog-btn"],div[class*="footer-btn"],' +
        'div[class*="shiny-action"],div[class*="header-left-btn"]'
    ));
    for (let i = all.length - 1; i >= 0; i--) {
        const el = all[i]; let dt = '';
        el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
        const t = dt.trim() || (el.innerText || '').trim();
        if (texts.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { el.click(); return t; }
        }
    }
    return null;
}"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        r = page.evaluate(js, texts)
        if r: _info(f"  clicked '{r}'"); return True
        time.sleep(2)
    return False


def screenshot(page, name):
    shots_dir = OUT_SHOTS if LOCAL_OUTPUT_ENABLED else "temp/screenshots"
    os.makedirs(shots_dir, exist_ok=True)
    path = os.path.join(shots_dir, f"{name}_{int(time.time())}.png")
    try: page.screenshot(path=path, full_page=True)
    except: pass
    return path


def debug_buttons(page):
    js = """\
() => Array.from(document.querySelectorAll(
    'button,div[class*="btn"],span[class*="btn"],a,div[class*="vlog-btn"]'
)).filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && (el.innerText || '').trim();
}).map(el =>
    el.tagName + '.' + el.className.substring(0, 40) +
    ' | ' + (el.innerText || '').trim().substring(0, 60)
);"""
    try:
        items = page.evaluate(js)
        _info(f"[debug-url] {page.url}")
        for i in (items or []): _info(f"  {i}")
    except: pass


def _credit_exhausted(page):
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        for kw in ["insufficient credits", "not enough credits", "out of credits",
                   "credits exhausted", "quota exceeded"]:
            if kw in body.lower(): return True
    except: pass
    return False


def _read_credits_from_page(page):
    try:
        credit_selectors = [
            ".home-top-navbar-credit-amount",
            ".credit-amount",
            "[class*='credit']",
        ]
        for selector in credit_selectors:
            try:
                credit_element = page.locator(selector).first
                if credit_element.is_visible(timeout=2000):
                    credit_text = credit_element.inner_text().strip()
                    if credit_text and any(c.isdigit() for c in credit_text):
                        clean_text = credit_text.replace(",", "")
                        m = re.search(r"(\d+)", clean_text)
                        if m:
                            return int(m.group(1)), 0
            except: continue
        return 0, 0
    except Exception as e:
        _warn(f"[credits] Read error: {e}"); return 0, 0


# ── Popup handlers ─────────────────────────────────────────────────────────────
def _wait_for_preview_page(page, timeout=60):
    _info("[post-render] Waiting for preview page…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        found = page.evaluate("""\
() => {
    const items = document.querySelectorAll('.previewer-new-body-right-item');
    const dlBtn = Array.from(document.querySelectorAll('button,a')).find(el => {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        return r.width > 0 && (t === 'Download video' || t === 'Download Video');
    });
    if (items.length > 0 || dlBtn) return true;
    return false;
}""")
        if found: _ok("Preview page loaded"); return True
        time.sleep(2)
    _warn("Preview page timeout"); return False


def _handle_generated_popup(page):
    _info("[post-render] Checking for generated popup…")
    submitted = False
    deadline = time.time() + 15
    while time.time() < deadline:
        for sel in [
            "button:has-text('Submit')",
            "button.arco-btn:has-text('Submit')",
            ".arco-modal button:has-text('Submit')",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(); _ok("Submit clicked"); submitted = True; break
            except: pass
        if submitted: break
        time.sleep(2)
    if submitted:
        sleep_log(4, "post-submit settle")
        _wait_for_preview_page(page, timeout=30)
    dl_deadline = time.time() + 30
    while time.time() < dl_deadline:
        for sel in [
            "button:has-text('Download video')", "a:has-text('Download video')",
            "button:has-text('Download Video')", "a:has-text('Download Video')",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(); _ok("Download video clicked"); return True
            except: pass
        time.sleep(2)
    _warn("[post-render] Download video button not found"); return False


# ── Login / Logout ────────────────────────────────────────────────────────────
def _logout(page):
    _info("   Clearing session…")
    try:
        page.goto("https://magiclight.ai/", timeout=30000)
        wait_site_loaded(page, None, timeout=20)
        time.sleep(2)
        page.evaluate("""\
() => {
    const logoutTexts = ['Log out','Logout','Sign out','Sign Out','Log Out'];
    const els = Array.from(document.querySelectorAll('a,button,div,span'));
    for (const el of els) {
        const t = (el.innerText || '').trim();
        if (logoutTexts.includes(t) && el.getBoundingClientRect().width > 0) {
            el.click(); return t;
        }
    }
    return null;
}""")
        time.sleep(1)
    except: pass
    try: page.context.clear_cookies()
    except: pass


def login(page, custom_email=None, custom_pw=None):
    _step("[Login] Starting fresh login…")
    email    = custom_email or EMAIL
    password = custom_pw or PASSWORD
    if not email or not password:
        raise Exception("Login failed — missing credentials")
    try:
        page.context.clear_cookies()
        page.context.clear_permissions()
    except Exception as e:
        _dbg(f"[login] Cookie clear failed: {e}")
    _logout(page)

    login_success = False
    for attempt in range(3):
        try:
            page.goto("https://magiclight.ai/login/?to=%252Fkids-story%252F", timeout=60000)
            wait_site_loaded(page, None, timeout=30)
            if "login" in page.url.lower() or "magiclight.ai" in page.url:
                login_success = True; break
            else:
                _warn(f"[login] Attempt {attempt+1}: not on login page: {page.url}")
                sleep_log(2)
        except Exception as nav_e:
            _warn(f"[login] Navigation attempt {attempt+1} failed: {nav_e}")
            if attempt < 2: sleep_log(3)
    if not login_success:
        raise Exception("Login failed — could not navigate to login page")

    sleep_log(3, "page settle")
    dismiss_popups(page, timeout=5)

    clicked_email_tab = False
    for sel in ['.entry-email', 'text=Log in with Email',
                'button:has-text("Log in with Email")', '[class*="entry-email"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click(timeout=5000); clicked_email_tab = True
                sleep_log(3, "inputs settle"); break
        except: pass
    if not clicked_email_tab:
        try:
            page.evaluate("""() => {
                const el = document.querySelector('.entry-email') ||
                           [...document.querySelectorAll('button')].find(b => b.innerText.includes('Email'));
                if (el) el.click();
            }""")
            sleep_log(2)
        except Exception as js_e:
            _dbg(f"[login] JS email tab click failed: {js_e}")

    email_filled = False
    for sel in ['input[type="text"]', 'input[type="email"]', 'input[name="email"]',
                'input.arco-input', 'input[placeholder*="mail" i]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=15000)
            loc.scroll_into_view_if_needed()
            loc.click(); page.wait_for_timeout(500); loc.fill(email)
            if email.lower() in loc.input_value().lower():
                email_filled = True; _ok(f"[login] Email filled: {email[:10]}…"); break
        except: continue
    if not email_filled:
        screenshot(page, "login_fail_no_email")
        raise Exception("Login failed — email input not found or not fillable")

    page.wait_for_timeout(500)
    pass_filled = False
    for sel in ['input[type="password"]', 'input[name="password"]',
                'input[placeholder*="password" i]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            loc.fill(password)
            if len(loc.input_value()) >= len(password) * 0.8:
                pass_filled = True; _ok("[login] Password filled"); break
        except: continue
    if not pass_filled:
        raise Exception("Login failed — password input not found or not fillable")

    clicked = False
    for attempt in range(3):
        for sel in [".signin-continue", "text=Continue", "div.signin-continue",
                    "button:has-text('Continue')", "button.arco-btn-primary"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000): el.click(); clicked = True; break
            except: pass
        if clicked: break
        if attempt < 2: page.wait_for_timeout(2000)
    if not clicked:
        screenshot(page, "login_fail_no_continue")
        raise Exception("Login failed — Continue button not found")

    try:
        page.wait_for_url("**/kids-story/**", timeout=30000)
        sleep_log(2)
        logout_found = page.evaluate("""() => {
            const logoutTexts = ['Log out','Logout','Sign out','Sign Out','Log Out'];
            const els = Array.from(document.querySelectorAll('a,button,div,span'));
            for (const el of els) {
                const t = (el.innerText || '').trim();
                if (logoutTexts.includes(t) && el.getBoundingClientRect().width > 0) return true;
            }
            return false;
        }""")
        if logout_found: _ok("[login] Login verified")
        else: _warn("[login] Login may have failed — no logout option found")
    except Exception as redirect_e:
        _warn(f"[login] Redirect verification failed: {redirect_e}")
        page.wait_for_timeout(5000)

    _ok(f"[Login] Logged in -> {page.url}")
    page.wait_for_timeout(3000)
    dismiss_popups(page, timeout=10, sweeps=4)

    _step("[credits] Reading credits…")
    try:
        page.goto("https://magiclight.ai/user-center", timeout=45000)
        wait_site_loaded(page, None, timeout=30)
        try:
            page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                   state="visible", timeout=15000)
        except: _warn("[credits] Credit selector not visible")
        sleep_log(2, "user center settle")
    except Exception as e:
        _warn(f"[credits] Could not load user center: {e}")

    total, _ = _read_credits_from_page(page)
    if total > 0:
        _ok(f"[credits] Credits available: {total}")
    else:
        _warn("[credits] Could not read credit count")

    try:
        page.goto("https://magiclight.ai/kids-story/", timeout=45000)
        wait_site_loaded(page, None, timeout=30)
    except Exception as final_e:
        _warn(f"[login] Final navigation failed: {final_e}")

    return total  # return credits for upstream tracking


# ── Step helpers ──────────────────────────────────────────────────────────────
def _select_dropdown(page, label_text, option_text):
    js_open = """\
(label) => {
    const all = Array.from(document.querySelectorAll('label,div,span,p'));
    for (const el of all) {
        const own = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
        if (own !== label && (el.innerText || '').trim() !== label) continue;
        let c = el.parentElement;
        for (let i = 0; i < 6; i++) {
            if (!c) break;
            const t = c.querySelector('.arco-select-view,.arco-select-view-input,' +
                '[class*="select-view"],[class*="arco-select"]');
            if (t && t.getBoundingClientRect().width > 0) { t.click(); return label; }
            c = c.parentElement;
        }
    }
    return null;
}"""
    js_pick = """\
(opt) => {
    const items = Array.from(document.querySelectorAll(
        '.arco-select-option,[class*="select-option"],[class*="option-item"]'
    )).filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    for (const el of items)
        if ((el.innerText || '').trim() === opt) { el.click(); return opt; }
    return null;
}"""
    try:
        r = page.evaluate(js_open, label_text)
        if r:
            time.sleep(0.8)
            r2 = page.evaluate(js_pick, option_text)
            if r2: _ok(f"{label_text} -> {option_text}")
            else:
                page.keyboard.press("Escape")
                _warn(f"'{option_text}' not in {label_text} dropdown")
        else:
            _warn(f"{label_text} dropdown not found")
    except Exception as e:
        _warn(f"_select_dropdown error: {e}")


def step1(page, story_text):
    _step("[Step 1] Story input ->")
    page.goto("https://magiclight.ai/kids-story/", timeout=60000)
    wait_site_loaded(page, None, timeout=60)
    dismiss_popups(page, timeout=10)
    ta = page.get_by_role("textbox", name="Please enter an original")
    wait_site_loaded(page, ta, timeout=60)
    dismiss_popups(page, timeout=6)
    ta.wait_for(state="visible", timeout=20000)
    ta.click(); ta.fill(story_text)
    _ok("Story text filled")
    sleep_log(1)
    try:
        page.locator("div").filter(has_text=re.compile(r"^Pixar 2\.0$")).first.click()
        _ok("Style: Pixar 2.0")
    except: _warn("Pixar 2.0 not found — default")
    try:
        page.locator("div").filter(has_text=re.compile(r"^16:9$")).first.click()
        _ok("Aspect: 16:9")
    except: _warn("16:9 not found — default")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    sleep_log(1)
    _select_dropdown(page, "Voiceover", "Sophia")
    _select_dropdown(page, "Background Music", "Silica")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    sleep_log(1)
    clicked = False
    for sel in ["button.arco-btn-primary:has-text('Next')", "button:has-text('Next')",
                ".vlog-bottom", "div[class*='footer-btn']:has-text('Next')"]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next", "Next Step", "Continue"], timeout=20)
    if not clicked:
        raise Exception("Step 1 Next button not found")
    _ok("Next -> Step 2")
    _wait_dismissing(page, STEP1_WAIT, "AI generating script")


def step2(page):
    _step("[Step 2] Cast ->")
    dismiss_popups(page, timeout=10)
    clicked = False
    for sel in ["button.arco-btn-primary:has-text('Next')", "button:has-text('Next')",
                ".vlog-bottom", "div[class*='footer-btn']:has-text('Next')"]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next", "Next Step", "Continue"], timeout=STEP2_WAIT)
    if not clicked:
        raise Exception("Step 2 Next button not found")
    _ok("Next -> Step 3")
    sleep_log(5, "step2->3 settle")


def step3(page):
    _step("[Step 3] Storyboard ->")
    dismiss_popups(page, timeout=15, sweeps=3)
    _wait_dismissing(page, STEP3_WAIT, "storyboard generating")
    dismiss_popups(page, timeout=10, sweeps=4)
    _dismiss_animation_modal(page)
    sleep_log(3)
    clicked = False
    for sel in ["button.arco-btn-primary:has-text('Generate Video')",
                "button:has-text('Generate Video')",
                "div[class*='footer-btn']:has-text('Generate Video')"]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Generate Video", "Generate"], timeout=30)
    if not clicked:
        raise Exception("Step 3 Generate Video button not found")
    _ok("Generate Video clicked -> Step 4")


def step4(page, safe_name, sheet_row_num=None):
    """Render wait + download. Returns download dict."""
    _step("[Step 4] Render + Download ->")
    from sheets import update_sheet_row
    if sheet_row_num:
        try:
            update_sheet_row(sheet_row_num,
                             Notes=f"Rendering started {datetime.now().strftime('%H:%M:%S')}")
        except Exception: pass

    deadline = time.time() + 1200  # 20 min max
    download_triggered = False
    while time.time() < deadline:
        if _shutdown: break
        _dismiss_all(page)
        try:
            ready = page.evaluate("""\
() => {
    const dlBtn = Array.from(document.querySelectorAll('button,a')).find(el => {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        return r.width > 0 && (t === 'Download video' || t === 'Download Video');
    });
    return !!dlBtn;
}""")
            if ready:
                _ok("Render complete — download button visible")
                download_triggered = True
                break
        except: pass
        time.sleep(10)

    if not download_triggered:
        _handle_generated_popup(page)

    return _download(page, safe_name, sheet_row_num=sheet_row_num)


# ── Download ──────────────────────────────────────────────────────────────────
def _story_dir(safe_name):
    d = os.path.join(OUT_BASE, safe_name)
    os.makedirs(d, exist_ok=True)
    return d


def _download(page, safe_name, sheet_row_num=None):
    out = {"video": "", "thumb": "", "gen_title": "", "summary": "", "tags": "",
           "drive_link": "", "drive_thumb": ""}
    if LOCAL_OUTPUT_ENABLED:
        sdir = _story_dir(safe_name)
    else:
        # Use downloads temp dir when local output disabled
        sdir = str(DOWNLOADS_DIR)
        os.makedirs(sdir, exist_ok=True)

    meta = page.evaluate("""\
() => {
    const result = { title: '', summary: '', hashtags: '' };
    const items = document.querySelectorAll('.previewer-new-body-right-item');
    items.forEach(item => {
        const label = (item.querySelector('.previewer-new-body-right-item-header-title') || {}).innerText || '';
        const ta    = item.querySelector('textarea.arco-textarea');
        const val   = ta ? (ta.value || ta.innerText || '').trim() : '';
        const key   = label.trim().toLowerCase();
        if (key === 'title')    result.title    = val;
        if (key === 'summary')  result.summary  = val;
        if (key === 'hashtags') result.hashtags = val;
    });
    return result;
}""") or {}

    out["gen_title"] = meta.get("title", "")
    out["summary"]   = meta.get("summary", "")
    out["tags"]      = meta.get("hashtags", "")
    _info(f"[meta] Title='{out['gen_title'][:50]}'")

    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": page.url}
    thumb_dest = os.path.join(sdir, f"{safe_name}_thumb.jpg")

    # ── Scroll to load thumbnails ──────────────────────────────────────────────
    try:
        page.mouse.move(1000, 400); page.mouse.wheel(0, 3000); time.sleep(1)
        page.keyboard.press("PageDown"); page.keyboard.press("PageDown"); time.sleep(1)
        page.evaluate("""\
() => {
    document.querySelectorAll('*').forEach(el => {
        try {
            const ov = window.getComputedStyle(el).overflowY;
            if(ov === 'auto' || ov === 'scroll' || ov === 'overlay') {
                if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
            }
        } catch(e) {}
    });
    window.scrollTo(0, document.body.scrollHeight);
}""")
        time.sleep(3)
    except Exception as e:
        _warn(f"[thumb] Scroll warning: {e}")

    # ── Thumbnail ─────────────────────────────────────────────────────────────
    thumb_url = page.evaluate("""\
() => {
    return new Promise(async (resolve) => {
        function findImages(wrapper) {
            const imgs = Array.from(wrapper.querySelectorAll('img[src]'));
            for (let img of imgs) {
                let s = img.src.toLowerCase();
                if ((s.startsWith('http') || s.startsWith('blob:') || s.startsWith('data:'))
                    && img.naturalWidth > 100
                    && !s.includes('avatar') && !s.includes('icon') && !s.includes('logo')) {
                    return img.src;
                }
            }
            return null;
        }
        let src = null;
        const dlBtn = document.querySelector('.show-cover-download');
        if (dlBtn) {
            let wrapper = dlBtn;
            for (let i = 0; i < 4; i++) {
                if (!wrapper) break;
                src = findImages(wrapper);
                if (src) break;
                wrapper = wrapper.parentElement;
            }
        }
        if (!src) {
            const titles = Array.from(document.querySelectorAll('div, span'));
            for (const el of titles) {
                if ((el.innerText || '').trim().toLowerCase() === 'magic thumbnail') {
                    let wrapper = el;
                    for (let i = 0; i < 4; i++) {
                        if (!wrapper) break;
                        src = findImages(wrapper);
                        if (src) break;
                        wrapper = wrapper.parentElement;
                    }
                    if (src) break;
                }
            }
        }
        if (!src) return resolve(null);
        if (src.startsWith('data:')) return resolve(src);
        try {
            const response = await window.fetch(src);
            const blob = await response.blob();
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror  = () => resolve(src);
            reader.readAsDataURL(blob);
        } catch(e) { resolve(src); }
    });
}""")

    if thumb_url:
        try:
            content_bytes = None
            if thumb_url.startswith("data:"):
                _, encoded = thumb_url.split(",", 1)
                content_bytes = base64.b64decode(encoded)
            elif thumb_url.startswith("http"):
                r = requests.get(thumb_url, timeout=30)
                if r.status_code == 200:
                    content_bytes = r.content
            if content_bytes and len(content_bytes) > 5000:
                with open(thumb_dest, "wb") as f: f.write(content_bytes)
                out["thumb"] = thumb_dest
                _ok(f"Thumbnail -> {thumb_dest} ({len(content_bytes)//1024} KB)")
        except Exception as e:
            _warn(f"Thumbnail error: {e}")

    # Fallback thumbnail
    if not out["thumb"]:
        fallback_url = page.evaluate("""\
() => {
    const selectors = [
        '[class*="timeline"] img[src]', '[class*="storyboard"] img[src]',
        '[class*="scene"] img[src]',   'img[src*="oss"][src]',
    ];
    for (const sel of selectors) {
        const imgs = Array.from(document.querySelectorAll(sel))
            .filter(i => i.src.startsWith('http') && i.naturalWidth >= 50);
        if (imgs.length) return imgs[0].src;
    }
    return null;
}""")
        if fallback_url:
            try:
                r = requests.get(fallback_url, timeout=30, cookies=cookies, headers=headers)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(thumb_dest, "wb") as f: f.write(r.content)
                    out["thumb"] = thumb_dest
                    _ok(f"Thumbnail (fallback) -> {thumb_dest}")
            except Exception as e:
                _warn(f"Thumbnail fallback error: {e}")

    # ── Video download ────────────────────────────────────────────────────────
    video_dest = os.path.join(sdir, f"{safe_name}.mp4")

    try:
        cancel_btn = page.locator('button', has_text="Cancel")
        if cancel_btn.count() > 0 and cancel_btn.first.is_visible(timeout=1000):
            cancel_btn.first.click(timeout=1000); sleep_log(1)
    except: pass

    _info("[dl] Waiting for video element (max 60s)…")
    vid_wait_deadline = time.time() + 60
    while time.time() < vid_wait_deadline:
        vid_check = page.evaluate("""\
() => {
    const v = document.querySelector('video');
    if (v && v.src && v.src.includes('.mp4')) return v.src;
    const s = document.querySelector('video source');
    if (s && s.src && s.src.includes('.mp4')) return s.src;
    const a = document.querySelector('a[href*=".mp4"]');
    if (a) return a.href;
    return null;
}""")
        if vid_check: break
        time.sleep(2)

    for sel in [
        "button:has-text('Download video')", "a:has-text('Download video')",
        "button:has-text('Download Video')", "a:has-text('Download Video')",
        "a[download]", "a[href*='.mp4']",
    ]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                _info(f"[dl] Clicking '{sel}'…")
                with page.expect_download(timeout=180000) as dl_info:
                    loc.first.click()
                dl = dl_info.value
                dl.save_as(video_dest)
                if os.path.exists(video_dest) and os.path.getsize(video_dest) > 10000:
                    out["video"] = video_dest
                    _ok(f"Video -> {video_dest} ({os.path.getsize(video_dest)//1024} KB)")
                    break
        except Exception as e:
            _warn(f"  {sel}: {e}")

    # URL fallback
    if not out["video"]:
        vid_url = page.evaluate("""\
() => {
    const v = document.querySelector('video');
    if (v && v.src && v.src.includes('.mp4')) return v.src;
    const s = document.querySelector('video source');
    if (s && s.src && s.src.includes('.mp4')) return s.src;
    const a = document.querySelector('a[href*=".mp4"]');
    if (a) return a.href;
    return null;
}""")
        if vid_url:
            for _attempt in range(3):
                try:
                    _info(f"[dl] Direct URL attempt {_attempt+1}: {vid_url[:80]}")
                    r = requests.get(vid_url, stream=True, timeout=180,
                                     cookies=cookies, headers=headers)
                    r.raise_for_status()
                    total = 0
                    with open(video_dest, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk: f.write(chunk); total += len(chunk)
                    if total > 10000:
                        out["video"] = video_dest
                        _ok(f"Video (URL) -> {video_dest} ({total//1024} KB)")
                        break
                    else:
                        _warn(f"Video too small ({total}B)")
                        try: os.remove(video_dest)
                        except: pass
                except Exception as e:
                    _warn(f"Video URL attempt {_attempt+1} failed: {e}")
                    if _attempt < 2: time.sleep(2 ** _attempt)

    if not out["video"]:
        _err("[dl] VIDEO DOWNLOAD FAILED")

    return out


# ── Retry via User Center ─────────────────────────────────────────────────────
def _retry_from_user_center(page, project_url, safe_name):
    _info("[retry] Opening User Center…")
    sleep_log(5, "pre-retry")
    try:
        page.goto("https://magiclight.ai/user-center/", timeout=60000)
        wait_site_loaded(page, None, timeout=45)
        sleep_log(4)
        _dismiss_all(page)
    except Exception as e:
        _warn(f"User Center failed: {e}"); return None

    clicked = page.evaluate("""\
(targetUrl) => {
    if (targetUrl) {
        const parts = targetUrl.replace(/[/]+$/, '').split('/');
        const projId = parts[parts.length - 1];
        if (projId && projId.length > 5) {
            const match = Array.from(document.querySelectorAll('a[href]'))
                .find(a => a.href && a.href.includes(projId));
            if (match && match.getBoundingClientRect().width > 0) {
                match.click(); return 'matched ID: ' + projId;
            }
        }
    }
    const editLinks = Array.from(document.querySelectorAll('a[href*="/project/edit/"],a[href*="/edit/"]'))
        .filter(a => a.getBoundingClientRect().width > 0);
    if (editLinks.length) { editLinks[0].click(); return 'edit-link'; }
    return null;
}""", project_url or "")

    if not clicked:
        if project_url and '/project/' in project_url:
            try:
                page.goto(project_url, timeout=60000)
                wait_site_loaded(page, None, timeout=30)
                sleep_log(3); _dismiss_all(page)
                _handle_generated_popup(page); sleep_log(2)
                return _download(page, safe_name)
            except Exception as e:
                _warn(f"Direct goto failed: {e}")
        _warn("[retry] Could not find project"); return None

    _ok(f"[retry] Project opened ({clicked})")
    sleep_log(5)
    wait_site_loaded(page, None, 30)
    _dismiss_all(page)
    _handle_generated_popup(page)
    sleep_log(2)
    try:
        return _download(page, safe_name)
    except Exception as e:
        _warn(f"[retry] Download failed: {e}"); return None


# ── Account credits check ─────────────────────────────────────────────────────
def check_all_accounts_credits(headless=False):
    from playwright.sync_api import sync_playwright
    from sheets import update_credits_login

    global _browser
    _step("[Credits Check] Starting account credit check…")

    accounts = []
    if os.path.exists("accounts.txt"):
        with open("accounts.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    u, p = line.split(":", 1)
                    accounts.append((u.strip(), p.strip()))
    if not accounts:
        if EMAIL and PASSWORD:
            accounts = [(EMAIL, PASSWORD)]
            _info("[Credits Check] Using single account from .env")
        else:
            _err("[Credits Check] No credentials in accounts.txt or .env"); return

    _ok(f"[Credits Check] Loaded {len(accounts)} account(s)")
    pw_mgr = None
    local_browser = False
    if _browser is None:
        pw_mgr = sync_playwright().start()
        _browser = pw_mgr.chromium.launch(headless=headless)
        local_browser = True

    checked = failed = 0
    for idx, (email, password) in enumerate(accounts, 1):
        _info(f"[Credits Check] Checking {idx}/{len(accounts)}: {email}")
        context = None
        try:
            context = _browser.new_context(accept_downloads=True, no_viewport=True)
            page = context.new_page()
            login(page, custom_email=email, custom_pw=password)
            try:
                page.goto("https://magiclight.ai/user-center", timeout=45000)
                wait_site_loaded(page, None, timeout=30)
                sleep_log(2, "user center settle")
            except Exception as e:
                _warn(f"[Credits Check] Could not load user center: {e}")
            total_credits, _ = _read_credits_from_page(page)
            _ok(f"[Credits Check] {email}: Total={total_credits}")
            update_credits_login(email, total_credits)
            try: _logout(page)
            except: pass
            context.close(); checked += 1
        except Exception as e:
            _err(f"[Credits Check] Failed for {email}: {e}")
            failed += 1
            try:
                if context: context.close()
            except: pass

    _ok(f"[Credits Check] Complete: {checked} checked, {failed} failed")
    if local_browser and pw_mgr:
        try: _browser.close()
        except: pass
        try: pw_mgr.stop()
        except: pass
        _browser = None


# ── Filename helpers (re-exported so main.py can use them) ────────────────────
def make_safe(row_num, title, file_type=""):
    safe_title = re.sub(r"[^\w\-]", "_", str(title)[:30])
    if file_type:
        return f"R{row_num}_{safe_title}_{file_type}".strip("_")
    return re.sub(r"[^\w\-]", "_", f"R{row_num}_{safe_title}").strip("_")


def extract_row_num(stem: str) -> int | None:
    m = re.match(r"R(\d+)_", stem)
    if m: return int(m.group(1))
    m = re.match(r"row(\d+)[_\-]", stem, re.IGNORECASE)
    if m: return int(m.group(1))
    return None
