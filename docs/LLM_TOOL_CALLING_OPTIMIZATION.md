# LLM Tool Calling Optimization Guide

This guide explains the configuration options and best practices for optimizing LLM tool calling accuracy and effectiveness, especially when using local models via Ollama.

## Overview

Tool calling (also known as function calling) allows LLMs to invoke structured functions/tools to perform actions. Optimizing this behavior is critical for autonomous agents like `rev` that rely heavily on tool execution.

## Key Improvements Implemented

### 1. **Lower Temperature (0.1)**
- **Parameter**: `OLLAMA_TEMPERATURE`
- **Default**: `0.1`
- **Range**: `0.0` to `2.0`
- **Purpose**: Lower temperature reduces randomness and improves consistency in tool calling
- **Recommendation**:
  - Use `0.1` for tool calling and structured outputs
  - Use `0.7` for creative tasks (documentation, commit messages)

### 2. **Larger Context Window (16K)**
- **Parameter**: `OLLAMA_NUM_CTX`
- **Default**: `16384` (16K tokens)
- **Common values**:
  - `8192` (8K) - Minimum recommended
  - `16384` (16K) - Balanced (default)
  - `32768` (32K) - For complex tasks with large context
- **Purpose**: Allows the model to consider more context when making tool calling decisions
- **Trade-offs**: Higher values use more memory but improve accuracy

### 3. **Enhanced Prompts with Step-by-Step Instructions**
- **Changes**:
  - Added explicit STEP-BY-STEP workflow sections
  - Included tool parameter examples
  - Provided "when to use" guidance for each tool
  - Added CRITICAL sections to emphasize important behaviors
- **Purpose**: Local models benefit from more explicit, detailed instructions
- **Best Practice**: Lead local models "by the nose" with clear, sequential steps

### 4. **Controlled Sampling Parameters**
- **Top-P (nucleus sampling)**: `OLLAMA_TOP_P` (default: `0.9`)
- **Top-K (vocabulary limiting)**: `OLLAMA_TOP_K` (default: `40`)
- **Purpose**: Fine-tune the sampling behavior for more predictable outputs

### 5. **Debug Logging**
- **Parameter**: `OLLAMA_DEBUG=1`
- **Purpose**: View exact prompts sent to the model and generation parameters
- **Usage**: `OLLAMA_DEBUG=1 rev your-command`

## Configuration

### Environment Variables

Set these in your environment or `.env` file:

```bash
# Temperature (0.0-2.0) - lower is more deterministic
export OLLAMA_TEMPERATURE=0.1

# Context window size (in tokens)
export OLLAMA_NUM_CTX=16384

# Top-p sampling (0.0-1.0)
export OLLAMA_TOP_P=0.9

# Top-k sampling (number of tokens)
export OLLAMA_TOP_K=40

# Enable debug logging
export OLLAMA_DEBUG=1
```

### Interactive Configuration (NEW!)

You can also update these settings interactively in the REPL using the `/set` command:

```bash
# Start REPL mode
rev --repl

# View all settings
/set

# Update temperature
/set temperature 0.1

# Update context window
/set num_ctx 16384

# Update top-p
/set top_p 0.9

# Update top-k
/set top_k 40

# Save settings for future sessions
/save

# View current configuration
/config
```

**Available LLM generation settings:**
- `temperature` - LLM temperature (0.0-2.0; lower = more deterministic)
- `num_ctx` - Context window size in tokens (e.g., 8192, 16384, 32768)
- `top_p` - Top-p nucleus sampling (0.0-1.0)
- `top_k` - Top-k vocabulary limiting (positive integer)

### Per-Task Configuration

For specific use cases, you may want different settings:

#### High Accuracy Tool Calling (Default)
```bash
export OLLAMA_TEMPERATURE=0.1
export OLLAMA_NUM_CTX=16384
```

#### Creative Tasks (Documentation, Explanations)
```bash
export OLLAMA_TEMPERATURE=0.7
export OLLAMA_NUM_CTX=8192
```

#### Complex Multi-Step Tasks
```bash
export OLLAMA_TEMPERATURE=0.1
export OLLAMA_NUM_CTX=32768  # More context for complex workflows
```

## Best Practices for Local Models

### 1. **Model Selection**
- Use models specifically fine-tuned for tool calling
- Recommended models:
  - `llama3.1:8b` or larger
  - `qwen2.5:14b` or larger
  - `mistral-small` (22B)
  - `deepseek-coder-v2` for code tasks

### 2. **Context Management**
- Monitor token usage with debug logging
- Keep prompts focused and concise
- Use the automatic context trimming features

### 3. **Prompt Engineering**
- The system prompts now include:
  - Explicit tool parameter schemas
  - Step-by-step workflows
  - When-to-use guidance
  - Critical behavior requirements
- Avoid modifying system prompts unless necessary

### 4. **Debugging Failed Tool Calls**

Enable debug mode to diagnose issues:

```bash
OLLAMA_DEBUG=1 rev your-task
```

