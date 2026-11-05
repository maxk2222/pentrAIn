# Atlas deployment pipeline — repository configuration

## .atlas-ci.yaml (main branch)

```yaml
pipelines:
  pull-request:
    runner: shared-prod-runners
    env:
      - DEPLOY_KEY=prod-registry-key
      - KUBECONFIG=prod-cluster-config
    steps:
      - run: ./ci/build.sh
      - run: ./ci/deploy-preview.sh

  tag-release:
    runner: shared-prod-runners
    steps:
      - run: ./ci/publish.sh
```

## deploy/kustomization.yaml

```yaml
images:
  - name: atlas/app
    newTag: latest
```

## Registry policy (registry.local)

- pull: anonymous
- push: org members
- signature verification on deploy: not enforced

## Runner inventory

| pool | nodes | credentials mounted |
|---|---|---|
| shared-prod-runners | 3 | prod-cluster-config, prod-registry-key |
