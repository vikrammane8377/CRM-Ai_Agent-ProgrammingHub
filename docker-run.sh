#!/bin/bash

# Docker build and run script for PH CRM Agent

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Building PH CRM Agent Docker image...${NC}"

# Build the Docker image
docker build -t ph-crm-agent .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Docker image built successfully!${NC}"
    
    echo -e "${YELLOW}Starting PH CRM Agent container...${NC}"
    
    # Run the container
    docker run -d \
        --name ph-crm-agent \
        -p 8080:8080 \
        -e OPENAI_API_KEY="$OPENAI_API_KEY" \
        -e MONGODB_URI="$MONGODB_URI" \
        -e MONGODB_DB_NAME="$MONGODB_DB_NAME" \
        -e MONGODB_CONVERSATIONS_COLLECTION="$MONGODB_CONVERSATIONS_COLLECTION" \
        -e SERVICE_ACCOUNT_FILE="$SERVICE_ACCOUNT_FILE" \
        -e IMPERSONATED_USER="$IMPERSONATED_USER" \
        -e SPREADSHEET_ID="$SPREADSHEET_ID" \
        -v $(pwd)/credentials:/app/credentials \
        -v $(pwd)/certificates:/app/certificates \
        ph-crm-agent
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Container started successfully!${NC}"
        echo -e "${YELLOW}Container name: ph-crm-agent${NC}"
        echo -e "${YELLOW}API endpoint: http://localhost:8080${NC}"
        echo -e "${YELLOW}Health check: http://localhost:8080/health${NC}"
        echo -e "${YELLOW}Process emails: http://localhost:8080/process-emails${NC}"
        
        echo -e "${GREEN}Container logs:${NC}"
        docker logs ph-crm-agent
    else
        echo -e "${RED}❌ Failed to start container${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ Failed to build Docker image${NC}"
    exit 1
fi 