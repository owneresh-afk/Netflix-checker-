#!/bin/bash

# Update script for the bot

echo "🔄 Updating Netflix Bulk Checker Bot..."

# Pull latest code
git pull origin main

# Install/update dependencies
pip install -r requirements.txt --upgrade

# Restart the bot
pkill -f "python.*bulk_netflix_bot.py"
sleep 2
python3 bulk_netflix_bot.py &

echo "✅ Bot updated and restarted!"
