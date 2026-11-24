# Azure setup

How Kako's Azure side is set up, how to check it, and what went wrong on the way. Keep it current
whenever a resource, role or setting changes. No secrets here: names and steps only.

Kako uses Azure for one thing: model calls to Azure AI Foundry, from `backend/src/kako/agents/model_manager.py`
only (REVIEW.md rule 10). It has its own resource group and budget, separate from every other
project in the subscription.

## What is in place

Status: **in place** (Nov 17, 2026). `check-models` passes from a cloud session and from the laptop.

| Piece | Name | Notes |
| --- | --- | --- |
| Resource group | `kako-rg` | Kako only. Deleting it removes everything below |
| Budget | `kako-monthly` | US$10 monthly, on the resource group; emails at 50%, 80% and 100%. A budget alerts, it does not stop spending |
| Foundry resource and project | `kako-ai`, project `kako` | East US 2, all networks, system-assigned identity |
| Application Insights | `appi-kako-ai-2195` | Added by the Foundry create form by default. Billed only for logs past the monthly free allowance (about 5 GB); for tracing later |
| Deployment, stronger | `gpt-5.4` (`KAKO_MODEL_STRONG`) | Orchestrator and dreaming. Global Standard (pay per token). Generally available, not Preview |
| Deployment, faster | `gpt-5-mini` (`KAKO_MODEL_FAST`) | The four specialists. Global Standard (pay per token). Generally available, not Preview |
| App registration | `kako-dev` | How the backend signs in (Entra ID). Its client secret expires Feb 1, 2027: renew it before then if the video is not yet recorded |
| Role | **Foundry User** on `kako-ai` → `kako-dev` | Lets the app call the models (data plane) |

Not used: API keys (Entra ID only), Key Vault (no secrets to store), Provisioned deployments (they
bill by the hour), any hosted app (the video runs on the laptop; docs/architecture.md).

## Steps

Portal steps, done by Pim, one at a time. Menu names drift; when the portal disagrees, trust the
portal and note the difference under Lessons.

### 1. Resource group

1. In the Azure portal, check the top-right account menu shows your personal directory.
2. Resource groups → Create. Subscription: your own. Name: `kako-rg`. Region: East US 2 (a
   resource group's region only holds its metadata; it doesn't limit where the models run).
3. Review + create → Create.

### 2. Budget

1. Open `kako-rg` → Cost Management → Budgets → Add.
2. Name `kako-monthly`, reset period Monthly, amount US$10 (Pim, Nov 17).
3. Alert conditions: Actual at 50%, 80% and 100%, emailed to your own address.

### 3. Foundry resource and project

1. Search "Foundry" in the portal → Create a Foundry resource. Resource group `kako-rg`, name
   `kako-ai`, region East US 2, default project `kako`, Network: All networks. The form also
   creates an Application Insights resource; keep it.
2. From the resource's overview, copy the endpoint. Either form works for `KAKO_FOUNDRY_ENDPOINT`:
   `https://kako-ai.openai.azure.com` or the project endpoint
   `https://kako-ai.services.ai.azure.com/api/projects/kako`. Kako keeps only the scheme and host.
3. Keys stay unused. Kako never reads them.

### 4. Two pay-per-token deployments

1. In the project: Models + endpoints → Deploy model. Deploy the stronger model, then the faster one.
2. Deployment type **Global Standard** (or Standard). Never Provisioned.
3. Prefer models marked Generally available: Preview models can change or be retired before the
   video. Chosen Nov 17: `gpt-5.4` (stronger) and `gpt-5-mini` (faster), deployment names equal to
   the model names; the Phase 3 agent test set confirms the pair.
4. Note each **deployment name**: that is what goes in `KAKO_MODEL_STRONG` and `KAKO_MODEL_FAST`, and
   it is not always the model's name.

### 5. App registration

1. Microsoft Entra ID → App registrations → New registration. Name `kako-dev`, single tenant, no
   redirect URI.
2. From its Overview, note the **Directory (tenant) ID** and the **Application (client) ID**.
3. Certificates & secrets → New client secret. Expiry after **Jan 24, 2027** (a week past the
   ContextCon deadline). Copy the **Value** (shown once), not the Secret ID, straight into the
   environment settings in step 7. Put a calendar reminder a week before it expires. Set Nov 17:
   expires Feb 1, 2027.

### 6. Role

1. Open the Foundry resource `kako-ai` → Access control (IAM) → Add → Add role assignment.
2. Role **Foundry User** (search "foundry"; it used to be called Azure AI User).
3. Members: User, group, or service principal → `kako-dev` → Review + assign. Allow 5 to 10 minutes.

