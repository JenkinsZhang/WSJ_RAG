"""
Command-line interface for the News Agent.

Provides an interactive chat interface for querying news.

Usage:
    python -m src.agent.cli
    python -m src.agent.cli --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("opensearch").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


def print_banner() -> None:
    """Print welcome banner."""
    print()
    print("=" * 60)
    print("  WSJ News Agent - Powered by LlamaIndex + Bedrock Claude")
    print("=" * 60)
    print()
    print("支持中英文提问，自动识别意图，所有回答使用中文。")
    print()
    print("示例问题:")
    print("  - 帮我总结一下最近的独家科技新闻")
    print("  - 特斯拉最近有什么新闻？")
    print("  - What's happening with Federal Reserve?")
    print("  - 今天有什么重要的商业新闻？")
    print()
    print("关键词: 独家(exclusive) | 总结(summarize) | 最近/今天")
    print()
    print("命令:")
    print("  exit, quit, q  - 退出")
    print("  clear, cls     - 清屏")
    print("  help, ?        - 显示帮助")
    print()
    print("-" * 60)


def clear_screen() -> None:
    """Clear the terminal screen."""
    import os
    os.system('cls' if os.name == 'nt' else 'clear')


async def chat_loop(verbose: bool = False) -> None:
    """Main chat loop."""
    from src.agent.news_agent import NewsAgent

    print_banner()

    # Initialize agent
    print("Initializing agent...")
    agent = NewsAgent(verbose=verbose)

    # Warm up the agent by accessing it
    _ = agent.agent
    print("Agent ready!")
    print()

    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() in ('exit', 'quit', 'q'):
                print("\nGoodbye!")
                break

            if user_input.lower() in ('clear', 'cls'):
                clear_screen()
                print_banner()
                continue

            if user_input.lower() in ('help', '?'):
                print_banner()
                continue

            # Send to agent
            print("\nAgent: ", end="", flush=True)

            try:
                response = await agent.chat(user_input)
                print(response)
            except Exception as e:
                print(f"\n[Error] {e}")

            print()

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except EOFError:
            print("\n\nGoodbye!")
            break


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WSJ News Agent - Interactive news Q&A"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show verbose agent output",
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Single query mode (non-interactive)",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.query:
        # Single query mode
        from src.agent.news_agent import NewsAgent
        agent = NewsAgent(verbose=args.verbose)
        response = agent.chat_sync(args.query)
        print(response)
    else:
        # Interactive mode
        asyncio.run(chat_loop(args.verbose))


if __name__ == "__main__":
    main()