Look for:
- **Prompt issues**: Is the prompt clear and explicit?
- **Parameter issues**: Are the generation parameters appropriate?
- **Model issues**: Does the model support tool calling?
- **Context issues**: Is the context window large enough?

Common issues and solutions:

| Issue | Solution |
|-------|----------|
| Model doesn't call tools | Increase temperature slightly (0.15-0.2) or try a different model |
| Tool calls have wrong parameters | Lower temperature, add more examples in prompts |
| Model repeats same tool calls | Already handled by deduplication logic |
| Context overflow errors | Reduce `OLLAMA_NUM_CTX` or enable context trimming |

## Performance Tuning

### Memory vs Accuracy Trade-offs

| num_ctx | Memory Usage | Accuracy | Use Case |
|---------|--------------|----------|----------|
| 4096 | Low | Lower | Simple tasks, limited RAM |
| 8192 | Medium | Good | Most tasks |
| 16384 | High | Better | Complex tasks (default) |
| 32768 | Very High | Best | Multi-file changes, large codebases |

### Speed vs Accuracy Trade-offs

| Temperature | Speed | Accuracy | Consistency |
|-------------|-------|----------|-------------|
| 0.0 | Fastest | Highest | Very High |
| 0.1 | Fast | High | High (default) |
| 0.5 | Medium | Medium | Medium |
| 1.0 | Slow | Lower | Lower |

## Monitoring and Validation

### Enable Detailed Logging

```bash
# Enable LLM debug logging
export OLLAMA_DEBUG=1

# Enable Ollama server logging
ollama serve 2>&1 | tee ollama.log
```

### Check Ollama Model Settings

View current model configuration:
```bash
ollama show <model-name> --modelfile
```

### Metrics to Track

1. **Tool Call Success Rate**: Percentage of correct tool invocations
2. **Parameter Accuracy**: Percentage of tool calls with correct parameters
3. **Task Completion Rate**: Percentage of tasks completed successfully
4. **Iteration Count**: Number of LLM calls needed per task

## Advanced Configuration

### Custom Model Parameters (Modelfile)

You can create a custom Modelfile with optimized parameters:

```
FROM llama3.1:8b

# Tool calling optimizations
PARAMETER temperature 0.1
PARAMETER num_ctx 16384
PARAMETER top_p 0.9
PARAMETER top_k 40

# Optional: Add custom system prompt
SYSTEM """You are an expert at calling tools accurately..."""
```

Save as `Modelfile` and create the model:
```bash
ollama create rev-optimized -f Modelfile
```

Then use it:
```bash
export OLLAMA_MODEL=rev-optimized
rev your-task
```

## Troubleshooting

### Issue: Model doesn't support tool calling

**Symptoms**: No tool calls are made, model only responds with text

**Solutions**:
1. Verify model supports tool calling: `ollama show <model> --modelfile`
2. Try a different model (see recommended models above)
3. Set `REV_MODEL_SUPPORTS_TOOLS=false` to use text-based fallback

### Issue: Out of memory errors

**Symptoms**: Ollama crashes or returns OOM errors

**Solutions**:
1. Reduce context window: `export OLLAMA_NUM_CTX=8192`
2. Use a smaller model
3. Increase system memory or use GPU offloading

### Issue: Tool calls are inconsistent

**Symptoms**: Same task produces different tool calls each time

**Solutions**:
1. Lower temperature: `export OLLAMA_TEMPERATURE=0.05`
2. Use a larger, more capable model
3. Enable debug logging to inspect prompt quality

## Examples

### Example 1: Debugging with Full Logging

```bash
# Enable all debugging
export OLLAMA_DEBUG=1
export REV_LOG_LEVEL=DEBUG

# Run with optimized parameters
export OLLAMA_TEMPERATURE=0.1
export OLLAMA_NUM_CTX=16384

# Execute task
rev "Add error handling to API endpoints"
```

### Example 2: Conservative Settings for Limited Resources

```bash
# Lower memory usage
export OLLAMA_NUM_CTX=8192

# Faster but less accurate
export OLLAMA_TEMPERATURE=0.2

# Smaller model
export OLLAMA_MODEL=llama3.1:8b

rev "Fix typo in README"
```

### Example 3: Maximum Accuracy for Critical Tasks

```bash
# Maximum context
export OLLAMA_NUM_CTX=32768

# Deterministic output
export OLLAMA_TEMPERATURE=0.0

# Best model available
export OLLAMA_MODEL=qwen2.5:32b

rev "Refactor authentication system"
```

## References

- [Ollama API Documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Tool Calling Best Practices](https://ollama.com/blog/tool-support)
- [Model Context Length Comparison](https://ollama.com/library)

## Contributing

If you discover additional optimizations or best practices, please:
1. Test thoroughly with multiple models
2. Document the improvement
3. Submit a pull request with examples

---

**Last Updated**: 2025-12-14
**Related Files**:
- `rev/llm/client.py` - LLM client implementation
- `rev/config.py` - Configuration parameters
- `rev/execution/executor.py` - Execution prompts
- `rev/execution/planner.py` - Planning prompts
