# n8n Workflow Templates

Files in this folder are designed for import into n8n (Workflow → Import from file).

## Important: `jsonBody` fix
In `openrouter-workflow.json`, the `OpenRouter Analyze → jsonBody` field must be a **single line** (no raw line breaks inside the expression value), otherwise n8n will throw an `invalid syntax` error.
