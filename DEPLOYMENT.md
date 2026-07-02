# Civility.ai Deployment Pipeline

## Overview
Complete CI/CD pipeline for containerized moderation system with Kubernetes orchestration, automated testing, and multi-environment support.

## Architecture

```
GitHub Push
    ↓
GitHub Actions CI/CD Pipeline
    ├─ Build Docker images (backend & frontend)
    ├─ Push to GitHub Container Registry (ghcr.io)
    ├─ Run automated tests
    ├─ Deploy to Kubernetes cluster
    └─ Verify deployment health
```

## Files Created

### CI/CD Workflow
- `.github/workflows/deploy.yml` — Automated build, test, and deployment pipeline

### Kubernetes Manifests
- `k8s/deployments.yaml` — Backend & frontend deployments with security hardening, resource limits, probes
- `k8s/services.yaml` — Services, networking policies, and horizontal pod autoscaling

### Deployment Scripts
- `scripts/deploy.sh` — Manual deployment orchestration for dev/staging/prod

## Quick Start

### 1. Configure GitHub Secrets

Set in your GitHub repository settings:

```
KUBE_CONFIG         → base64-encoded kubeconfig file
ANTHROPIC_API_KEY   → Your API key
```

**Generate base64 kubeconfig:**
```bash
cat ~/.kube/config | base64 | pbcopy  # macOS
cat ~/.kube/config | base64 | xclip   # Linux
cat ~/.kube/config | base64           # Windows (copy output)
```

### 2. Deploy Manually

```bash
# Make script executable
chmod +x scripts/deploy.sh

# Deploy to dev
./scripts/deploy.sh dev deploy

# Check status
./scripts/deploy.sh dev status

# View logs
./scripts/deploy.sh dev logs backend

# Rollback if needed
./scripts/deploy.sh dev rollback
```

### 3. Automatic CI/CD

Push to `main` or `develop` branches to trigger:
- Image builds for both backend and frontend
- Automated testing
- Kubernetes deployment (main branch only)
- Rollout verification

## Environment Variables

### Set via `ANTHROPIC_API_KEY`
```bash
export ANTHROPIC_API_KEY=your_key_here
./scripts/deploy.sh prod deploy
```

### Or pass via kubectl
```bash
kubectl -n civility-ai create secret generic civility-secrets \
  --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Deployment Environments

| Environment | Branch | Action | Replicas |
|---|---|---|---|
| **Dev** | develop | Manual only | 2 |
| **Staging** | develop | Auto on push | 2 |
| **Prod** | main | Auto on push | 2-10 (HPA) |

## Scaling

### Manual Scale
```bash
kubectl -n civility-ai scale deployment civility-backend --replicas=5
```

### Automatic Scaling (HPA)
Backend scales 2-10 replicas based on:
- CPU > 70% utilization
- Memory > 80% utilization

Frontend scales 2-5 replicas based on:
- CPU > 80% utilization
- Memory > 85% utilization

## Health Checks

### Liveness Probe
- Path: `/health`
- Interval: 20 seconds
- Failure threshold: 3

### Readiness Probe
- Path: `/health`
- Interval: 10 seconds
- Failure threshold: 3

**Note:** Add `/health` endpoint to `backend/main.py`:
```python
@app.get("/health")
def health_check():
    return {"status": "ok"}
```

## Security Features

- Network policies (restrict cross-namespace traffic)
- Read-only root filesystems
- Non-root user execution
- Dropped Linux capabilities
- Resource limits and requests
- Pod anti-affinity (spread across nodes)
- Secret management for API keys

## Monitoring & Troubleshooting

### View Real-time Logs
```bash
./scripts/deploy.sh prod logs backend
./scripts/deploy.sh prod logs frontend
```

### Check Pod Status
```bash
kubectl -n civility-ai get pods -o wide
kubectl -n civility-ai describe pod <pod-name>
```

### Resource Usage
```bash
kubectl -n civility-ai top pods
kubectl -n civility-ai top nodes
```

### Deployment History
```bash
kubectl -n civility-ai rollout history deployment/civility-backend
kubectl -n civility-ai rollout history deployment/civility-frontend
```

### Rollback to Previous Version
```bash
./scripts/deploy.sh prod rollback
```

## Registry

Images are stored in GitHub Container Registry (GHCR):
- `ghcr.io/<your-org>/civility-backend:main`
- `ghcr.io/<your-org>/civility-frontend:main`
- `ghcr.io/<your-org>/civility-backend:sha-<commit-hash>`
- `ghcr.io/<your-org>/civility-frontend:sha-<commit-hash>`

## Image Tags

- `main`, `develop` — Branch names
- `v1.0.0`, `v1.0` — Semantic versions
- `sha-abc123` — Commit SHA

## Port Mappings

| Service | Port | Type |
|---|---|---|
| Backend | 8000 | ClusterIP |
| Frontend | 80 | LoadBalancer |

## Troubleshooting

### Deployment Stuck in Pending
```bash
kubectl -n civility-ai describe pod <pod-name>
# Check: image pull errors, resource constraints, node availability
```

### CrashLoopBackOff
```bash
kubectl -n civility-ai logs <pod-name>
# Check: missing env vars, API connectivity, startup errors
```

### High Memory/CPU Usage
```bash
kubectl -n civility-ai top pods
# Increase limits in deployments.yaml and reapply
```

### ImagePullBackOff
```bash
# Verify GITHUB_TOKEN has registry.permissions.read_packages
# Verify imagePullPolicy: Always is set
kubectl -n civility-ai get imagepullsecrets
```

## Next Steps

1. Add `/health` endpoint to backend
2. Configure DNS records pointing to LoadBalancer IP
3. Set up monitoring (Prometheus/Grafana)
4. Add ingress controller for HTTPS
5. Implement backup/restore strategy for persistent data
