#!/bin/bash

# Azure Container Apps Deployment Script for SimpleChat MCP Server

set -e

# Configuration
RESOURCE_GROUP_NAME="${RESOURCE_GROUP_NAME:-simplechat-mcp-rg}"
LOCATION="${LOCATION:-eastus}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-simplechat-mcp-server}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-your-registry/simplechat-mcp-server:latest}"
SIMPLECHAT_BASE_URL="${SIMPLECHAT_BASE_URL}"
SIMPLECHAT_BEARER_TOKEN="${SIMPLECHAT_BEARER_TOKEN}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v az &> /dev/null; then
        log_error "Azure CLI is not installed. Please install it first."
        exit 1
    fi
    
    if [ -z "$SIMPLECHAT_BASE_URL" ]; then
        log_error "SIMPLECHAT_BASE_URL environment variable is required"
        exit 1
    fi
    
    if [ -z "$SIMPLECHAT_BEARER_TOKEN" ]; then
        log_error "SIMPLECHAT_BEARER_TOKEN environment variable is required"
        exit 1
    fi
    
    # Check if logged in to Azure
    if ! az account show &> /dev/null; then
        log_error "Not logged in to Azure. Please run 'az login' first."
        exit 1
    fi
    
    log_info "Prerequisites check passed"
}

# Create resource group
create_resource_group() {
    log_info "Creating resource group: $RESOURCE_GROUP_NAME"
    
    if az group show --name "$RESOURCE_GROUP_NAME" &> /dev/null; then
        log_warn "Resource group $RESOURCE_GROUP_NAME already exists"
    else
        az group create \
            --name "$RESOURCE_GROUP_NAME" \
            --location "$LOCATION"
        log_info "Resource group created successfully"
    fi
}

# Deploy using Bicep
deploy_with_bicep() {
    log_info "Deploying Container App using Bicep template..."
    
    az deployment group create \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --template-file azure-container-app.bicep \
        --parameters \
            containerAppName="$CONTAINER_APP_NAME" \
            location="$LOCATION" \
            containerImage="$CONTAINER_IMAGE" \
            simpleChatBaseUrl="$SIMPLECHAT_BASE_URL" \
            simpleChatBearerToken="$SIMPLECHAT_BEARER_TOKEN" \
            logLevel="$LOG_LEVEL"
    
    log_info "Deployment completed successfully"
}

# Deploy using ARM template
deploy_with_arm() {
    log_info "Deploying Container App using ARM template..."
    
    az deployment group create \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --template-file azure-container-app.json \
        --parameters \
            containerAppName="$CONTAINER_APP_NAME" \
            location="$LOCATION" \
            containerImage="$CONTAINER_IMAGE" \
            simpleChatBaseUrl="$SIMPLECHAT_BASE_URL" \
            simpleChatBearerToken="$SIMPLECHAT_BEARER_TOKEN" \
            logLevel="$LOG_LEVEL"
    
    log_info "Deployment completed successfully"
}

# Get deployment info
get_deployment_info() {
    log_info "Getting deployment information..."
    
    FQDN=$(az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --query "properties.latestRevisionFqdn" \
        --output tsv)
    
    log_info "Container App FQDN: $FQDN"
    log_info "Health endpoint: https://$FQDN/health"
    log_info "Ready endpoint: https://$FQDN/ready"
}

# Show logs
show_logs() {
    log_info "Showing recent logs..."
    
    az containerapp logs show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --follow
}

# Main deployment
main() {
    log_info "Starting SimpleChat MCP Server deployment to Azure Container Apps"
    
    check_prerequisites
    create_resource_group
    
    # Use Bicep by default, fallback to ARM
    if command -v bicep &> /dev/null; then
        deploy_with_bicep
    else
        log_warn "Bicep CLI not found, using ARM template"
        deploy_with_arm
    fi
    
    get_deployment_info
    
    log_info "Deployment completed! Use 'show-logs' argument to view logs."
}

# Handle command line arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "show-logs")
        show_logs
        ;;
    "info")
        get_deployment_info
        ;;
    *)
        echo "Usage: $0 [deploy|show-logs|info]"
        echo "  deploy    - Deploy the application (default)"
        echo "  show-logs - Show application logs"
        echo "  info      - Show deployment information"
        exit 1
        ;;
esac