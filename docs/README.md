# Toolkit Manager documentation

Start with the table. Each row is one job and one page. The sections under it are the same pages, grouped by folder, for when you already know the area.

> **Toolkit Manager** installs, upgrades and tears down every layer: Kubernetes, the platform, the Intel® Inference Toolkit, and the Intel® Agent Toolkit or Intel® Chatbot Toolkit on top. Run every command from the root of this repository; `init` clones the other repositories under `ext/`. The [project README](../README.md#quick-start) walks up the layers on one machine.

## Find a page

| I want to… | Page |
|---|---|
| Understand the stack and its layers | [Meet Toolkit Manager](overview/meet.md) |
| Check hardware, OS, network and disks before installing | [Prerequisites](getting-started/prerequisites.md) |
| Install on one machine, several machines or an existing cluster | [Getting Started](getting-started/quickstart.md) |
| Deploy a model and call it | [Deploy a model](getting-started/deploy-models.md) |
| Install the Intel® Agent Toolkit | [Getting Started with the Agent Toolkit](getting-started/agent-toolkit.md) |
| Install the Intel® Chatbot Toolkit | [Getting Started with the Chatbot Toolkit](getting-started/chatbot-toolkit.md) |
| Install step by step, with a bastion host or a chosen auth type | [Deployment Guide](deployment/install-platform.md) |
| Spread the cluster over several machines, or use my own cluster | [Multi-node and BYO cluster](deployment/multi-node.md) |
| Add or remove nodes on a running cluster | [Node scaling](deployment/node-scaling.md) |
| Build a cluster on a dedicated high-speed fabric | [Rack-scale deployment](deployment/rack-scale.md) |
| Install on OpenShift | [Deploy on OpenShift](deployment/openshift.md) |
| Use NetApp ONTAP for storage | [NetApp ONTAP and Trident](deployment/netapp-ontap.md) |
| Upgrade, back up or restore a layer | [Upgrade a layer](deployment/upgrade.md) |
| See which YAML file holds a setting | [Configuration](configuration/configuration.md) |
| Use the Kubernetes cluster dashboard and platform sign-in | [Kubernetes cluster dashboard (Headlamp)](configuration/headlamp.md) |
| Open Grafana and read the dashboards | [Observability](configuration/observability.md) |
| Place platform and inference pods on different nodes | [Node topology](configuration/node-topology.md) |
| Pin inference pods to CPU cores | [NRI CPU balloons](configuration/nri-cpu-balloons.md) |
| Connect my application or framework | [Integration guide](reference/integration.md) |
| Look up a command or flag | [CLI reference](reference/cli.md) |
| See how a request reaches a model | [Network architecture](reference/networking.md) |
| See how the installer is built | [Architecture](reference/architecture.md) |
| Check a namespace's security labels | [Namespace security labels](reference/labels.md) |
| Plug in my own solution layer | [Adding solution layers](reference/adding-solutions.md) |
| Get a short answer | [FAQ](faq-and-troubleshooting/frequently-asked-questions.md) |
| Look up a term | [Glossary](reference/glossary.md) |
| Report a bug or change Toolkit Manager | [Contributing](../CONTRIBUTING.md) |

## Folders

| Folder | When you open it |
|---|---|
| `overview/` | Before you install: what Toolkit Manager is |
| `getting-started/` | The first install, a first model and the toolkits on top |
| `deployment/` | Other layouts, platforms and storage, scaling and upgrades |
| `configuration/` | YAML you edit after the first install, and the web UIs it turns on |
| `reference/` | Commands, architecture, networking and terms |
| `faq-and-troubleshooting/` | Answers |

## First install

Do these in order: prerequisites, getting started, then a model.

| Guide | What it covers |
|---|---|
| [Meet Toolkit Manager](overview/meet.md) | What the platform is, the problem it solves, and the layers it deploys |
| [Prerequisites](getting-started/prerequisites.md) | Everything needed before running the installer |
| [Getting Started](getting-started/quickstart.md) | Three deployment paths: pick one and follow it end to end |
| [Deploy a model](getting-started/deploy-models.md) | Deploying, accessing and managing models with `model-manager` |
| [Getting Started with the Agent Toolkit](getting-started/agent-toolkit.md) | Agent sandboxes, memory stores and the LiteLLM gateway on top of inference |
| [Getting Started with the Chatbot Toolkit](getting-started/chatbot-toolkit.md) | Vector database, document ingestion and chat UI on top of inference |

## Other ways to install

| Guide | What it covers |
|---|---|
| [Deployment Guide](deployment/install-platform.md) | Step-by-step install, no Kubernetes experience needed: single machine, several machines, bastion host |
| [Multi-node and BYO cluster](deployment/multi-node.md) | Several machines, or an existing cluster |
| [Node scaling](deployment/node-scaling.md) | `add-node` and `remove-node` on a provisioned cluster |
| [Rack-scale deployment](deployment/rack-scale.md) | The rack profile, star, Clos and L2 topologies, Ceph on the fabric, GPU nodes |
| [Deploy on OpenShift](deployment/openshift.md) | Preparing an OpenShift and OpenShift AI cluster, then installing on top (preview) |
| [NetApp ONTAP and Trident](deployment/netapp-ontap.md) | Trident and ONTAP as the storage backend |
| [Upgrade a layer](deployment/upgrade.md) | Upgrading through `install`, the upgrade checks, backup, restore and rollback |

## After the install

Edit the YAML under `env/<name>/` and re-run `install`.

| Guide | What it covers |
|---|---|
| [Configuration](configuration/configuration.md) | Every option in `global_config.yaml`, and how to override it |
| [Kubernetes cluster dashboard (Headlamp)](configuration/headlamp.md) | The cluster web UI, Keycloak sign-in for every UI, and the API server step on BYO clusters |
| [Observability](configuration/observability.md) | Opening Grafana and signing in: local admin or Keycloak, roles, and the validate checks |
| [Node topology](configuration/node-topology.md) | Separating platform and inference workloads on multi-node clusters |
| [NRI CPU balloons](configuration/nri-cpu-balloons.md) | NUMA-aware CPU pinning for inference pods |

## Connect an application

| Guide | What it covers |
|---|---|
| [Integration guide](reference/integration.md) | Connecting your tool or framework without modifying the stack |
| [CLI reference](reference/cli.md) | `toolkit_manager.sh` and `model-manager` commands and flags |
| [Network architecture](reference/networking.md) | Network topology, IP allocation, and how a request reaches a model |
| [Architecture](reference/architecture.md) | How the modular deployment framework is structured |
| [Namespace security labels](reference/labels.md) | Pod Security Admission and Istio labels applied per namespace |
| [Glossary](reference/glossary.md) | Every term used in these guides, defined once |

## When something fails

| Guide | What it covers |
|---|---|
| [FAQ](faq-and-troubleshooting/frequently-asked-questions.md) | Short answers to the questions that come up most |

## Contribute

| Guide | What it covers |
|---|---|
| [Adding solution layers](reference/adding-solutions.md) | How to create and plug in your own solution layer |
| [Contributing](../CONTRIBUTING.md) | Reporting a problem or sending a change |
