import asyncio
import os
import shutil
from playwright.async_api import async_playwright

async def record():
    os.makedirs("demo_videos", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir="demo_videos/raw",
            record_video_size={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        
        print("Navigating to ADK Web UI...")
        await page.goto("http://127.0.0.1:8080")
        await page.wait_for_timeout(3000)

        # Prompt 1
        prompt1 = "Hi! Can you search for a healthy avocado recipe in my collection and check if it fits my dietary preferences?"
        print(f"Sending Prompt 1: {prompt1}")
        
        textarea = page.locator("textarea[placeholder='Type a message...']")
        await textarea.fill(prompt1)
        await page.wait_for_timeout(1000)
        
        send_btn = page.locator("button:has-text('send')")
        await send_btn.click()
        
        # Wait for agent response to complete
        print("Waiting for response 1...")
        await page.wait_for_timeout(15000)

        # Prompt 2
        prompt2 = "Awesome! Can you generate a photo for Avocado Toast with poached egg, and calculate its nutritional macros for 2 servings?"
        print(f"Sending Prompt 2: {prompt2}")
        
        await textarea.fill(prompt2)
        await page.wait_for_timeout(1000)
        await send_btn.click()
        
        # Wait for tool calls (image generation + code executor) and response
        print("Waiting for response 2...")
        await page.wait_for_timeout(25000)

        # Extra delay to view final response clearly
        await page.wait_for_timeout(5000)

        # Close context to flush video file
        video_path = await page.video.path()
        await context.close()
        await browser.close()
        
        final_video = "demo_videos/agent_demo.webm"
        shutil.copy(video_path, final_video)
        print(f"Demo video saved successfully to {final_video} (Size: {os.path.getsize(final_video)} bytes)")

if __name__ == "__main__":
    asyncio.run(record())
