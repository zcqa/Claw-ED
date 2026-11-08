# DeepSeek

Claw-ED can call the official DeepSeek API as an independent provider. It uses
the existing teaching generators, knowledge retrieval, tools, and document
compilers. No additional SDK or optional dependency is required.

## Configure access

Create an API key at [DeepSeek Platform](https://platform.deepseek.com/api_keys).
Then run:

```powershell
clawed config set-key deepseek
clawed config set-model deepseek --model deepseek-flash
clawed config show
```

The key command prompts privately. `DEEPSEEK_API_KEY` is also supported and
takes precedence over the saved key. Keys use the existing keyring / secrets
store and are not added to `config.json`.

In the dashboard, open **Settings**, choose **DeepSeek**, enter the key and
model, and save. Leave the key blank to retain the existing key. Save changes
before using **Test Connection**, which sends a short real request to the saved
model. Configuration changes apply to subsequent chats without restarting a
gateway created from saved configuration.
Use **Refresh available models** to load the saved endpoint's current catalog.

## Models and images

The default is `deepseek-flash`. As checked on 2026-11-08, the official catalog
also lists `deepseek-v4-pro`. Model discovery reads `/models` when credentials
are configured and falls back to a small curated list if discovery is unavailable.
Custom model IDs remain editable.

Flash supports image input. When using a text-only main model, explicitly
select the image-screening model:

```powershell
clawed config set-model deepseek --model deepseek-v4-pro --vision-model deepseek-flash
```

Otherwise, unsupported or failed image checks reject the image, following the
existing image pipeline policy. Claw-ED does not silently switch the model.
To return to screening with the selected main model, clear the image-screening
model in the dashboard.

## Thinking and streaming

Thinking is explicitly disabled by default. Both modes support native tools.
To enable it:

```powershell
clawed config set-model deepseek --thinking --reasoning-effort high --reasoning-tokens 8192 --timeout 300
```

Effort is `low`, `high`, or `max`. The additional reasoning allowance is added
to the answer token budget; larger tasks may need a larger allowance and
timeout. Disable thinking with `--no-thinking`. These settings are also
available on the Settings page. Sampling temperature is omitted in thinking
mode because it has no effect there.

The text streaming interface emits answer content only. Native tool messages
retain the full `content`, `reasoning_content`, and `tool_calls`. The main
gateway stores up to ten complete native turns per teacher and endpoint/model/
thinking-mode combination in the local `memory/sessions.db`. This allows tool
conversations to continue across user turns and process restarts without
truncating reasoning or orphaning tool results. Native histories are separate
from the shortened display transcript and are not replayed to another model.
They contain prompts, tool results, and provider reasoning; protect them like
the rest of the teacher's local working data.

Structured generation requests JSON output and retains existing schema
validation and bounded repairs. Truncated, blank, filtered, interrupted, or
failed responses raise errors instead of reporting success or changing provider.
Thinking settings and the endpoint participate in generation checkpoint hashes.

## Endpoints and task routing

The default base URL is `https://api.deepseek.com`. A base URL ending in `/v1`
also works; do not append `/chat/completions` yourself.

```powershell
clawed config set-model deepseek --base-url https://api.deepseek.com
```

CLI configuration permits HTTPS endpoints and HTTP on localhost. Dashboard
configuration permits the official host; additional proxy hosts require the
server-side `EDUAGENT_DEEPSEEK_ALLOW_HOSTS` comma-separated allowlist. Redirects
are not followed, preventing credentials from being forwarded to another host.

Existing `tier_providers`, `tier_models`, and per-task overrides work with
`deepseek`. Without overrides, the selected model remains in use.

Official references: [API setup](https://api-docs.deepseek.com/),
[thinking and tool history](https://api-docs.deepseek.com/guides/thinking_mode/),
[JSON output](https://api-docs.deepseek.com/guides/json_mode/),
[vision](https://api-docs.deepseek.com/guides/vision/), and
[model discovery](https://api-docs.deepseek.com/api/list-models/).
