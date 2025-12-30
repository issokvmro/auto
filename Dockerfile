FROM python:3.9-slim

WORKDIR /app

# Install system dependencies (build tools might be needed for some python packages)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command to start the watcher
# Provide RD_API_TOKEN via environment variable at runtime
CMD ["python", "-m", "rd_automator.cli", "start"]
