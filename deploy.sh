#!/bin/bash
set -e

echo "=========================================="
echo "🚀 Emotion Detection Backend Deployment"
echo "=========================================="

# 1. Update package list
echo "📦 Updating system packages..."
sudo apt-get update -y

# 2. Check and install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    sudo apt-get install -y docker.io docker-compose-v2
    sudo systemctl enable --now docker
    sudo usermod -aG docker $USER
fi

# 3. Check and install Nginx & Certbot
if ! command -v nginx &> /dev/null; then
    echo "🌐 Installing Nginx & Certbot..."
    sudo apt-get install -y nginx certbot python3-certbot-nginx
fi

# 4. Check for .env file
if [ ! -f .env ]; then
    echo "⚠️  WARNING: .env file not found!"
    echo "Please create a .env file with your credentials before running the container."
    exit 1
fi

# 5. Build and Start Backend Container with Docker Compose
echo "🔨 Building and starting Backend container..."
sudo docker compose -f docker-compose.prod.yml down || true
sudo docker compose -f docker-compose.prod.yml up -d --build

# 6. Check Container Status
echo "🔍 Checking container status..."
sudo docker ps -f name=emotion_detection_backend

echo "=========================================="
echo "✅ Backend deployed successfully!"
echo "API is running on port 2508."
echo "=========================================="
