# Netflix Bulk Cookie Checker Bot

<div align="center">

✦✦✦ **Premium Telegram Bot for Bulk Netflix Cookie Checking** ✦✦✦

[![Deploy on Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

</div>

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🚀 **Bulk Processing** | Check 1,000+ cookies at once |
| ⚡ **50x Concurrent** | Lightning fast parallel checks |
| 🔥 **Premium Detection** | Auto-detects Premium accounts |
| 🔗 **NFToken Links** | One-click login without password |
| 📦 **ZIP Support** | Upload multiple cookie files |
| ✅ **Auto Export** | Download results as ZIP |
| 📊 **Live Progress** | Real-time progress bar |
| 🎨 **Premium UI** | Line emojis & symbols |

## 📋 Commands

| Command | Description |
|---------|-------------|
| `/start` | Launch the bot |
| `/help` | Show help menu |
| `/stats` | View your statistics |
| `/batch` | Check batch status |
| `/export` | Download results |

## 📁 Supported File Formats

- `.txt` - Netscape cookie format
- `.json` - Browser extension export
- `.zip` - Multiple cookie files (1000+)

## 🚀 Deployment

### Deploy on Render (Free)

1. Fork this repository
2. Go to [render.com](https://render.com)
3. Click "New +" → "Web Service"
4. Connect your GitHub repo
5. Add environment variable: `BOT_TOKEN`
6. Click "Deploy"

### Deploy on Railway (Free)

1. Fork this repository
2. Go to [railway.app](https://railway.app)
3. Click "New Project" → "Deploy from GitHub"
4. Add `BOT_TOKEN` in variables
5. Deploy!

### Local Deployment

```bash
# Clone repository
git clone https://github.com/owneresh-afk/Netflix-checker-/tree/main
cd Netflix 

# Install dependencies
pip install -r requirements.txt

# Set bot token
export BOT_TOKEN="your_bot_token_here"

# Run bot
python main.py
