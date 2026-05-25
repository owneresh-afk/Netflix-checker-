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
