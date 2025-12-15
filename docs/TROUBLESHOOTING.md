# Troubleshooting Guide for rev

## Quick Diagnostics

Run these commands first to diagnose issues:

```bash
# 1. Check if Ollama is running
curl http://localhost:11434/api/version

# 2. List available models
ollama list

# 3. Test rev with debug mode
OLLAMA_DEBUG=1 rev --model qwen3-coder:480b-cloud "test task"

# 4. Check Ollama logs (if running as service)
# macOS:
tail -f ~/Library/Logs/Ollama/server.log
# Linux:
journalctl -u ollama -f
# Docker:
docker logs ollama -f
```

---

## Common Issues

### 1. "Connection refused" or "Cannot connect to Ollama"

**Error Message:**
```
Error: Ollama API error: Connection refused
```

**Diagnosis:**
```bash
# Check if Ollama is running
curl http://localhost:11434/api/version

# Expected output:
# {"version":"0.1.x"}

# If connection refused:
# Ollama is not running
```

**Solutions:**

#### A. Ollama Not Installed
```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows
# Download from https://ollama.ai
```

#### B. Ollama Not Running
```bash
# Start Ollama
ollama serve

# Or run in background (macOS/Linux)
nohup ollama serve > /dev/null 2>&1 &

# Or as system service (Linux)
sudo systemctl start ollama
sudo systemctl enable ollama  # Start on boot
```

#### C. Ollama Running on Different Port
```bash
# If Ollama is on custom port (e.g., 8080)
export OLLAMA_BASE_URL="http://localhost:8080"
rev --base-url http://localhost:8080 "task"
```

#### D. Ollama Running on Remote Host
```bash
# If Ollama is on remote server
export OLLAMA_BASE_URL="http://remote-server:11434"
rev --base-url http://remote-server:11434 "task"
```

---

### 2. "Model not found" (404 Error)

**Error Message:**
```
Error: Ollama API error: 404 Client Error: Not Found
{"error":"model 'qwen3-coder:480b-cloud' not found"}
```

**Diagnosis:**
```bash
# List all pulled models
ollama list

# Expected output:
# NAME                     ID              SIZE
# qwen3-coder:480b-cloud      123abc...       3.8GB
# llama3.1:latest         456def...       4.7GB
```

**Possible Causes & Solutions:**

#### A. Ollama Was Updating or Not Running
This is the **most common** cause! If you see this error, first check:

```bash
# Check if Ollama is running
curl http://localhost:11434/api/version

# If no response, start Ollama:
ollama serve
```

**Why this happens:**
- Ollama auto-updates in background
- Ollama crashed or was restarted
- System reboot without auto-start configured

**Solution:**
Just start Ollama again. Your models are still downloaded.

#### B. Local Model Not Pulled
If using a local model (not `-cloud` suffix):

```bash
# Pull the model
ollama pull qwen3-coder:latest
ollama pull qwen2.5:14b
ollama pull llama3.1:70b

# Verify it's available
ollama list
```

#### C. Cloud Model (Requires Authentication)
If model ends with `-cloud` (e.g., `qwen3-coder:480b-cloud`):

**Cloud models require Ollama to be running** to proxy the request to Ollama's cloud API.

1. **Ensure Ollama is running:**
   ```bash
   ollama serve
   ```

2. **Try the model:**
   ```bash
   rev --model qwen3-coder:480b-cloud "test"
   ```

3. **Authenticate when prompted:**
   ```
   ============================================================
   OLLAMA CLOUD AUTHENTICATION REQUIRED
   ============================================================
   1. Visit this URL: https://ollama.com/connect?key=...
   2. Sign in with Ollama account
   3. Authorize device

   Press Enter after authentication...
   ```

4. **Visit the URL in browser** and complete authentication

5. **Press Enter** to continue

#### D. Typo in Model Name
```bash
# Check exact model name
ollama search qwen3

# Use exact name from search results
rev --model qwen3-coder:480b-cloud "task"
```

#### E. Model Version Not Available
```bash
# Try different version
ollama pull qwen3-coder:latest  # Instead of specific version
ollama pull llama3.1:8b         # Instead of 70b if storage limited
```

---

### 3. "401 Unauthorized" for Cloud Models

**Error Message:**
```
OLLAMA CLOUD AUTHENTICATION REQUIRED

Model 'qwen3-coder:480b-cloud' requires authentication.
```

**This is Normal!** Cloud models require authentication on first use.

**Steps:**

1. **Ensure Ollama is running** (cloud models proxy through Ollama):
   ```bash
   ollama serve
   ```

2. **Run rev with cloud model:**
   ```bash
   rev --model qwen3-coder:480b-cloud "test task"
   ```

3. **You'll see authentication prompt:**
   ```
   ============================================================
   OLLAMA CLOUD AUTHENTICATION REQUIRED
   ============================================================

   Model 'qwen3-coder:480b-cloud' requires authentication.

   To authenticate:
   1. Visit this URL in your browser:
      https://ollama.com/connect?name=YOUR-DEVICE&key=...

   2. Sign in with your Ollama account
   3. Authorize this device
   ============================================================

   Press Enter after completing authentication, or Ctrl+C to cancel...
   ```

