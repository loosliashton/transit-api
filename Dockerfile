# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system build dependencies (often needed for pandas/protobuf on slim images)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Optimize caching: Copy requirements and install dependencies first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make port 8000 available
EXPOSE 8000

# Define environment variable
ENV PORT=8000

# Run main.py
CMD ["python", "main.py"]
