# Multi-Provider LLM Support

Rev now supports multiple commercial LLM providers in addition to Ollama. This allows you to compare different models and determine whether issues are related to LLM quality or prompt design.

## Supported Providers

- **Ollama** - Local and cloud models (default)
- **OpenAI** - GPT-4, GPT-3.5-turbo, and other ChatGPT models
- **Anthropic** - Claude 3, Claude 3.5 Sonnet/Opus/Haiku
- **Google Gemini** - Gemini 2.0 Flash, Gemini Pro, etc.

## Quick Start

### 1. Install Provider Dependencies

```bash
# For OpenAI
pip install openai

# For Anthropic (Claude)
pip install anthropic

# For Google Gemini
pip install google-generativeai
```

### 2. Configure API Keys

You have three options for setting API keys:

#### Option A: Use the /api-key Command (Recommended)
The easiest way - use Rev's built-in command:

```bash
# Start Rev
python -m rev

# Set API keys interactively (input will be hidden)
/api-key set openai
/api-key set anthropic
/api-key set gemini

# View saved keys (masked for security)
/api-key list

# Delete a key
/api-key delete openai
```

Keys are stored securely in `.rev/secrets.json` with restricted file permissions (owner read/write only).

#### Option B: Use Environment Variables
Create a `.env` file (or copy from `.env.example`):

```bash
# OpenAI
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4-turbo-preview

# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Google Gemini
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL=gemini-2.0-flash-exp
```

#### Option C: Use Runtime Settings
Set API keys from within the Rev REPL:

```bash
# Start Rev
python -m rev

# Set API keys using the /set command
/set openai_api_key sk-your-openai-key-here
/set anthropic_api_key sk-ant-your-anthropic-key-here
/set gemini_api_key your-gemini-key-here

# View current keys (masked)
/settings
```

**Priority Order:**
1. Environment variables (highest priority)
2. Saved secrets in `.rev/secrets.json`
3. Not set (will error when trying to use that provider)

### 3. Select Provider

You can select the provider in several ways:

#### Option A: Set Default Provider (Environment Variable)
```bash
export REV_LLM_PROVIDER=openai  # or anthropic, gemini, ollama
```

#### Option B: Auto-detect from Model Name
The system automatically detects the provider based on the model name:

```bash
# Uses OpenAI provider
export OLLAMA_MODEL=gpt-4-turbo-preview

# Uses Anthropic provider
export OLLAMA_MODEL=claude-3-5-sonnet-20241022

# Uses Gemini provider
export OLLAMA_MODEL=gemini-2.0-flash-exp

# Uses Ollama provider (default)
export OLLAMA_MODEL=qwen3-coder:480b-cloud
```

#### Option C: Per-Phase Provider Selection
You can use different providers for different agent phases:

```bash
# Use OpenAI for execution, Claude for planning, Gemini for research
export REV_EXECUTION_PROVIDER=openai
export REV_EXECUTION_MODEL=gpt-4-turbo-preview

export REV_PLANNING_PROVIDER=anthropic
export REV_PLANNING_MODEL=claude-3-5-sonnet-20241022

export REV_RESEARCH_PROVIDER=gemini
export REV_RESEARCH_MODEL=gemini-2.0-flash-exp
```

## Usage Examples

### Example 1: Compare Ollama vs GPT-4

```bash
# Test with Ollama
export REV_LLM_PROVIDER=ollama
export OLLAMA_MODEL=qwen3-coder:480b-cloud
python -m rev "Write a function to calculate fibonacci numbers"

# Test with OpenAI GPT-4
export REV_LLM_PROVIDER=openai
export OPENAI_MODEL=gpt-4-turbo-preview
python -m rev "Write a function to calculate fibonacci numbers"
```

### Example 2: Use Claude for Code Review

```bash
export REV_LLM_PROVIDER=anthropic
export ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
python -m rev "Review the authentication code in src/auth.py"
```

### Example 3: Use Gemini for Research

```bash
export REV_RESEARCH_PROVIDER=gemini
export REV_RESEARCH_MODEL=gemini-2.0-flash-exp
python -m rev "Research the codebase and explain the architecture"
```

## Provider-Specific Configuration

