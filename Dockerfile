FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 -r requirements.txt

# Copy application code
COPY . .

# Create knowledge_base directory if not exists
RUN mkdir -p knowledge_base

CMD ["python", "main.py", "chat"]