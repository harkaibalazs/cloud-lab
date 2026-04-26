# Cluster Prerequisites

The application services (web and ocr) depend on the following infrastructure components that must be installed in the cluster before deploying the manifests.

## Redis

Used by both `web` and `ocr` for storing uploaded images and OCR results.

Install via Helm:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm install redis bitnami/redis --set architecture=standalone
```

The default service endpoint will be `redis-master:6379`. Update the `REDIS_URL` environment variable in `ocr-deploy.yaml` and `web-deploy.yaml` if your release name or namespace differs:

```
redis://<release-name>-master.<namespace>.svc.cluster.local:6379/0
```

## RabbitMQ

Used as the message broker between `web` (producer) and `ocr` (consumer) via a topic exchange.

Install via Helm:

```bash
helm install rabbitmq bitnami/rabbitmq
```

The default service endpoint will be `rabbitmq:5672`. Update the `RABBITMQ_URL` environment variable in `ocr-deploy.yaml` and `web-deploy.yaml` accordingly:

```
amqp://<user>:<password>@<release-name>.<namespace>.svc.cluster.local:5672/%2F
```

Retrieve the auto-generated password:

```bash
kubectl get secret rabbitmq -o jsonpath='{.data.rabbitmq-password}' | base64 -d
```

## Gateway API (for HTTPRoute)

The `httproute.yaml` manifest uses the Kubernetes Gateway API. You need a Gateway API controller and a `Gateway` resource in the cluster.

### Install the Gateway API CRDs

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/latest/download/standard-install.yaml
```

### Install a Gateway controller

Any conformant implementation works. Example using Envoy Gateway:

```bash
helm repo add envoy-gateway https://gateway.envoyproxy.io/charts
helm repo update
helm install envoy-gateway envoy-gateway/gateway-helm -n envoy-gateway-system --create-namespace
```

### Create a Gateway resource

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: gateway
spec:
  gatewayClassName: eg  # matches Envoy Gateway; adjust for your controller
  listeners:
    - name: http
      protocol: HTTP
      port: 80
```

The `parentRefs.name` in `httproute.yaml` must match the Gateway resource name (`gateway` by default).

## Deployment order

1. Install Redis and RabbitMQ
2. Install Gateway API CRDs and controller, create the Gateway resource
3. Apply the application manifests:

```bash
kubectl apply -f manifests/
```
