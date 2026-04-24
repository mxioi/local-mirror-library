# Kubernetes deployment

These manifests deploy the backend API and static frontend in one pod with shared persistent storage.

## Apply

```bash
docker build -t local-mirror:latest .
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

## Notes

- Update `k8s/secret.yaml` before production use.
- `imagePullPolicy: IfNotPresent` assumes local node image availability.
- For multi-node clusters, push image to a registry and update image references.
