import requests
from bs4 import BeautifulSoup
import re
import os
from urllib.parse import urlparse
from collections import defaultdict
import json

# Configuration
BASE_URL = "https://dlpsgame.com/list-all-game-ps4/"
OUTPUT_DIR = "ps4_games"
RESULTS_FILE = "organized_results.txt"
LOG_FILE = "scraper.log"
MAX_RETRIES = 3
REQUEST_DELAY = 1
MAX_WORKERS = 5

# Keywords/hosts considered real download links
DOWNLOAD_KEYWORDS = [
    '1fichier.com', 'mediafire.com', 'mega.nz', 'gofile.io',
    'pixeldrain.com', 'zippyshare.com', 'uptobox.com',
    'drive.google.com', 'akirabox.com', 'downloadgameps3.net'
]

# Keywords to ignore (ads, popups, shorteners)
BLOCKED_PATTERNS = [
    'adf.ly', 'shorte.st', 'ouo.io', 'linkvertise', 
    'short.pe', 'rekonise', 'boost.ink', 'spam', 
    'popup', 'ads', 'doubleclick.net', 'redirect',
    'onclick', 'adssettings', 'shrinkearn.com'
]

# Patterns to categorize links
LINK_CATEGORIES = {
    'full_game': [r'\bfull\b', r'\bgame\b', r'\bbase\b', r'\bdownload\b', r'\.pkg$', r'\.iso$'],
    'update': [r'\bupdate\b', r'\bpatch\b', r'v?\d+\.\d+', r'\d+\.\d+\+'],
    'backport': [r'\bbackport\b', r'\bback\s*port\b'],
    'dlc': [r'\bdlc\b', r'\baddon\b', r'\badd-on\b'],
    'mod': [r'\bmod\b', r'\bcheat\b']
}

# Fake browser headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

def setup_directories():
    """Create necessary directories if they don't exist"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def log_message(message, level="INFO"):
    """Log messages to both console and log file"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}"
    
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

def make_request(url):
    """Make HTTP request with retries and delay"""
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = (attempt + 1) * 5
                log_message(f"Retry {attempt + 1} for {url} after error: {e}. Waiting {wait_time}s...", "WARNING")
                time.sleep(wait_time)
            else:
                raise

def get_all_game_urls():
    """Fetch all game URLs from the base page"""
    log_message("Fetching all game URLs...")
    
    try:
        resp = make_request(BASE_URL)
        soup = BeautifulSoup(resp.content, "html.parser")
        game_links = []

        for a in soup.select("div.entry-content a[href]"):
            href = a.get("href", "").strip()
            if href and href.startswith("https://dlpsgame.com/") and not href.endswith("/list-all-game-ps4/"):
                game_links.append(href)

        unique_links = list(set(game_links))
        log_message(f"Found {len(unique_links)} unique game URLs.")
        return unique_links
    except Exception as e:
        log_message(f"Failed to fetch game URLs: {e}", "ERROR")
        return []

def clean_title(title):
    """Clean and sanitize game title for filename use"""
    if not title or title == "None":
        return "Unknown_Game"
        
    # Remove special characters and extra whitespace
    title = re.sub(r'[\\/*?:"<>|]', "", title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title[:100]  # Limit length to prevent filesystem issues

def extract_metadata(soup):
    """Extract metadata from the page"""
    metadata = {
        'title': 'Unknown Game',
        'language': 'Unknown',
        'release_year': 'Unknown',
        'genre': 'Unknown',
        'description': 'No description available'
    }

    # Extract title from page title (removing site name)
    title = soup.title.string if soup.title else "Unknown Game"
    metadata['title'] = re.sub(r' - Download Game PSX PS2 PS3 PS4 PS5$', '', title)

    # Extract from info table if available
    info_table = soup.find('table', {'border': '7'})
    if info_table:
        rows = info_table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) == 2:
                key = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                
                if 'name' in key:
                    metadata['title'] = value
                elif 'language' in key:
                    metadata['language'] = value
                elif 'release' in key:
                    metadata['release_year'] = value
                elif 'genre' in key:
                    metadata['genre'] = value

    # Extract description from blockquote if available
    blockquote = soup.find('blockquote')
    if blockquote:
        metadata['description'] = blockquote.get_text(strip=True)

    return metadata

def categorize_link(link_text, href):
    """Categorize a link based on its text and URL"""
    link_text = link_text.lower()
    href = href.lower()
    
    # First check for specific patterns in the URL
    if any(ext in href for ext in ['.pkg', '.iso']):
        return 'full_game'
    
    # Then check text patterns
    for category, patterns in LINK_CATEGORIES.items():
        for pattern in patterns:
            if re.search(pattern, link_text) or re.search(pattern, href):
                return category
                
    return 'other'

