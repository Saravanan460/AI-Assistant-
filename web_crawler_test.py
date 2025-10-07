# web_crawler_test.py
# A standalone script to test a multi-step, deep-scraping, and summarization process.

import sys
import requests
from bs4 import BeautifulSoup
from googlesearch import search
from litellm import completion
import os
from urllib.parse import urljoin

# --- Configuration ---
os.environ["OPENAI_API_BASE"] = "http://localhost:11434/v1"
os.environ["OPENAI_API_KEY"] = "ollama"

MODEL = "llama3:8b"

def scrape_page_for_links(url: str):
    """
    Scrapes a page to find all links and their text.
    Returns a list of tuples: (link_text, absolute_url)
    """
    print(f"--- Scraping initial page for links: {url} ---")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        for a_tag in soup.find_all('a', href=True):
            link_text = a_tag.get_text(strip=True)
            if link_text:
                # Convert relative URLs to absolute URLs
                absolute_url = urljoin(url, a_tag['href'])
                links.append((link_text, absolute_url))
        return links
    except Exception as e:
        print(f"Error scraping for links: {e}")
        return None

def find_most_relevant_link(links: list, query: str) -> str:
    """
    Uses an LLM to choose the most relevant link from a list by its text,
    then returns the corresponding URL.
    """
    print("--- Using LLM to find the most relevant link... ---")
    
    # Create a dictionary for easy lookup of URL by its text
    link_map = {text: url for text, url in links}
    
    # Format the link texts for the prompt
    link_options = "\n".join([f"- '{text}'" for text, url in links[:40]]) # Limit to first 40 links

    system_prompt = "You are an intelligent navigation assistant. Your task is to analyze a list of link texts from a webpage and select the single most relevant one based on the user's query. Respond with ONLY the exact text of the link you choose."
    
    user_prompt = f"""Based on my original query, which of the following links is the most likely to contain the information I need?

My query: "{query}"

Link texts found on the page:
{link_options}

The exact text of the single most relevant link is:"""

    try:
        response = completion(
            model=f"ollama/{MODEL}",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        # The response should be the text of the link
        chosen_text = response.choices[0].message.content.strip().strip("'\"")
        
        # Look up the URL from the map using the chosen text
        if chosen_text in link_map:
            return link_map[chosen_text]
        else:
            print(f"--- LLM chose a link text ('{chosen_text}') that was not in the original list. Aborting. ---")
            return None

    except Exception as e:
        print(f"An error occurred while choosing a link: {e}")
        return None

def scrape_final_content(url: str) -> str:
    """
    Fetches the content of the final target URL and extracts the main text.
    """
    print(f"--- Performing deep scrape on final URL: {url} ---")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script_or_style in soup(["script", "style", "nav", "footer", "header"]):
            script_or_style.decompose()
        
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        full_text = '\n'.join(chunk for chunk in chunks if chunk)

        if not full_text:
            return "Could not find any meaningful text on the final page."
        return full_text

    except Exception as e:
        return f"Error during final content scrape: {e}"

def summarize_text(text: str, query: str) -> str:
    """
    Uses an LLM to summarize the provided text.
    """
    print("\n--- Summarizing final content with LLM... ---")
    text_to_summarize = text[:8000]
    system_prompt = "You are an expert research assistant. Your goal is to provide a concise, helpful summary of the provided text, focusing on the user's original query."
    user_prompt = f"""Based on the following text, please provide a summary that directly answers my question: "{query}"

Text to summarize:
---
{text_to_summarize}
---

Concise summary:"""
    try:
        response = completion(
            model=f"ollama/{MODEL}",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"An error occurred during summarization: {e}"

def main():
    if len(sys.argv) < 2:
        print("Usage: python web_crawler_test.py \"<your search query>\"")
        sys.exit(1)

    query = sys.argv[1]
    print(f"--- Starting deep research for query: \"{query}\" ---")

    try:
        # Step 1: Find the initial landing page URL
        print("--- Searching for the landing page URL... ---")
        search_results = list(search(query, num_results=1, sleep_interval=2))
        if not search_results:
            print("--- No search results found. ---")
            return
        landing_page_url = search_results[0]

        # Step 2: Scrape the landing page to find all relevant links
        links_on_page = scrape_page_for_links(landing_page_url)
        if not links_on_page:
            print("--- Could not find any links on the landing page. Attempting to scrape it directly. ---")
            final_content_url = landing_page_url
        else:
            # Step 3: Use the LLM to identify the best link to follow
            final_content_url = find_most_relevant_link(links_on_page, query)
            if not final_content_url:
                print("--- LLM could not determine the best link. Aborting. ---")
                return
        
        # Step 4: Scrape the final, most relevant page for its content
        final_text = scrape_final_content(final_content_url)
        if final_text.startswith("Error") or final_text.startswith("Could not find"):
            print(final_text)
            return

        # Step 5: Display the raw text before summarizing, as requested
        print("\n" + "="*20 + " RAW TEXT FOR VERIFICATION " + "="*20)
        print(final_text)
        print("="*65 + "\n")

        # Step 6: Summarize the final text
        summary = summarize_text(final_text, query)

        print("\n--- FINAL SUMMARY ---")
        print(summary)
        print(f"\nSource URL: {final_content_url}")
        print("--- END OF RESEARCH ---")

    except Exception as e:
        print(f"An unexpected error occurred in the main process: {e}")

if __name__ == "__main__":
    main()