### 7. Settings

Variables, one per line (see `.env.example`):

```
KAKO_FOUNDRY_ENDPOINT=https://<resource>.openai.azure.com
KAKO_MODEL_STRONG=<deployment name>
KAKO_MODEL_FAST=<deployment name>
KAKO_AZURE_TENANT_ID=<directory (tenant) id>
KAKO_AZURE_CLIENT_ID=<application (client) id>
KAKO_AZURE_CLIENT_SECRET=<client secret value>
```

- **Cloud sessions:** all six in the cloud environment's settings, and the Foundry host
  (`kako-ai.services.ai.azure.com`) under Network access → Allowed domains (added Nov 17). A running session doesn't pick up
  changes, so start a new one after editing.
- **Laptop:** the same six in `kako/.env`, which is gitignored, with its own client secret
  (`kako-laptop`, also expiring Feb 1, 2027), so either secret can be revoked alone. Or the first three only, signed in
  with `az login` instead of the app registration.
- The `KAKO_` prefix keeps these apart from another project's `AZURE_*` variables in a shared
  environment. Kako never reads `AZURE_*` and never uses `DefaultAzureCredential`.

## Spend controls and prices

The Azure budget only alerts; Kako stops spending itself. `ModelManager.chat`
(`backend/src/kako/agents/model_manager.py`) checks every call before sending it:

| Setting | Default | What it does |
| --- | --- | --- |
| `KAKO_TURN_TOKEN_BUDGET` | 200,000 | Tokens one planning turn may use, all its calls together (input, output and hidden reasoning). A call that could pass it (its input, estimated high at one token per 3 UTF-8 bytes plus a little per message and tool, and its output cap) is refused |
| `KAKO_DAILY_SPEND_CAP_USD` | 3 | US$ of real calls per UTC day, summed from `llm_call`. A call whose worst case would pass it is refused |
| `KAKO_MODEL_MAX_RETRIES` | 2 | Retries after a rate limit (honouring `Retry-After`, at most 20 s), a timeout or a server error. Never after a 400 or a sign-in failure |
| `KAKO_PRICE_STRONG_*`, `KAKO_PRICE_FAST_*` | gpt-5.4: 2.50 / 0.25 / 15.00; gpt-5-mini: 0.25 / 0.025 / 2.00 | US$ per million tokens: input, cached input, output. OpenAI's list prices (Nov 2026); Azure's Global Standard prices usually match, but check the [pricing page](https://azure.microsoft.com/pricing/details/azure-openai/) for the deployment type and update these if they differ |
| `KAKO_REASONING_EFFORT_STRONG`, `_FAST` | low | GPT-5 reasoning effort. Hidden reasoning is billed as output |

Each call's worst case is reserved on the turn and on the day before it is sent and released when its
row is written, so specialists running in parallel can't each pass a check only one of them fits. (The
reservation is per backend process; Kako runs one.) A call that times out or loses its connection may
still have been billed, so it is logged at its worst case. Prices must be above 0: a free price would
turn the cap off. Every attempt is an `llm_call` row with its cost, including refused
(`budget_exceeded`) and failed ones. Rough cost of one planning turn at these prices: about US$0.10 to US$0.25 (the orchestrator on
gpt-5.4, four specialists on gpt-5-mini); measured figures go on the metrics page. Tests and CI never
call Foundry; `KAKO_MODEL_MODE=record` does, and needs Pim's yes first.

## Check

From `backend/`:

```
uv run kako check-models
```

Every line must be `[PASS]`: settings, sign-in (as `kako-dev`, or the Azure CLI), then one tiny call
per deployment (at most 256 output tokens each, since GPT-5 models count their hidden reasoning against the cap; one retry). It prints no secret and exits 1 on any
`[FAIL]`. It must pass from a cloud session and from the laptop.

## Verification log

| Date | Where | Result |
| --- | --- | --- |
| Nov 17, 2026 | Cloud session ("First TEst" environment), as `kako-dev` | All four lines `[PASS]`: `gpt-5.4` answered in 1.5 s (13 tokens in, 4 out), `gpt-5-mini` in 1.1 s (13 in, 10 out) |
| Nov 17, 2026 | Pim's Windows laptop (`kako/.env`, `kako-laptop` secret), as `kako-dev` | All four lines `[PASS]`: `gpt-5.4` in 2.8 s (13 in, 4 out), `gpt-5-mini` in 1.6 s (13 in, 10 out) |

## Lessons

| # | What happened | Why | Fix |
| --- | --- | --- | --- |
