# health_check.py
import os
import sys

def check_health():
    """Simple health check for Render deployment"""
    
    # Check if bot file exists
    if not os.path.exists("bulk_netflix_bot.py"):
        print("❌ Bot file not found!")
        sys.exit(1)
    
    # Check if requirements installed
    try:
        import telegram
        import requests
        print("✅ Dependencies installed")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        sys.exit(1)
    
    # Check if BOT_TOKEN is set
    if not os.environ.get("BOT_TOKEN"):
        print("⚠️ BOT_TOKEN not set (this is normal for build stage)")
    else:
        print("✅ BOT_TOKEN configured")
    
    print("✅ Health check passed!")
    sys.exit(0)

if __name__ == "__main__":
    check_health()
