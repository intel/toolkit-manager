# Troubleshooting

[← Docs index](../README.md)

How to check an install, find the error when something fails, and fix the problems that come
up most. Run the commands from the Toolkit Manager folder with `KUBECONFIG` pointing at the
cluster:

```bash
export KUBECONFIG=$(pwd)/env/<env>/kubeconfig.yaml
```

## Check the install

Three commands, from quickest to most thorough. None of them changes anything.

```bash
./toolkit_manager.sh status --health --env <env>   # green or red; exit code 0 or 1
./toolkit_manager.sh status --env <env>            # namespaces, pods, Helm releases, service URLs
./toolkit_manager.sh validate <target> --env <env> # health checks for a layer or one component
```

- **`status --health`** is red when a node is not `Ready`, or a pod is crash-looping, cannot
  pull its image or cannot be scheduled.
- **`validate`** takes a layer (`platform`, `inference`, `agent-toolkit`, `erag`) or a component
  (`keycloak`, `kserve`, ...; `./toolkit_manager.sh show` lists them). It checks that the
  deployments are ready, the endpoints answer and the expected objects exist, and stops at the
  first failed check with the reason.

After layer 3, also send one request to a model: [Say hello](../../README.md#layer-3-intel-inference-toolkit).

## Find the error

Every run writes a log under `env/<env>/logs/`, named `<action>-<target>-<date>-<time>.log`;
the 30 newest are kept. A failed run prints the file name.

```bash
ls -t env/<env>/logs/*.log | head -3
tail -50 "$(ls -t env/<env>/logs/install-*.log | head -1)"
```

For more detail, run again with `TKM_LOG_LEVEL=debug` (adds Ansible's `-vvv`) or `trace`.
Re-running `install` after a fix is safe: what is already installed is left as it is.
Cluster-side logs are in Loki, browsable from Grafana.

## Install

| Symptom | Likely cause / fix |
|---------|--------------------|
| The install stops before Kubespray with a list of node checks (`N1` ... `N19`) | A node failed a pre-flight check; the list names the node and the fix. See [Node checks](../getting-started/prerequisites.md#node-checks-before-install) for each ID and how to skip one. |
| `N8` fails: no HTTPS to github.com or registry.k8s.io | No internet from the node, or the proxy is not set. Set `http_proxy`, `https_proxy` and `no_proxy` in `env/<env>/global_config.yaml`. |
| SSH errors on multi-node | Test `ssh -i <key> <user>@<node> hostname` by hand first; the installer uses the same access. See [Deployment Guide](../deployment/install-platform.md#troubleshooting). |
| Pods in `ImagePullBackOff` | The nodes cannot download images: proxy settings, or a registry rate limit. |
| `kubectl`: "connection to the server localhost:8080 was refused" | `KUBECONFIG` is not set (see the top of this page). |
| A layer you installed is missing after `teardown`, or teardown finds nothing | Environments are separate: tear down and install with the same `--env`. |

## Browser access

| Symptom | Likely cause / fix |
|---------|--------------------|
| The page does not load ("site can't be reached") | The host name does not resolve to the gateway IP. Add every host to `/etc/hosts` (wildcards do not work there): [Access the services](../getting-started/quickstart.md#access-the-services). |
| The page loads directly on the node but not from your laptop | The browser sends the request to the corporate proxy. Add `<domain>` and `*.<domain>` to its proxy bypass list. |
| Certificate warning | Self-signed CA. Copy `env/<env>/logs/ai-solutions-ca.crt` from the deploy node to your machine and trust it: [Trust the self-signed CA](../configuration/configuration.md#trust-the-self-signed-ca-in-your-browser). |
| The sign-in redirects to `keycloak.<domain>` and that page does not load | The Keycloak host needs its own `/etc/hosts` entry and proxy bypass, like the service host. |
| The LiteLLM UI redirects to `http://` and fails | The trailing slash is required: `https://litellm-ui.<domain>/ui/`. |

## Sign-in

| Symptom | Likely cause / fix |
|---------|--------------------|
| The `platform-admin` password from the Secret is refused | It is the temporary one, and it was changed at first login. Reset it in the [Keycloak admin console](../configuration/configuration.md#keycloak-admin-console): realm `platform` → **Users** → `platform-admin` → **Credentials**. |
| `platform-admin` cannot sign in to the Keycloak admin console | Expected: the console uses the `master` realm `admin` account. See [Keycloak admin console](../configuration/configuration.md#keycloak-admin-console). |
| `403` at Headlamp or the LiteLLM UI after signing in | The user is in neither `platform-admins` nor `platform-viewers`. See [Who gets in](../configuration/headlamp.md#who-gets-in). |
| Grafana has no **Sign in with Keycloak** button | `observability_grafana_sso` is `false`, or Keycloak is off. Sign in as the local `admin`: [Observability](../configuration/observability.md#sign-in). |
| No Headlamp at all | It is opt-in: set `headlamp_enabled: true` in `env/<env>/global_config.yaml` and run `install platform` again. |

## Models and requests

| Symptom | Likely cause / fix |
|---------|--------------------|
| No models after `install inference` | Expected unless you asked for them: set `llm_services_deploy_models: true` in `env/<env>/config.inference.yaml` **and** `autodeploy: true` on the model in `env/<env>/models.yaml`. Or run `./model-manager deploy <name> --wait`. |
| `404` "No matching route found" | The `model` field is not a deployed model's name. `./model-manager list --deployed` shows them. |
| `401` "Jwt is expired" or "Jwt is missing" (`auth_type: jwt`) | Keycloak tokens last 15 minutes. Get a new one: `source ./ext/enterprise.ai-inference/model_manager/scripts/get-keycloak-token.sh`. |
| `401` "Authentication Error" (`auth_type: litellm_vkey`) | Wrong, expired or revoked virtual key. |
| Model pod stays `Pending` | Not enough free CPU or memory on any node: `kubectl describe pod -n llm-inference -l app.kubernetes.io/name=<name>`. |

Model deploys, runtimes, CPU pinning and the request path in detail →
[Inference Toolkit troubleshooting](https://github.com/intel/inference-toolkit/blob/main/docs/faq-and-troubleshooting/troubleshooting.md).
Ingress, DNS and the gateway → [Network Architecture](../reference/networking.md#troubleshooting).
The chatbot layer → [Chatbot Toolkit troubleshooting](../getting-started/chatbot-toolkit.md#troubleshooting).

## Report a problem

Open an issue with:

- the command you ran and the log file from `env/<env>/logs/`;
- the output of `./toolkit_manager.sh status --env <env>`;
- the failing `validate` check, if there is one.

Remove passwords, keys and tokens from what you paste, and your domain and IP addresses if
they are private. See [Contributing](../../CONTRIBUTING.md).
