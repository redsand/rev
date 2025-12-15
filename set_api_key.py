#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI tool to set API keys for commercial LLM providers."""

import argparse
import sys
from pathlib import Path

# Add rev to path
sys.path.insert(0, str(Path(__file__).parent))

from rev.secrets_manager import set_api_key, get_api_key, mask_api_key, delete_api_key


def main():
    """Set API keys for commercial LLM providers."""
    parser = argparse.ArgumentParser(
        description="Set API keys for commercial LLM providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set OpenAI API key
  python set_api_key.py openai sk-your-key-here

  # Set Anthropic API key
  python set_api_key.py anthropic sk-ant-your-key-here

  # Set Gemini API key
  python set_api_key.py gemini your-gemini-key-here

  # View current keys (masked)
  python set_api_key.py --list

  # Delete a key
  python set_api_key.py --delete openai
        """
    )

    parser.add_argument(
        "provider",
        nargs="?",
        choices=["openai", "anthropic", "gemini"],
        help="Provider name (openai, anthropic, or gemini)"
    )

    parser.add_argument(
        "api_key",
        nargs="?",
        help="API key to set"
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List current API keys (masked)"
    )

    parser.add_argument(
        "--delete", "-d",
        metavar="PROVIDER",
        help="Delete API key for provider"
    )

    args = parser.parse_args()

    # List keys
    if args.list:
        print("\nSaved API Keys:")
        print("=" * 60)
        for provider in ["openai", "anthropic", "gemini"]:
            api_key = get_api_key(provider)
            masked = mask_api_key(api_key) if api_key else "(not set)"
            print(f"{provider:12} : {masked}")
        print("=" * 60)
        print("\nKeys are stored securely in .rev/secrets.json")
        return 0

    # Delete key
    if args.delete:
        provider = args.delete.lower()
        if provider not in ["openai", "anthropic", "gemini"]:
            print(f"Error: Invalid provider '{provider}'")
            print("Valid providers: openai, anthropic, gemini")
            return 1

        if delete_api_key(provider):
            print(f"✓ Deleted {provider} API key")
        else:
            print(f"No API key found for {provider}")
        return 0

    # Set key
    if not args.provider or not args.api_key:
        parser.print_help()
        return 1

    provider = args.provider.lower()
    api_key = args.api_key.strip()

    if not api_key:
        print("Error: API key cannot be empty")
        return 1

    # Save the API key
    set_api_key(provider, api_key)

    print(f"\n✓ Successfully saved {provider} API key")
    print(f"  Key: {mask_api_key(api_key)}")
    print(f"\nYou can now use {provider} by setting:")
    print(f"  export REV_LLM_PROVIDER={provider}")
    print(f"\nOr the system will auto-detect from model names:")

    if provider == "openai":
        print(f"  export OPENAI_MODEL=gpt-4-turbo-preview")
    elif provider == "anthropic":
        print(f"  export ANTHROPIC_MODEL=claude-3-5-sonnet-20241022")
    elif provider == "gemini":
        print(f"  export GEMINI_MODEL=gemini-2.0-flash-exp")

    print(f"\nAPI key stored securely in .rev/secrets.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