4. **Open the URL in browser**
5. **Sign in** with Ollama account (create one if needed at https://ollama.com)
6. **Authorize** your device
7. **Press Enter** in terminal

8. **Authentication persists** - you only do this once per device

**Troubleshooting Authentication:**

- **"Authentication still failing"** - Check network connection, VPN, firewall
- **"Can't create Ollama account"** - Visit https://ollama.com to sign up
- **"Want to cancel"** - Press `Ctrl+C` instead of Enter
- **"Want to re-authenticate"** - Clear Ollama session and retry

---

### 4. "Model doesn't support tools" (400 Error with Tools)

**Error/Warning:**
```
[DEBUG] Got 400 with tools, retrying without tools...
```

**This is Normal!** rev automatically handles this.

**What's Happening:**
1. rev sends request with function calling tools (for better results)
2. Older models don't support tools → return 400 error
3. rev automatically retries **without** tools
4. Task continues with limited functionality

**Models Without Tool Support:**
- `codellama:*` (all versions)
- `deepseek-coder:*` (most versions)
- Older/legacy models

**Models With Tool Support (Recommended):**
- `llama3.1:*` (8B, 70B, 405B) ✅
- `qwen2.5:*` (7B and up) ✅
- `mistral-nemo`, `mistral-large` ✅
- Cloud models (qwen3-coder:480b-cloud, etc.) ✅

**Solution:**
```bash
# Use a model with tool support for best results
ollama pull llama3.1:latest
rev --model llama3.1:latest "task"

# Or use cloud model
rev --model qwen3-coder:480b-cloud "task"
```

**No Action Needed:** If you see this message, rev is handling it automatically. Your task will still complete.

---

### 5. Request Timeout

**Error Message:**
```
[DEBUG] Request timed out after 600s, will retry with longer timeout...
```

**What's Happening:**
- Complex task taking longer than 10 minutes
- rev automatically retries with longer timeouts (20m, then 30m), and keeps retrying with backoff when configured to do so
- This is normal for large codebases or complex tasks

**Timeout Schedule:**
- Attempt 1: 10 minutes (600s)
- Attempt 2: 20 minutes (1200s)
- Attempt 3+: 30 minutes (1800s, capped) with continued retries if `OLLAMA_MAX_RETRIES` > 3

**Solutions:**

#### A. Wait for Retry (Recommended)
rev will automatically retry with longer timeout. Just wait.

#### B. Use Faster Model
```bash
# Use smaller, faster model for simple tasks
ollama pull qwen2.5:7b
rev --model qwen2.5:7b "task"

# Save large models for complex tasks
rev --model llama3.1:70b "complex refactoring"
```

#### C. Break Down Task
```bash
# Instead of:
rev "Refactor entire authentication system"

# Try:
rev "Review authentication code"
# Then separately:
rev "Refactor login logic into separate service"
# Then:
rev "Update tests for refactored auth"
```

#### D. Use Cloud Model (Faster Hardware)
```bash
# Cloud models run on powerful servers
rev --model qwen3-coder:480b-cloud "complex task"
```

---

### 6. "--model Parameter Not Working"

**Symptom:**
```bash
rev --model llama3.1:latest "task"
# Shows: Model: llama3.1:latest
# But actually uses: qwen3-coder:480b-cloud (wrong!)
```

**Status:** **FIXED** in commit `3088c5d` (Nov 21, 2024)

**If You Still See This:**

1. **Update rev:**
   ```bash
   git pull origin main
   pip install -r requirements.txt
   ```

2. **Verify fix:**
   ```bash
   grep "from rev import config" rev/llm/client.py
   # Should return: from rev import config
   ```

3. **Test:**
   ```bash
   OLLAMA_DEBUG=1 rev --model llama3.1:latest "test"
   # Look for: [DEBUG] Model: llama3.1:latest
   ```

**If problem persists, check:**
```python
# In rev/llm/client.py, line 11 should be:
from rev import config  # CORRECT

# NOT:
from rev.config import OLLAMA_MODEL  # WRONG
```

---

### 7. Ollama Running But Still Connection Errors

**Symptoms:**
- `ollama list` works
- `ollama serve` is running
- rev still can't connect

**Diagnosis:**
```bash
# Test exact endpoint rev uses
curl -X POST http://localhost:11434/api/chat \
  -d '{"model":"qwen3-coder:480b-cloud","messages":[{"role":"user","content":"test"}],"stream":false}'

# Should return JSON response
```

**Possible Causes:**

#### A. Firewall Blocking Localhost
```bash
# Check firewall (Linux)
sudo ufw status
sudo ufw allow 11434/tcp

# Check firewall (macOS)
# System Preferences → Security & Privacy → Firewall
```

#### B. Port Already in Use
```bash
# Check what's on port 11434
lsof -i :11434
netstat -an | grep 11434

# If another process is using it, either:
# 1. Stop that process
# 2. Run Ollama on different port:
OLLAMA_PORT=8080 ollama serve
# Then:
rev --base-url http://localhost:8080 "task"
```

#### C. VPN or Proxy Issues
```bash
# Temporarily disable VPN/proxy
# Or configure rev to use proxy:
export http_proxy=http://proxy:8080
export https_proxy=http://proxy:8080
rev "task"
```

#### D. Docker Networking (If Ollama in Docker)
```bash
# If running Ollama in Docker
docker run -d -p 11434:11434 --name ollama ollama/ollama

# Verify port mapping
docker port ollama
# Should show: 11434/tcp -> 0.0.0.0:11434

# Test from host
curl http://localhost:11434/api/version
```

---

### 8. Performance Issues / Very Slow

**Symptoms:**
- Requests taking very long (>30 minutes)
- No error, just slow

**Solutions:**

#### A. Use Smaller Model
```bash
# Check model sizes
ollama list

# Use smaller variant
ollama pull qwen2.5:7b    # ~4GB
ollama pull llama3.1:8b   # ~5GB

# Instead of:
# llama3.1:70b (~40GB)
# qwen3-coder:480b-cloud
```

#### B. Check System Resources
```bash
# Monitor CPU/RAM during request
# Linux:
htop
# macOS:
Activity Monitor

# If RAM is maxed:
# - Close other applications
# - Use smaller model
# - Add swap space (Linux)
```

#### C. GPU Acceleration (If Available)
```bash
# Check if Ollama is using GPU
ollama ps

# If not using GPU but you have one:
# 1. Install CUDA (NVIDIA) or ROCm (AMD)
# 2. Restart Ollama
# Ollama auto-detects GPU

# Verify GPU usage:
nvidia-smi  # NVIDIA
# or
rocm-smi    # AMD
```

#### D. Use Cloud Model
```bash
# Cloud models run on Ollama's servers (faster)
rev --model qwen3-coder:480b-cloud "task"
```

---

## Environment Variables Reference

```bash
# Ollama Configuration
export OLLAMA_BASE_URL="http://localhost:11434"  # Default
export OLLAMA_MODEL="qwen3-coder:480b-cloud"           # Default

# Debug Mode
export OLLAMA_DEBUG=1  # Enable verbose logging

# Network (if using proxy)
export http_proxy="http://proxy:8080"
export https_proxy="http://proxy:8080"

# Ollama Server Configuration (when running ollama serve)
export OLLAMA_HOST="0.0.0.0:11434"  # Listen on all interfaces
export OLLAMA_PORT="8080"            # Custom port
export OLLAMA_MODELS="/path/to/models"  # Custom model directory
```

---

## Debug Mode Usage

Enable debug mode to see detailed API interactions:

```bash
# Method 1: Environment variable
export OLLAMA_DEBUG=1
rev "task"

# Method 2: Inline
OLLAMA_DEBUG=1 rev --model llama3.1:latest "test task"
```

**Debug Output Includes:**
```
[DEBUG] Ollama request to http://localhost:11434/api/chat
[DEBUG] Model: qwen3-coder:480b-cloud
[DEBUG] Messages: [{"role": "user", "content": "..."}]
[DEBUG] Tools: 41 tools provided
[DEBUG] Response status: 200
[DEBUG] Response: {"message": ...}
```

**Use Cases:**
- Verify correct model is being used
- Check API request/response
- Diagnose authentication issues
- Debug timeout problems

---

## Getting Help

### 1. Check Ollama Status
```bash
ollama --version
ollama list
curl http://localhost:11434/api/version
```

### 2. Check rev Version
```bash
git log --oneline -1
# Should show recent commit with model fix
```

### 3. Collect Debug Information
```bash
# Run with debug mode
OLLAMA_DEBUG=1 rev --model YOUR_MODEL "test task" 2>&1 | tee debug.log

# Share debug.log when reporting issues
```

### 4. Test Ollama Directly
```bash
# Test without rev
ollama run qwen3-coder:480b-cloud "Write a hello world function"

# If this works but rev doesn't:
# - Check rev configuration
# - Verify Python dependencies
# - Check for firewall/proxy
```

### 5. Report Issue
When reporting bugs, include:
- **Ollama version:** `ollama --version`
- **Python version:** `python --version`
- **Operating system:** `uname -a` (Linux/macOS) or `ver` (Windows)
- **Model being used:** e.g., `qwen3-coder:480b-cloud`
- **Error message:** Full error output
- **Debug log:** Output from `OLLAMA_DEBUG=1`
- **Steps to reproduce**

---

## Quick Command Reference

```bash
# Verify Ollama is running
curl http://localhost:11434/api/version

# List models
ollama list

# Pull a model
ollama pull llama3.1:latest

# Start Ollama
ollama serve

# Test rev with debug
OLLAMA_DEBUG=1 rev --model qwen3-coder:480b-cloud "test"

# Use custom Ollama URL
rev --base-url http://remote:11434 "task"

# Use cloud model
rev --model qwen3-coder:480b-cloud "task"

# Check Ollama logs (Linux service)
journalctl -u ollama -f

# Check Ollama logs (macOS)
tail -f ~/Library/Logs/Ollama/server.log
```
