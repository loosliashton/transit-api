# Use an official Python runtime (full version to include build tools)
FROM python:3.11

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install dependencies individually to isolate build failures
RUN pip install --no-cache-dir pandas
RUN pip install --no-cache-dir protobuf
RUN pip install --no-cache-dir gtfs-realtime-bindings
RUN pip install --no-cache-dir fastapi uvicorn requests

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Define environment variable
ENV PORT=8000

# Run main.py when the container launches
CMD ["python", "main.py"]