def extract_download_links(soup):
    """Extract and categorize download links from the page"""
    categorized_links = defaultdict(list)
    
    # First check the download spoiler section
    spoiler = soup.find('div', class_='su-spoiler-content')
    if spoiler:
        for p in spoiler.find_all('p'):
            text = p.get_text(strip=True)
            for a in p.find_all('a', href=True):
                href = a['href']
                link_text = a.get_text(strip=True)
                
                if (any(key in href.lower() for key in DOWNLOAD_KEYWORDS) and 
                    not any(bad in href.lower() for bad in BLOCKED_PATTERNS)):
                    
                    # Normalize URL
                    parsed = urlparse(href)
                    if not parsed.scheme:
                        href = f"https://{href}"
                    
                    category = categorize_link(link_text + ' ' + text, href)
                    categorized_links[category].append({
                        'url': href,
                        'text': link_text,
                        'context': text.replace(link_text, '').strip()
                    })

    # Also check regular links in the content
    content = soup.find('div', class_='post-body')
    if content:
        for a in content.find_all('a', href=True):
            href = a['href']
            link_text = a.get_text(strip=True)
            
            if (any(key in href.lower() for key in DOWNLOAD_KEYWORDS) and \
               not any(bad in href.lower() for bad in BLOCKED_PATTERNS):
                
                # Skip if already found in spoiler
                if not any(href in link['url'] for links in categorized_links.values() for link in links):
                    parsed = urlparse(href)
                    if not parsed.scheme:
                        href = f"https://{href}"
                    
                    category = categorize_link(link_text, href)
                    categorized_links[category].append({
                        'url': href,
                        'text': link_text,
                        'context': ''
                    })

    return categorized_links

def extract_game_info(url):
    """Extract game information from a game page"""
    log_message(f"Processing: {url}")
    
    try:
        resp = make_request(url)
        soup = BeautifulSoup(resp.content, "html.parser")

        # Extract metadata
        metadata = extract_metadata(soup)
        title = clean_title(metadata['title'])

        # Extract and categorize links
        categorized_links = extract_download_links(soup)

        return {
            'title': title,
            'metadata': metadata,
            'links': categorized_links,
            'url': url
        }
    except Exception as e:
        log_message(f"Error processing {url}: {e}", "ERROR")
        return None

def save_game_details(game_info):
    """Save game details to individual file and results file"""
    if not game_info or not any(game_info['links'].values()):
        log_message(f"Skipping {game_info['title']} (no valid download links)", "WARNING")
        return

    try:
        # Save to individual JSON file
        file_path = os.path.join(OUTPUT_DIR, f"{game_info['title']}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(game_info, f, indent=2, ensure_ascii=False)

        # Append to organized results file
        with open(RESULTS_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Game: {game_info['title']}\n")
            f.write(f"URL: {game_info['url']}\n")
            f.write(f"Year: {game_info['metadata']['release_year']}\n")
            f.write(f"Genre: {game_info['metadata']['genre']}\n")
            f.write(f"Language: {game_info['metadata']['language']}\n")
            f.write(f"\nDescription:\n{game_info['metadata']['description']}\n\n")
            
            # Write links in specific order
            for category in ['full_game', 'update', 'backport', 'dlc', 'mod', 'other']:
                if game_info['links'].get(category):
                    f.write(f"{category.replace('_', ' ').title()}:\n")
                    for link in game_info['links'][category]:
                        context = f" ({link['context']})" if link['context'] else ""
                        f.write(f"- {link['text']}{context}: {link['url']}\n")
                    f.write("\n")

        log_message(f"Saved info for {game_info['title']} with {sum(len(v) for v in game_info['links'].values())} links")
    except Exception as e:
        log_message(f"Failed to save details for {game_info['title']}: {e}", "ERROR")

def process_game(url):
    """Process a single game URL"""
    try:
        game_info = extract_game_info(url)
        if game_info and game_info['links']:
            save_game_details(game_info)
            return True
        return False
    except Exception as e:
        log_message(f"Failed to process {url}: {e}", "ERROR")
        return False

def main():
    """Main execution function"""
    import argparse
    parser = argparse.ArgumentParser(description="PS4 Game Scraper")
    parser.add_argument("--threads", type=int, default=MAX_WORKERS,
                       help=f"Number of concurrent threads (default: {MAX_WORKERS})")
    args = parser.parse_args()

    setup_directories()
    
    # Clear results file
    open(RESULTS_FILE, "w").close()
    open(LOG_FILE, "w").close()

    log_message("Starting PS4 Game Scraper")
    start_time = time.time()

    urls = get_all_game_urls()
    if not urls:
        log_message("No game URLs found. Exiting.", "ERROR")
        return

    # Process URLs with thread pool
    successful = 0
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {executor.submit(process_game, url): url for url in urls}
        
        for future in as_completed(futures):
            url = futures[future]
            try:
                if future.result():
                    successful += 1
            except Exception as e:
                log_message(f"Unexpected error processing {url}: {e}", "ERROR")

    elapsed = time.time() - start_time
    log_message(f"Completed! Processed {len(urls)} games, {successful} successful. Time taken: {elapsed:.2f} seconds")

if __name__ == "__main__":
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    main()