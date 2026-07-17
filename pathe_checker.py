#!/usr/bin/env python3
import os
import re
import json
import urllib.request
import urllib.parse
import datetime
import sys

# Configuration Defaults
URL = "https://www.pathe.nl/en/films"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Referer': 'https://www.google.com/'
}

def log(message, log_file=None, data_dir=None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    if log_file and data_dir:
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted_msg + "\n")
        except Exception as e:
            print(f"Failed to write to log file: {e}", file=sys.stderr)

def send_notification(title, subtitle, log_file=None, data_dir=None, telegram_token=None, telegram_chat_id=None):
    if not telegram_token or not telegram_chat_id:
        log("No Telegram credentials configured. Skipping notification.", log_file, data_dir)
        return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    text = f"🎥 *New Pathé Special: {title}*\n_{subtitle}_"
    payload = {
        "chat_id": telegram_chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            log(f"Telegram notification sent: {title} ({subtitle})", log_file, data_dir)
    except Exception as e:
        log(f"Failed to send Telegram notification: {e}", log_file, data_dir)

def find_shows_recursive(obj, shows_dict):
    """Recursively search for show-like objects inside the parsed state JSON."""
    if isinstance(obj, dict):
        if 'slug' in obj and 'title' in obj and 'releaseAt' in obj:
            slug = obj['slug']
            shows_dict[slug] = obj
        for v in obj.values():
            find_shows_recursive(v, shows_dict)
    elif isinstance(obj, list):
        for v in obj:
            find_shows_recursive(v, shows_dict)

def fetch_html(url=URL, headers=HEADERS, scraperapi_key=None):
    """Fetches raw HTML content from the specified URL."""
    if scraperapi_key:
        encoded_url = urllib.parse.quote(url)
        url = f"http://api.scraperapi.com?api_key={scraperapi_key}&url={encoded_url}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise Exception(f"Non-200 status code returned: {response.status}")
        return response.read().decode('utf-8', errors='ignore')

def parse_specials_from_html(html):
    """Extracts and parses specials movies from Angular state in HTML."""
    match = re.search(r'<script id="ng-state" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        raise Exception("Could not locate <script id=\"ng-state\" type=\"application/json\"> tag.")

    script_content = match.group(1)
    
    try:
        state_data = json.loads(script_content)
    except Exception as e:
        raise Exception(f"JSON parsing error: {e}")

    all_shows = {}
    find_shows_recursive(state_data, all_shows)
    
    specials = {}
    for slug, show in all_shows.items():
        is_event_special = show.get('isEventSpecial', False)
        special_event = show.get('specialEvent', False)
        if is_event_special or special_event:
            specials[slug] = {
                'title': show.get('title'),
                'slug': slug,
                'releaseAt': show.get('releaseAt', {}).get('NL_NL', 'Unknown Date'),
                'genres': show.get('genres', [])
            }
            
    return specials

def check_for_specials(args):
    log_file = os.path.join(args.data_dir, "pathe_checker.log")
    cache_file = os.path.join(args.data_dir, "specials_cache.json")
    
    log("Starting Pathé Specials check...", log_file, args.data_dir)
    
    # Clear cache file if requested
    if args.clear_cache:
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
                log("Cleared existing specials cache.", log_file, args.data_dir)
            except Exception as e:
                log(f"Failed to clear cache file: {e}", log_file, args.data_dir)
        else:
            log("No cache file found to clear.", log_file, args.data_dir)
    
    # 1. Fetch HTML page
    try:
        html = fetch_html(args.url, HEADERS, scraperapi_key=args.scraperapi_key)
    except Exception as e:
        log(f"HTTP request error: {e}", log_file, args.data_dir)
        return

    # 2. Parse HTML & extract specials
    try:
        specials = parse_specials_from_html(html)
    except Exception as e:
        log(f"Parsing error: {e}", log_file, args.data_dir)
        return

    log(f"Found specials: {len(specials)}", log_file, args.data_dir)

    if not specials:
        log("No specials found in current page state. Check if structure changed.", log_file, args.data_dir)
        return

    # 3. Load cache and identify new specials
    cache_existed = os.path.exists(cache_file)
    cached_specials = {}
    if cache_existed:
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_specials = json.load(f)
        except Exception as e:
            log(f"Error reading cache file (will re-initialize): {e}", log_file, args.data_dir)
            cache_existed = False

    if not cache_existed:
        # Initialize cache file on first run
        if not args.dry_run:
            try:
                os.makedirs(args.data_dir, exist_ok=True)
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(specials, f, indent=2)
                log(f"Initialized cache file with {len(specials)} specials. No alerts sent.", log_file, args.data_dir)
            except Exception as e:
                log(f"Error writing cache file: {e}", log_file, args.data_dir)
        else:
            log(f"[Dry Run] Would initialize cache with {len(specials)} specials. No file written.", log_file, args.data_dir)
        return

    # Compare currently active specials against cached specials
    new_specials = []
    for slug, show in specials.items():
        if slug not in cached_specials:
            new_specials.append(show)

    if new_specials:
        log(f"Detected {len(new_specials)} new specials!", log_file, args.data_dir)
        for show in new_specials:
            title = show['title']
            release = show['releaseAt']
            genres = ", ".join(show['genres']) if show['genres'] else ""
            subtitle = f"Release: {release}" + (f" | {genres}" if genres else "")
            
            if not args.dry_run:
                # Send notification
                send_notification(title, subtitle, log_file, args.data_dir, telegram_token=args.telegram_token, telegram_chat_id=args.telegram_chat_id)
                log(f"New Special: '{title}' (Slug: {show['slug']}, Release: {release})", log_file, args.data_dir)
            else:
                log(f"[Dry Run] Would send notification for: '{title}' (Slug: {show['slug']}, Release: {release})", log_file, args.data_dir)
            
        # Update cache file with all current specials
        if not args.dry_run:
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(specials, f, indent=2)
                log("Updated cache file.", log_file, args.data_dir)
            except Exception as e:
                log(f"Error updating cache file: {e}", log_file, args.data_dir)
    else:
        log("No new specials detected.", log_file, args.data_dir)

def main():
    import argparse
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    parser = argparse.ArgumentParser(description="Monitor Pathé Netherlands for special event screenings.")
    parser.add_argument(
        "-w", "--workspace",
        default=script_dir,
        help="Base directory for the project (defaults to script directory)"
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="Run scraping and detection without updating cache or sending alerts"
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Delete the cached specials file before checking"
    )
    parser.add_argument(
        "--url",
        default=URL,
        help="Pathé URL to scrape"
    )
    parser.add_argument(
        "--telegram-token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN"),
        help="Telegram Bot API Token (defaults to TELEGRAM_BOT_TOKEN environment variable)"
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.environ.get("TELEGRAM_CHAT_ID"),
        help="Telegram Chat ID (defaults to TELEGRAM_CHAT_ID environment variable)"
    )
    parser.add_argument(
        "--scraperapi-key",
        default=os.environ.get("SCRAPERAPI_KEY"),
        help="ScraperAPI key to bypass Cloudflare protection"
    )
    
    args = parser.parse_args()
    args.data_dir = os.path.join(args.workspace, "data")
    
    check_for_specials(args)

if __name__ == '__main__':
    main()
