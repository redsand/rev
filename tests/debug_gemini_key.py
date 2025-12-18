#!/usr/bin/env python3
"""
Diagnostic script to verify Gemini API key configuration.
Run this to check if your API key is properly loaded.
"""

import os
import sys
from pathlib import Path

def check_gemini_key():
    print("=" * 60)
    print("GEMINI API KEY DIAGNOSTIC")
    print("=" * 60)
    print()

    # Show working directory and expected paths
    print(f"Working directory: {os.getcwd()}")
    print(f"Python: {sys.executable}")
    print()

    # Check 1: Environment variable
    env_key = os.getenv("GEMINI_API_KEY", "")
    if env_key:
        masked = f"{env_key[:10]}...{env_key[-4:]}" if len(env_key) > 14 else "***"
        print(f"✓ Environment variable GEMINI_API_KEY: {masked}")
        print(f"  Length: {len(env_key)} characters")
    else:
        print("✗ Environment variable GEMINI_API_KEY: NOT SET")

    print()

    # Check 2: Config module
    try:
        from rev import config
        # Force reload of API keys
        config._load_saved_api_keys()

        print(f"Config ROOT: {config.ROOT}")
        print(f"Config REV_DIR: {config.REV_DIR}")
        print()

        if config.GEMINI_API_KEY:
            masked = f"{config.GEMINI_API_KEY[:10]}...{config.GEMINI_API_KEY[-4:]}" if len(config.GEMINI_API_KEY) > 14 else "***"
            print(f"✓ Config module GEMINI_API_KEY: {masked}")
            print(f"  Length: {len(config.GEMINI_API_KEY)} characters")
            # Check for whitespace issues
            if config.GEMINI_API_KEY != config.GEMINI_API_KEY.strip():
                print("  ⚠️  WARNING: API key has leading/trailing whitespace!")
        else:
            print("✗ Config module GEMINI_API_KEY: NOT SET")
    except Exception as e:
        print(f"✗ Error loading config: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Check 3: Secrets manager
    try:
        from rev.secrets_manager import get_api_key, SECRETS_FILE
        from rev.secrets_manager import load_secrets

        print(f"Secrets file path: {SECRETS_FILE}")
        print(f"Secrets file exists: {SECRETS_FILE.exists()}")

        if SECRETS_FILE.exists():
            secrets = load_secrets()
            print(f"Secrets found: {list(secrets.keys())}")

        print()

        saved_key = get_api_key("gemini")

        if saved_key:
            masked = f"{saved_key[:10]}...{saved_key[-4:]}" if len(saved_key) > 14 else "***"
            print(f"✓ Saved API key (secrets manager): {masked}")
            print(f"  Length: {len(saved_key)} characters")
            # Check for whitespace issues
            if saved_key != saved_key.strip():
                print("  ⚠️  WARNING: API key has leading/trailing whitespace!")
        else:
            print("✗ Saved API key (secrets manager): NOT FOUND")
            print("  You can save it with: rev save-api-key gemini YOUR_KEY")
    except Exception as e:
        print(f"✗ Error checking secrets: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Check 4: Try to initialize Gemini provider
    try:
        from rev.llm.providers.gemini_provider import GeminiProvider

        print("Testing Gemini provider initialization...")
        provider = GeminiProvider()

        if provider.api_key:
            masked = f"{provider.api_key[:10]}...{provider.api_key[-4:]}" if len(provider.api_key) > 14 else "***"
            print(f"✓ Provider API key: {masked}")
            print(f"  Length: {len(provider.api_key)} characters")
        else:
            print("✗ Provider API key: EMPTY")

    except Exception as e:
        print(f"✗ Error initializing provider: {e}")

    print()

    # Check 5: Try to list models (validates API key)
    try:
        import google.generativeai as genai

        # Determine which key to use
        test_key = env_key or config.GEMINI_API_KEY

        if test_key:
            print("Testing API key validity by listing models...")
            genai.configure(api_key=test_key)
            models = list(genai.list_models())
            print(f"✓ API key is VALID! Found {len(models)} models")
            print("  Available models:")
            for model in models[:5]:  # Show first 5
                if "generateContent" in model.supported_generation_methods:
                    print(f"    - {model.name.replace('models/', '')}")
        else:
            print("✗ Cannot test API key validity - no key found")

    except Exception as e:
        print(f"✗ API key validation FAILED: {e}")
        print("  This likely means your API key is invalid or expired")

    print()
    print("=" * 60)
    print("RECOMMENDATIONS:")
    print("=" * 60)

    final_key = env_key or config.GEMINI_API_KEY

    if not final_key:
        print("❌ No API key found!")
        print()
        print("To fix this, you can either:")
        print("1. Set environment variable:")
        print("   export GEMINI_API_KEY='your-api-key-here'")
        print()
        print("2. Save the key using rev:")
        print("   rev save-api-key gemini your-api-key-here")
        print()
    elif len(final_key) < 20:
        print("⚠️  API key seems too short - it may be invalid")
        print(f"   Current length: {len(final_key)} characters")
        print("   Expected: 39+ characters")
        print()
    else:
        print("✓ API key is configured")
        print()
        print("If you're still getting errors, verify:")
        print("1. The API key is valid at: https://aistudio.google.com/apikey")
        print("2. The Generative Language API is enabled in your Google Cloud project")
        print("3. You have billing enabled (required for Gemini API)")
        print()

if __name__ == "__main__":
    check_gemini_key()
