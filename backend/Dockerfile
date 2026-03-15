FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    CHROMA_DB_PATH=/app/chroma_db \
    TORCH_CPU_ARCH_LIST="AVX2"

WORKDIR /app

# System dependencies
RUN apt-get update -o Acquire::ForceIPv4=true \
    && apt-get install -y --no-install-recommends \
       libgomp1 \
       build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency file first (layer caching)
COPY requirements.txt .

# Upgrade pip and install CPU-only ML libraries
RUN pip install --upgrade pip \
    && pip install --no-cache-dir \
        torch \
        torchvision \
        torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Copy application code
COPY . .

# Create chroma DB directory with correct permissions
RUN mkdir -p /app/chroma_db \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]