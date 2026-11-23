# Contract Review Agent

A local-first, auditable contract-policy review prototype. Given a **plain-text contract**, the CLI evaluates **six predefined company policies** and produces one finding per rule: `COMPLIANT`, `NON_COMPLIANT`, or `NOT_FOUND`, with exact supporting quotations and a human-review flag. **The system is decision support, not a legal approver; a person makes the final decision.**

## Architecture

```text
contract.txt + bundled company policies
                  |
                  v
       OpenAI-compatible LLM
       (structured clause/fact extraction in V2)
                  |
                  v
       Exact quotation verification
                  |
                  v
       Python deterministic policy evaluators
                  |
                  v
       Six findings + human-review flags
                  |
                  v
       CLI JSON output + JSONL audit trail
```

- **V0:** Direct LLM classification.
- **V1:** Direct classification plus exact-evidence validation and escalation for invalid quotations.
- **V2 (default):** One batched structured extraction call; verified candidate evidence; deterministic Python policy evaluation and aggregation to exactly one finding per rule. The LLM extracts facts but does **not** make the final V2 policy classification.

The built-in rules cover termination-for-convenience notice (at least 30 days), supplier invoice payment (within 60 days), aggregate liability cap (no more than total contract fees), Turkish governing law for the agreement and incorporated schedules, mutual confidentiality, and no automatic renewal. See the repository's rule definitions for the exact scope and exceptions.

## Requirements and installation

- Python **3.11+** and `pip`.
- An accessible **OpenAI-compatible chat-completions endpoint** supporting the structured JSON-schema response format used by this project. A local vLLM-served Qwen3-8B-FP8 model is the configuration used for the recorded experiments, but the application does **not** depend on the original developer's machine or model directory.
- Appropriate model runtime/hardware if self-hosting. **No Docker required.**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
# Edit .env to match your OWN model server.
set -a; source .env; set +a
```

**Important:** The Python application reads environment variables; it does **not** load `.env` automatically. Set `LLM_BASE_URL`, `LLM_MODEL`, and optionally `LLM_API_KEY` in the process environment before running the CLI. The `.env` file is ignored by Git.

For a compatible local vLLM installation, an illustrative server startup is:

```bash
vllm serve /path/to/your/model --served-model-name contract-review-qwen3-8b --host 127.0.0.1 --port 8000
```

Use a model/path supported by your vLLM installation. On another computer, both the **model path** and `LLM_MODEL` can differ; `LLM_MODEL` must match the model ID exposed by the server. Check with `curl "$LLM_BASE_URL/models"`. A remote/private endpoint can also be used by changing `LLM_BASE_URL` and credentials; do not expose confidential contracts to an untrusted provider. **Compatibility with arbitrary models/providers is not guaranteed**: the endpoint must support the schema-constrained response used by V2, and extraction quality varies by model.

## Quick start: one contract, one command

With your chosen model server running and environment variables set:

```bash
contract-review review --contract data/contracts/contract_a.txt
```

V2 is the default. Policies are bundled; users do **not** supply a rules argument. Output is JSON containing the six findings and metadata. To compare earlier implementations:

```bash
contract-review review --version v0 --contract data/contracts/contract_a.txt
contract-review review --version v1 --contract data/contracts/contract_a.txt
```

Supported input is a UTF-8 **text** contract. PDF/DOCX ingestion is not implemented. The tool does not sign off on contracts or automatically apply edits.

## Evaluation and reproducibility

The fixed evaluation set consists of **three synthetic contracts**, **six rules**, and **18 expected rule-level findings**. Ground truth: `data/ground_truth.json`. Original V2 metrics are frozen in `eval/baselines/v2_initial.json`.

```bash
# View saved V0/V1/V2 metrics; does NOT call the model.
contract-review eval --version all

# Re-evaluate one version using your currently configured model server.
contract-review eval --version v2 --mode live

