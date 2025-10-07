"""
Example: Using Stagehand with Chrome Extension

This example demonstrates how to use Stagehand in EXTENSION mode,
which allows you to control your existing Chrome browser instead of
launching a new one.

Prerequisites:
1. Start the extension server: python server/extension_server.py
2. Load the extension in Chrome from chrome_extension/ folder
3. Have a Chrome tab open
4. Run this script: python examples/extension_example.py
"""

import asyncio
from stagehand import Stagehand


async def main():
    print("\n🤘 Stagehand Extension Mode Example")
    print("=" * 50)

    # Create Stagehand instance in EXTENSION mode
    async with Stagehand(env="EXTENSION", verbose=1) as stagehand:
        page = stagehand.page

        print("\n✅ Connected to Chrome extension!")
        current_url = await page.url()
        print(f"   Current URL: {current_url}")

        # Navigate to Y Combinator
        print("\n📍 Navigating to Y Combinator...")
        await page.goto("https://ycombinator.com")

        # Extract data using AI
        print("\n🤖 Extracting company data from batch 3...")
        companies = await page.extract(
            instruction="Extract names and descriptions of 5 companies in batch 3"
        )

        print("\n📊 Extracted Companies:")
        print(companies)

        # Observe an element
        print("\n👀 Looking for the Browserbase link...")
        observe_results = await page.observe("the link to the company Browserbase")

        if observe_results:
            print(f"\n✅ Found Browserbase link!")
            print(f"   Selector: {observe_results[0].selector}")
            print(f"   Description: {observe_results[0].description}")

            # Click on it using AI
            print("\n🖱️  Clicking on Browserbase link...")
            result = await page.act("click the link to the company Browserbase")
            print(f"   Result: {result}")

            # Wait a bit to see the navigation
            await asyncio.sleep(2)
            new_url = await page.url()
            print(f"\n📍 New URL: {new_url}")

        print("\n✅ Example completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
