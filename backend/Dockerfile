# Dockerfile for building the Karaoke Processor backend

FROM python:3.10-slim

# Install system dependencies including librubberband for pitch shifting
RUN apt-get update && apt-get install -y \
    # Install build dependencies first if needed for some packages
    # build-essential \
    # Install rubberband library first
    librubberband-dev \
    # Then install ffmpeg, ensuring it's linked against rubberband if possible
    ffmpeg \
    git \
    sox \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Set environment variable to potentially help ffmpeg find plugins (might not be needed)
# ENV LD_LIBRARY_PATH /usr/local/lib:$LD_LIBRARY_PATH

# Copy and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

# Expose port 8000 for uvicorn
EXPOSE 8000

# Start server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]