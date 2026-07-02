#!/bin/bash
set -e

# Civility.ai Deployment Script
# Usage: ./deploy.sh [environment] [command]
# Environments: dev, staging, prod
# Commands: deploy, rollback, status, logs

ENVIRONMENT=${1:-dev}
COMMAND=${2:-deploy}
NAMESPACE="civility-ai"
REGISTRY="ghcr.io"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
  echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1"
}

check_dependencies() {
  for cmd in kubectl docker jq; do
    if ! command -v $cmd &> /dev/null; then
      log_error "$cmd not found. Please install it."
      exit 1
    fi
  done
}

create_namespace() {
  if ! kubectl get namespace $NAMESPACE &> /dev/null; then
    log_info "Creating namespace $NAMESPACE..."
    kubectl create namespace $NAMESPACE
    kubectl label namespace $NAMESPACE name=$NAMESPACE
  fi
}

create_secrets() {
  log_info "Setting up secrets for $ENVIRONMENT..."
  
  if [ -z "$ANTHROPIC_API_KEY" ]; then
    log_error "ANTHROPIC_API_KEY environment variable not set"
    exit 1
  fi

  kubectl -n $NAMESPACE create secret generic civility-secrets \
    --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY \
    --dry-run=client -o yaml | kubectl apply -f -
  
  log_info "Secrets updated"
}

build_images() {
  log_info "Building Docker images for $ENVIRONMENT..."
  
  docker build -t $REGISTRY/civility-ai/civility-backend:$ENVIRONMENT ./backend
  docker build -t $REGISTRY/civility-ai/civility-frontend:$ENVIRONMENT ./frontend
  
  if [ "$ENVIRONMENT" != "dev" ]; then
    log_info "Pushing images to registry..."
    docker push $REGISTRY/civility-ai/civility-backend:$ENVIRONMENT
    docker push $REGISTRY/civility-ai/civility-frontend:$ENVIRONMENT
  fi
}

deploy() {
  log_info "Deploying to $ENVIRONMENT environment..."
  
  create_namespace
  create_secrets
  
  # Apply deployments
  log_info "Applying Kubernetes manifests..."
  kubectl apply -f k8s/deployments.yaml
  kubectl apply -f k8s/services.yaml
  
  # Wait for rollout
  log_info "Waiting for deployments to roll out..."
  kubectl -n $NAMESPACE rollout status deployment/civility-backend --timeout=5m
  kubectl -n $NAMESPACE rollout status deployment/civility-frontend --timeout=5m
  
  log_info "Deployment completed successfully!"
}

rollback() {
  log_info "Rolling back deployments..."
  
  kubectl -n $NAMESPACE rollout undo deployment/civility-backend
  kubectl -n $NAMESPACE rollout undo deployment/civility-frontend
  
  kubectl -n $NAMESPACE rollout status deployment/civility-backend --timeout=5m
  kubectl -n $NAMESPACE rollout status deployment/civility-frontend --timeout=5m
  
  log_info "Rollback completed"
}

status() {
  log_info "Deployment status for $ENVIRONMENT:"
  echo ""
  echo "Deployments:"
  kubectl -n $NAMESPACE get deployments
  echo ""
  echo "Pods:"
  kubectl -n $NAMESPACE get pods -o wide
  echo ""
  echo "Services:"
  kubectl -n $NAMESPACE get svc
  echo ""
  echo "HPA Status:"
  kubectl -n $NAMESPACE get hpa
}

logs_cmd() {
  COMPONENT=${3:-backend}
  
  if [ "$COMPONENT" = "backend" ]; then
    kubectl -n $NAMESPACE logs -l app=civility-backend -f --tail=100 --timestamps=true
  elif [ "$COMPONENT" = "frontend" ]; then
    kubectl -n $NAMESPACE logs -l app=civility-frontend -f --tail=100 --timestamps=true
  else
    log_error "Unknown component: $COMPONENT (use 'backend' or 'frontend')"
  fi
}

main() {
  check_dependencies
  
  case $COMMAND in
    deploy)
      build_images
      deploy
      ;;
    rollback)
      rollback
      ;;
    status)
      status
      ;;
    logs)
      logs_cmd
      ;;
    *)
      log_error "Unknown command: $COMMAND"
      echo "Usage: $0 [environment] [command]"
      echo "Environments: dev, staging, prod"
      echo "Commands: deploy, rollback, status, logs [backend|frontend]"
      exit 1
      ;;
  esac
}

main "$@"