### OpenAI

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo-preview  # or gpt-4, gpt-3.5-turbo
OPENAI_TEMPERATURE=0.1
```

Available models:
- `gpt-4-turbo-preview` - Latest GPT-4 Turbo
- `gpt-4` - GPT-4
- `gpt-3.5-turbo` - Faster, cheaper option

### Anthropic (Claude)

```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_TEMPERATURE=0.1
ANTHROPIC_MAX_TOKENS=8192
```

Available models:
- `claude-3-5-sonnet-20241022` - Latest Claude 3.5 Sonnet
- `claude-3-5-haiku-20241022` - Fast Claude 3.5 Haiku
- `claude-3-opus-20240229` - Most capable Claude 3
- `claude-3-sonnet-20240229` - Balanced Claude 3
- `claude-3-haiku-20240307` - Fast Claude 3

### Google Gemini

```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash-exp
GEMINI_TEMPERATURE=0.1
GEMINI_TOP_P=0.9
GEMINI_TOP_K=40
GEMINI_MAX_OUTPUT_TOKENS=8192
```

Available models:
- `gemini-2.0-flash-exp` - Latest Gemini 2.0 Flash (experimental)
- `gemini-pro` - Gemini Pro
- `gemini-pro-vision` - Gemini Pro with vision

## Architecture

The multi-provider support is implemented using a provider abstraction layer:

```
rev/llm/
├── client.py              # Main client (backward compatible)
├── provider_factory.py    # Provider factory and auto-detection
└── providers/
    ├── base.py           # Base provider interface
    ├── ollama.py         # Ollama provider
    ├── openai_provider.py    # OpenAI provider
    ├── anthropic_provider.py # Anthropic provider
    └── gemini_provider.py    # Gemini provider
```

### How It Works

1. **Provider Factory**: The `provider_factory.py` module detects which provider to use based on:
   - Explicit provider configuration (`REV_LLM_PROVIDER`)
   - Model name pattern matching (e.g., `gpt-4` → OpenAI)
   - Default fallback to Ollama

2. **Provider Interface**: All providers implement the `LLMProvider` base class with:
   - `chat()` - Standard chat completion
   - `chat_stream()` - Streaming chat completion
   - `supports_tool_calling()` - Check if model supports tools
   - `validate_config()` - Validate API keys and configuration
   - `get_model_list()` - List available models

3. **Backward Compatibility**: The existing `ollama_chat()` and `ollama_chat_stream()` functions continue to work and now support all providers.

## Troubleshooting

### API Key Not Found

```
Error: Provider error: OpenAI package not installed
```

**Solution**: Install the required package:
```bash
pip install openai anthropic google-generativeai
```

### Invalid API Key

```
Error: OpenAI API error: Incorrect API key provided
```

**Solution**: Check that your API key is set correctly in `.env` or environment variables.

### Model Not Found

```
Error: The model 'gpt-5' does not exist
```

**Solution**: Use a valid model name. Check the provider's documentation for available models.

### Rate Limiting

Commercial providers have rate limits. If you hit them, you'll see errors like:

```
Error: Rate limit exceeded. Please try again later.
```

**Solution**:
- Wait and retry
- Reduce request frequency
- Upgrade your API plan

## Cost Considerations

Commercial LLM providers charge per token. Here's a rough comparison:

| Provider | Model | Input Cost | Output Cost |
|----------|-------|------------|-------------|
| OpenAI | gpt-4-turbo | $0.01/1K | $0.03/1K |
| OpenAI | gpt-3.5-turbo | $0.0005/1K | $0.0015/1K |
| Anthropic | claude-3-opus | $0.015/1K | $0.075/1K |
| Anthropic | claude-3-sonnet | $0.003/1K | $0.015/1K |
| Anthropic | claude-3-haiku | $0.00025/1K | $0.00125/1K |
| Google | gemini-pro | $0.0005/1K | $0.0015/1K |
| Ollama | local models | Free | Free |
| Ollama | cloud models | Varies | Varies |

**Tip**: Start with cheaper models (GPT-3.5, Claude Haiku, Gemini Pro) for testing, then upgrade to more capable models for production use.

## Comparing LLM Quality

To determine if issues are due to LLM quality or prompts:

1. **Test with Multiple Providers**:
   ```bash
   # Test same task with different providers
   for provider in ollama openai anthropic gemini; do
     export REV_LLM_PROVIDER=$provider
     python -m rev "Your task here" > ${provider}_output.txt
   done
   ```

2. **Compare Results**:
   - If all providers fail → Likely a prompt/tool design issue
   - If only some providers fail → Likely a model capability issue
   - If all succeed but differently → Model-specific behaviors

3. **Check Token Usage**:
   ```bash
   # Monitor token usage across providers
   export REV_LLM_PROVIDER=openai
   python -m rev "Task" --debug
   ```

## Best Practices

1. **Start Local**: Use Ollama for development and testing (free, fast)
2. **Test Commercial**: Use commercial providers to verify quality
3. **Use Per-Phase**: Assign best model for each phase (e.g., GPT-4 for planning, Gemini for research)
4. **Monitor Costs**: Track token usage to control expenses
5. **Iterate Prompts**: If commercial models work but local don't, improve prompts

## Future Enhancements

Planned features:
- [ ] Support for additional providers (Cohere, Mistral AI, etc.)
- [ ] Cost tracking and budgeting
- [ ] Automatic provider fallback on errors
- [ ] Model performance benchmarking
- [ ] Provider-specific optimizations
