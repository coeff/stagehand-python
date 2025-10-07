import asyncio
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from stagehand import Stagehand, StagehandConfig

# Load environment variables
load_dotenv()

# Define Pydantic models for structured data extraction
class Company(BaseModel):
    name: str = Field(..., description="Company name")
    description: str = Field(..., description="Brief company description")

class Companies(BaseModel):
    companies: list[Company] = Field(..., description="List of companies")

async def main():
    # Create configuration for EXTENSION mode
    config = StagehandConfig(
        env="EXTENSION",  # Use Chrome extension!
        model_api_key=os.getenv("OPENAI_API_KEY"),
        model_name="gpt-4o",
        verbose=1
    )

    stagehand = Stagehand(config)

    try:
        print("\nInitializing 🤘 Stagehand in EXTENSION mode...")
        # Initialize Stagehand
        await stagehand.init()

        page = stagehand.page

        print("\n📍 Navigating to aigrant.com...")
        await page.goto("https://www.aigrant.com")

        print("\n🤖 Extracting company data...")
        # Extract companies using structured schema
        companies_data = await page.extract(
          "Extract names and descriptions of 5 companies in batch 3",
          schema=Companies
        )

        # Display results
        print("\n✅ Extracted Companies:")
        for idx, company in enumerate(companies_data.companies, 1):
            print(f"{idx}. {company.name}: {company.description}")

        print("\n👀 Observing Browserbase link...")
        observe = await page.observe("the link to the company Browserbase")
        print("Observe result:", observe)

        print("\n🖱️  Acting on Browserbase link...")
        act = await page.act("click the link to the company Browserbase")
        print("Act result:", act)

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        raise
    finally:
        # Close the client
        print("\n👋 Closing 🤘 Stagehand...")
        await stagehand.close()

if __name__ == "__main__":
    asyncio.run(main())