# Regression tests.
python -m pytest tests/ -q
```

`--mode live --version all` is **not** supported; select one of `v0`, `v1`, or `v2`. Live evaluation writes to `eval/results/<version>.json`, potentially replacing a previous live result. The frozen V2 baseline is kept separately.

**Metrics:** classification accuracy counts correct statuses among successfully processed rules; violation recall counts detected ground-truth violations across all expected violations; exact-evidence validity checks final findings' exact quotations; human-review recall measures escalation of cases requiring review; end-to-end correctness requires correct status, correct review flag, and valid evidence across all 18 rules. V2 additionally reports clause-level candidate recall and candidate evidence validity.

### Recorded results (separate live inference runs)

| Metric | V0 | V1 | V2 initial |
| --- | ---: | ---: | ---: |
| Classification accuracy | 66.7% | 55.6% | **77.8%** |
| Violation recall | 57.1% | 71.4% | **71.4%** |
| Exact-evidence validity | 50.0% | 33.3% | **100.0%** |
| Human-review recall | 0.0% | 100.0% | **50.0%** |
| Successful contract coverage | 66.7% | 100.0% | **100.0%** |
| End-to-end correctness | 22.2% | 22.2% | **72.2%** |
| Candidate recall | — | — | **84.0%** |

The recorded V2 initial result is **14/18** correct statuses, **5/7** violations detected, **13/18** end-to-end correct findings, and **21/25** relevant clause references recovered. All **21/21** extracted candidate quotations passed exact verification. **These measurements predate a targeted R05 evaluator change and must not be presented as re-measured performance of the latest code.**

**Comparison protocol matters:** V0 and V1 also have a separate **paired replay** (`eval/results/paired_v0_v1.json`) using the same frozen raw V0 model outputs, to isolate evidence-validation behavior. Paired replay is **not** the same as the independently run live V0/V1 results above. V2 uses a different prompt/output task (fact extraction rather than direct classification); V1-to-V2 changes are therefore **not** a controlled single-variable experiment even though dataset and ground truth are shared. Inference can vary across runs and model/server configurations.

**Repository packaging note:** The current `.gitignore` excludes `eval/results/` by default. If you want the public repository's report command to work immediately, explicitly include the selected, reviewed JSON artifacts (or update the ignore policy) before publishing. Never commit raw sensitive contracts, secrets, or unredacted audit logs.

## Failure analysis and limitations

Observed V2 initial failures included missing contract-fee clauses in A/R03 and B/R03; a missed special termination clause in C/R01; a confidentiality-scope evaluator issue in B/R05; and a semantic interpretation error around continued performance in C/R06. A targeted R05 change was made after the frozen baseline, with regression testing required before claiming improved aggregate metrics.

- **Extraction recall is a bottleneck:** Python can only evaluate the facts the model supplies. Candidate recall was 84% on this tiny dataset.
- **Exact quotation ≠ semantic correctness:** verifying quoted text does not prove structured facts correctly interpret that text.
- **Human review is essential:** ambiguous, incomplete, and potentially conflicting terms require legal review. Initial V2 human-review recall was 50%.
- **Evaluation scope is narrow:** three synthetic contracts and 18 labels are not a production legal benchmark, and results cannot be generalized to arbitrary contracts or models.
- **Untrusted contract content:** a contract may contain prompt-injection text. Treat documents as data, never instructions; schema constraints, exact quotation checking, and deterministic evaluation reduce some risks but do not eliminate prompt injection or erroneous interpretations.

## Audit logging, security, and privacy

Review events are appended to `logs/reviews.jsonl`, including request/start/completion/failure events, model outputs, token usage, latency, and final findings; events belonging to one review share a `run_id`. V2 successful and failed call paths were tested. Local Unix file permissions are restricted; logs are excluded from Git.

**Sensitive-data warning:** prompts and raw responses can include full contract terms. Use only an approved local or private endpoint for confidential documents. Do not commit/share logs without reviewing and redacting them. API credentials must never be committed. Production deployments would also require access-control policies, encryption, retention/deletion rules, and stronger secret redaction. Hosting a model on-premises may support data-residency requirements, but this prototype makes no compliance certification claim.

## If there were more time

Improve extraction coverage and semantic fact verification; add adversarial contracts and prompt-injection tests; measure fact-level extraction accuracy; improve applicability/ambiguity handling; and benchmark compatible models in approved on-premises environments. These are **future work**, not implemented V3 features.

## AI assistance and submission artifacts

AI coding assistance was used during prototyping. If submission requires raw AI coding session exports, include them as **separate, reviewed artifacts**, remove credentials and private data, and clearly identify which repository version/experiment each export covers. A README description is **not** a substitute for supplying required exports. Keep the architecture decision record to one page and clearly document human approval boundaries, threat model, and hosting assumptions.
