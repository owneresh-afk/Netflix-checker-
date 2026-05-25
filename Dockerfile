FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bulk_netflix_bot.py .

# Create necessary folders
RUN mkdir -p temp_cookies bot_output bulk_results

# Run the bot
CMD ["python", "bulk_netflix_bot.py"]
