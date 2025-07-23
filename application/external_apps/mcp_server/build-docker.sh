#!/bin/bash

# Build and push Docker image for SimpleChat MCP Server

set -e

# Configuration
REGISTRY="${DOCKER_REGISTRY:-youracr.azurecr.io}"
IMAGE_NAME="${IMAGE_NAME:-simplechat-mcp-server}"
TAG="${TAG:-latest}"
FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${TAG}"

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
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install it first."
        exit 1
    fi
    
    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
    
    log_info "Prerequisites check passed"
}

# Build Docker image
build_image() {
    log_info "Building Docker image: $FULL_IMAGE_NAME"
    
    docker build -t "$FULL_IMAGE_NAME" .
    
    log_info "Docker image built successfully"
}

# Test image locally
test_image() {
    log_info "Testing Docker image locally..."
    
    # Create a temporary env file for testing
    cat > .env.test << EOF
SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=http://localhost:5000
SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=test-token
SIMPLECHAT_MCP_LOG_LEVEL=INFO
EOF
    
    # Run container with test environment
    CONTAINER_ID=$(docker run -d \
        --env-file .env.test \
        -p 8080:8080 \
        "$FULL_IMAGE_NAME")
    
    log_info "Container started with ID: $CONTAINER_ID"
    
    # Wait a bit for container to start
    sleep 5
    
    # Test health endpoint
    if curl -f http://localhost:8080/health > /dev/null 2>&1; then
        log_info "Health check passed"
    else
        log_warn "Health check failed (expected if no valid token provided)"
    fi
    
    # Show container logs
    log_info "Container logs:"
    docker logs "$CONTAINER_ID"
    
    # Stop and remove container
    docker stop "$CONTAINER_ID"
    docker rm "$CONTAINER_ID"
    
    # Clean up test file
    rm -f .env.test
    
    log_info "Local test completed"
}

# Login to registry
login_registry() {
    if [[ $REGISTRY == *"azurecr.io" ]]; then
        log_info "Logging in to Azure Container Registry..."
        
        if command -v az &> /dev/null; then
            az acr login --name "${REGISTRY%%.*}"
        else
            log_error "Azure CLI not found. Please install it or login to registry manually."
            exit 1
        fi
    else
        log_info "Please ensure you're logged in to your container registry: $REGISTRY"
        read -p "Press Enter to continue..."
    fi
}

# Push image to registry
push_image() {
    log_info "Pushing image to registry: $FULL_IMAGE_NAME"
    
    docker push "$FULL_IMAGE_NAME"
    
    log_info "Image pushed successfully"
}

# Show image info
show_info() {
    log_info "Image Information:"
    echo "  Registry: $REGISTRY"
    echo "  Image Name: $IMAGE_NAME"
    echo "  Tag: $TAG"
    echo "  Full Name: $FULL_IMAGE_NAME"
    echo ""
    
    if docker images "$FULL_IMAGE_NAME" | grep -q "$IMAGE_NAME"; then
        log_info "Local image details:"
        docker images "$FULL_IMAGE_NAME"
    else
        log_warn "Image not found locally"
    fi
}

# Main build process
main() {
    log_info "Starting Docker build process for SimpleChat MCP Server"
    
    check_prerequisites
    build_image
    test_image
    login_registry
    push_image
    show_info
    
    log_info "Docker build and push completed successfully!"
    log_info "You can now deploy using: CONTAINER_IMAGE=$FULL_IMAGE_NAME ./deploy-azure.sh"
}

# Handle command line arguments
case "${1:-build}" in
    "build")
        main
        ;;
    "test")
        check_prerequisites
        test_image
        ;;
    "push")
        check_prerequisites
        login_registry
        push_image
        ;;
    "info")
        show_info
        ;;
    *)
        echo "Usage: $0 [build|test|push|info]"
        echo "  build - Build, test, and push image (default)"
        echo "  test  - Test image locally only"
        echo "  push  - Push existing image to registry"
        echo "  info  - Show image information"
        echo ""
        echo "Environment variables:"
        echo "  DOCKER_REGISTRY - Container registry (default: youracr.azurecr.io)"
        echo "  IMAGE_NAME      - Image name (default: simplechat-mcp-server)"
        echo "  TAG             - Image tag (default: latest)"
        exit 1
        ;;
esac