# This bot requires the 'message_content' intent.

import json
import discord
from discord import app_commands
from discord.ext import commands
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import os
import sys
import asyncio
import urllib.request
import urllib.error
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import PurePosixPath

#--------------------------------------------------------------------
# Setup
#--------------------------------------------------------------------


def get_app_folder() -> str:
    """
    Determine the application folder path.
    
    Returns:
        str: Path to the application directory (executable dir if frozen, script dir otherwise)
    """
    if getattr(sys, 'frozen', False):
        # When compiled with PyInstaller, return the directory containing the executable
        return os.path.dirname(sys.executable)
    
    # For development/script mode, find the directory containing main.py
    # Start by checking if we can find main.py relative to this file's location
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Check if main.py is in the parent directory of this file (Src directory)
    parent_dir = os.path.dirname(current_file_dir)
    main_py_path = os.path.join(parent_dir, 'main.py')
    if os.path.exists(main_py_path):
        return parent_dir
    
    # If not found, search from current working directory up the tree
    current_dir = os.path.abspath(os.getcwd())
    search_dir = current_dir
    
    while True:
        main_py_path = os.path.join(search_dir, 'main.py')
        if os.path.exists(main_py_path):
            return search_dir
        
        # Move up one directory
        parent_dir = os.path.dirname(search_dir)
        if parent_dir == search_dir:  # Reached root directory
            break
        search_dir = parent_dir
    
    # Final fallback: return the directory containing this file (helpers directory)
    # and go up one level to get the Src directory
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def ensure_file_exists(filepath: str, default_content) -> None:
    """
    Create a file with default content if it doesn't exist.
    
    Args:
        filepath: Path to the file to create
        default_content: Default content to write to the file
    """
    if not os.path.isfile(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_content, f, indent=4)
        print(f"Created missing file: {filepath}")

def ensure_json_valid(filepath: str, default_content: dict) -> None:
    """
    Validate and clean a JSON configuration file.
    
    This function ensures the JSON file is valid and contains only expected keys.
    If the file is corrupted or contains extra keys, it will be cleaned up.
    
    Args:
        filepath: Path to the JSON file to validate
        default_content: Default configuration structure to validate against
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                # Reset to defaults if file is corrupted
                with open(filepath, 'w', encoding='utf-8') as fw:
                    json.dump(default_content, fw, indent=4)
                print(f"Invalid JSON in {filepath}. Resetting to default.")
                return

        modified = False
        cleaned_data = {}

        # Copy over valid keys from default_config
        for key, default_value in default_content.items():
            if key in data:
                if isinstance(default_value, list) and isinstance(data[key], list):
                    merged = list(dict.fromkeys(data[key] + default_value))
                    cleaned_data[key] = merged

                    if merged != data[key]:
                        modified = True
                        print(f"Updated '{key}' in {filepath}")
                else:
                    cleaned_data[key] = data[key]
            else:
                cleaned_data[key] = default_value
                modified = True
                print(f"Added missing key '{key}' to {filepath}")

        # Check for and remove extra keys
        extra_keys = set(data.keys()) - set(default_content.keys())
        if extra_keys:
            modified = True
            print(f"Removing extra keys from {filepath}: {extra_keys}")

        if modified:
            # Create a backup before making changes
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = f"{filepath}.backup_{timestamp}.json"
            with open(backup_path, 'w', encoding='utf-8') as backup_file:
                json.dump(data, backup_file, indent=4)
            print(f"Backed up original config file to {backup_path}")

            # Write cleaned data
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(cleaned_data, f, indent=4)
            print(f"Successfully cleaned and updated {filepath}")

    except Exception as e:
        print(f"Error validating JSON file {filepath}: {e}")

APP_FOLDER = get_app_folder()
CONFIG_PATH = os.path.join(APP_FOLDER, 'config.json')
TRACKERS_PATH = os.path.join(APP_FOLDER, 'trackers.json')

default_config = {
    "bot_token": "",
    "mention_reply_author": True,
    "require_links": True,
    "privacy_alert_channel_id": 1549493675870916668,
    "regex_keys": "(?i)\\b((?:https?://|www\\.)[^\\s<>\"']+|(?:[a-z0-9-]+\\.)+[a-z]{2,}(?:/[^\\s<>\"']*)?)\\b"
}

default_trackers = {
    # ---------------------------------------------------------------
    # Google / Google Ads / Google Analytics
    # ---------------------------------------------------------------
    "Google": [
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_source_platform",
        "utm_creative_format",
        "utm_marketing_tactic",

        "gclid",
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",

        "gad",
        "gad_source",
        "gad_campaignid",

        "_ga",
        "_gl",
        "_gac",
        "_gid"
    ],

    # ---------------------------------------------------------------
    # Meta / Facebook / Instagram
    # ---------------------------------------------------------------
    "Meta": [
        "fbclid",
        "fb_action_ids",
        "fb_action_types",
        "fb_source",
        "fb_ref",
        "fb_ad_id",
        "fb_adset_id",
        "fb_campaign_id",

        "igsh",
        "igshid",

        "stkn"
    ],

    # ---------------------------------------------------------------
    # TikTok
    # ---------------------------------------------------------------
    "TikTok": [
        "ttclid",
        "tt_content_id",
        "tt_medium",
        "tt_campaign_id",
        "tt_ad_id",
        "tt_adset_id"
    ],

    # ---------------------------------------------------------------
    # Microsoft / Bing Ads
    # ---------------------------------------------------------------
    "Microsoft": [
        "msclkid"
    ],

    # ---------------------------------------------------------------
    # LinkedIn
    # ---------------------------------------------------------------
    "LinkedIn": [
        "li_fat_id",
        "li_source",
        "li_medium",
        "li_campaign"
    ],

    # ---------------------------------------------------------------
    # X / Twitter
    # ---------------------------------------------------------------
    "Twitter": [
        "twclid",
        "tw_campaign",
        "tw_source",
        "ref_src"
    ],

    # ---------------------------------------------------------------
    # Reddit
    # ---------------------------------------------------------------
    "Reddit": [
        "rdt_cid",
        "rdt_source",
        "rdt_medium",
        "rdt_campaign"
    ],

    # ---------------------------------------------------------------
    # Snapchat
    # ---------------------------------------------------------------
    "Snapchat": [
        "sc_cid",
        "sc_source",
        "sc_medium",
        "sc_campaign"
    ],

    # ---------------------------------------------------------------
    # Pinterest
    # ---------------------------------------------------------------
    "Pinterest": [
        "epik",
        "pin_campaign",
        "pin_source"
    ],

    # ---------------------------------------------------------------
    # Amazon
    # ---------------------------------------------------------------
    "Amazon": [
        "tag",
        "ascsubtag",
        "asc_source",
        "creative",
        "creativeASIN",
        "linkCode"
    ],

    # ---------------------------------------------------------------
    # Mailchimp
    # ---------------------------------------------------------------
    "Mailchimp": [
        "mc_cid",
        "mc_eid"
    ],

    # ---------------------------------------------------------------
    # HubSpot
    # ---------------------------------------------------------------
    "HubSpot": [
        "hsa_acc",
        "hsa_cam",
        "hsa_grp",
        "hsa_ad",
        "hsa_src",
        "hsa_tgt",
        "hsa_kw",
        "hsa_mt",
        "hsa_net",
        "hsa_ver",
        "_hsenc",
        "_hsmi"
    ],

    # ---------------------------------------------------------------
    # Adobe
    # ---------------------------------------------------------------
    "Adobe": [
        "s_cid",
        "ef_id"
    ],

    # ---------------------------------------------------------------
    # Salesforce / Pardot
    # ---------------------------------------------------------------
    "Salesforce": [
        "pi_campaign_id",
        "pi_source",
        "pi_ad_id"
    ],

    # ---------------------------------------------------------------
    # Shopify
    # ---------------------------------------------------------------
    "Shopify": [
        "shopify",
        "shopify_app",
        "shopify_email",
        "shopify_utm"
    ],

    # ---------------------------------------------------------------
    # Email / Marketing platforms
    # ---------------------------------------------------------------
    "Email": [
        "mkt_tok",
        "vero_id",
        "vero_conv",
        "oly_anon_id",
        "oly_enc_id"
    ],

    # ---------------------------------------------------------------
    # Affiliate / click attribution
    #
    # Keep this conservative. Generic names such as ref/source/cid
    # can be legitimate site functionality.
    # ---------------------------------------------------------------
    "Affiliate": [
        "aff_id",
        "affiliate_id",
        "partner_id",
        "click_id",
        "clickid",
        "subid",
        "sub_id"
    ],

    # ---------------------------------------------------------------
    # Other known analytics / advertising IDs
    # ---------------------------------------------------------------
    "Analytics": [
        "yclid",
        "rb_clickid",
        "appSharePlatform"
    ]
}

ensure_file_exists(CONFIG_PATH, default_config)
ensure_json_valid(CONFIG_PATH, default_config)
ensure_file_exists(TRACKERS_PATH, default_trackers)
ensure_json_valid(TRACKERS_PATH, default_trackers)

# Load initial config
with open(CONFIG_PATH, 'r', encoding="utf-8") as f:
    config = json.load(f)
    
with open(TRACKERS_PATH, 'r', encoding="utf-8") as f:
    trackers = json.load(f)
    
bot_token = os.getenv("DISCORD_TOKEN", "").strip() or config.get("bot_token", default_config["bot_token"]).strip()
mention_reply_author = config.get("mention_reply_author", default_config["mention_reply_author"])
require_links = config.get("require_links", default_config["require_links"])

PARAM_INDEX = {param.lower(): company for company, params in trackers.items() for param in params}

try:
    REGEX = re.compile(
        config.get("regex_keys", default_config["regex_keys"])
    )
except re.error as e:
    raise RuntimeError(f"Invalid regex in config.json: {e}")


#--------------------------------------------------------------------
# Funcs
#--------------------------------------------------------------------

def has_link(message: str) -> bool:
    return bool(REGEX.search(message))


TRACKER_PREFIXES = {
    "utm_": "Google",
    "gad_": "Google",
    "hsa_": "HubSpot",
}


def get_tracker_owner(param_name: str):
    """
    Return the owner of a known tracking parameter.

    Checks exact tracker names first, then known tracker families.
    Returns None if the parameter is not a known tracker.
    """
    key = param_name.lower()

    # Exact tracker from trackers.json
    owner = PARAM_INDEX.get(key)
    if owner:
        return owner

    # Known tracker families
    for prefix, owner in TRACKER_PREFIXES.items():
        if key.startswith(prefix):
            return owner

    return None


# ---------------------------------------------------------------
# Meta / Facebook / Instagram aggressive cleaning
# ---------------------------------------------------------------

META_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mobile.facebook.com",
    "mbasic.facebook.com",
    "fb.com",
    "www.fb.com",
    "instagram.com",
    "www.instagram.com",
    "threads.net",
    "www.threads.net",
}


def is_meta_host(hostname: str) -> bool:
    hostname = hostname.lower()

    return (
        hostname in META_HOSTS
        or hostname.endswith(".facebook.com")
        or hostname.endswith(".instagram.com")
        or hostname.endswith(".threads.net")
    )


def get_meta_param_owner(parsed, key: str):
    """
    Aggressively remove unnecessary query parameters from Meta content URLs.

    Meta frequently changes tracking parameter names, so for URLs where
    the content ID is already contained in the path, query parameters are
    removed by default.

    Older Facebook formats preserve parameters needed to locate content.
    """

    hostname = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    key = key.lower()

    if not is_meta_host(hostname):
        return None

    # Instagram
    if "instagram.com" in hostname:
        if path.startswith(("/reel/", "/reels/", "/p/", "/tv/")):

            # Can select a particular picture in a carousel
            if key == "img_index":
                return None

            return "Meta"

    # Threads
    if "threads.net" in hostname:
        if "/post/" in path:
            return "Meta"

    # Facebook
    if "facebook.com" in hostname or hostname in {"fb.com", "www.fb.com"}:

        # Modern Facebook URLs with content ID in the path
        if (
            path.startswith(("/reel/", "/share/"))
            or "/posts/" in path
            or "/videos/" in path
        ):
            return "Meta"

        # Facebook Watch requires v=
        if path in {"/watch", "/watch/"}:
            if key == "v":
                return None

            return "Meta"

        # Older story URLs
        if path.endswith("/story.php") or path == "/story.php":
            if key in {"story_fbid", "id"}:
                return None

            return "Meta"

        # Older permalink URLs
        if path.endswith("/permalink.php") or path == "/permalink.php":
            if key in {"story_fbid", "id"}:
                return None

            return "Meta"

        # Facebook photo URLs
        if path.endswith("/photo.php") or path == "/photo.php":
            if key in {"fbid", "id", "set"}:
                return None

            return "Meta"

        # Facebook profile URLs
        if path.endswith("/profile.php") or path == "/profile.php":
            if key == "id":
                return None

            return "Meta"

    return None


KNOWN_INSTAGRAM_SHARE_KEYS = {
    "igsh", "igshid", "igsi", "stkn", "srtk", "mdxt", "obrf", "cplk",
    "dlrf", "exln", "psln", "rpxt", "vrfl", "xtok", "utm_source",
    "utm_medium", "utm_campaign", "img_index",
}


def unknown_share_parameters(url):
    """Report unfamiliar query *names*, never their identifying values."""
    parsed = urlparse(url if "://" in url else "https://" + url)
    host, path = (parsed.hostname or "").lower(), parsed.path.lower()
    if host in {"instagram.com", "www.instagram.com"} and path.startswith(("/reel/", "/p/", "/tv/")):
        return {key for key, _ in parse_qsl(parsed.query) if key.lower() not in KNOWN_INSTAGRAM_SHARE_KEYS and not get_tracker_owner(key)}
    if host in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"} and TIKTOK_VIDEO_PATH.fullmatch(parsed.path):
        return {key for key, _ in parse_qsl(parsed.query) if key.lower() not in {"_r", "_t"} and not get_tracker_owner(key)}
    return set()


def has_trackers(url):
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):

        # Meta-specific aggressive rules
        if get_meta_param_owner(parsed, key):
            return True

        # Normal tracker database
        if get_tracker_owner(key):
            return True

        # YouTube share tracking
        if hostname in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be"
        }:
            if key.lower() in {"si", "is"}:
                return True

    return False


def build_param_index(tracker_map):
    index = {}

    for company, params in tracker_map.items():
        for param in params:
            index[param.lower()] = company

    return index


def clean_url(url):
    parsed = urlparse(url)
    kept = []
    removed = {}

    hostname = (parsed.hostname or "").lower()

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        owner = None

        # Meta-specific aggressive cleaning
        meta_owner = get_meta_param_owner(parsed, key)

        if meta_owner:
            owner = meta_owner

        # Normal tracker database
        if not owner:
            owner = get_tracker_owner(key)

        # Spotify share IDs can link listening activity to the sender.
        if hostname in {"open.spotify.com", "spotify.com"} and key.lower() == "si":
            owner = "Spotify"
        if hostname in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"} and key.lower() in {"_r", "_t"}:
            owner = "TikTok"
        # The video ID is in TikTok's path; extra query fields are not needed.
        if hostname in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"} and TIKTOK_VIDEO_PATH.fullmatch(parsed.path):
            owner = "TikTok"

        # YouTube share tracking
        if hostname in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be"
        }:
            if key.lower() in {"si", "is"}:
                owner = "YouTube"

        if owner:
            removed.setdefault(owner, []).append(key)
        else:
            kept.append((key, value))

    cleaned_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(kept),
        parsed.fragment
    ))

    if removed:
        message = f"Removed trackers from {', '.join(removed.keys())}"
    else:
        message = "No trackers found"

    return {
        "clean_url": cleaned_url,
        "removed_trackers": removed,
        "message": message
    }


# High-risk short share links must be resolved to the underlying content.
# Never treat a /share/ path as safe merely because it has no query string.
FB_SHARE_PATH = re.compile(r"^/share/(?:r|v|p)/[A-Za-z0-9_-]+/?$", re.I)
IG_SHARE_PATH = re.compile(r"^/share/(?:p/)?[A-Za-z0-9_-]+/?$", re.I)
FB_REEL_PATH = re.compile(r"^/reel/\d+/?$", re.I)
FB_POST_PATH = re.compile(r"^/(?:[^/]+/)?posts/(?:pfbid[A-Za-z0-9]+|\d+)/?$", re.I)
IG_CONTENT_PATH = re.compile(r"^/(?:p|reel|tv)/[A-Za-z0-9_-]+/?$", re.I)
TIKTOK_VIDEO_PATH = re.compile(r"^/@[A-Za-z0-9_.-]+/video/\d+/?$", re.I)


def privacy_share_kind(url):
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if host in {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"} and (
        path.lower().startswith("/share/") or host == "fb.watch"
    ):
        return "Facebook"
    if host in {"instagram.com", "www.instagram.com"} and path.lower().startswith("/share/"):
        return "Instagram"
    if host in {"vm.tiktok.com", "vt.tiktok.com"} or (
        host in {"tiktok.com", "www.tiktok.com"}
        and path.lower().startswith("/t/")
    ):
        return "TikTok"
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _resolve_share_sync(url, kind):
    """Resolve only approved hosts; never follow arbitrary redirect destinations."""
    parsed = urlparse(url if "://" in url else "https://" + url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        return None
    allowed = {
        "Facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"},
        "Instagram": {"instagram.com", "www.instagram.com"},
        "TikTok": {"vm.tiktok.com", "vt.tiktok.com", "tiktok.com", "www.tiktok.com"},
    }[kind]
    if (parsed.hostname or "").lower() not in allowed:
        return None
    opener = urllib.request.build_opener(_NoRedirect)
    # The first Location is usually sufficient. Cap hops and validate each one.
    current = url
    for _ in range(4):
        try:
            request = urllib.request.Request(current, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            response = opener.open(request, timeout=7)
            status, location = response.status, response.headers.get("Location")
            response.close()
        except urllib.error.HTTPError as error:
            status, location = error.code, error.headers.get("Location")
            error.close()
        except (OSError, ValueError):
            return None
        if status not in {301, 302, 303, 307, 308} or not location:
            return None
        from urllib.parse import urljoin
        destination = urlparse(urljoin(current, location))
        if destination.scheme != "https" or destination.username or destination.password or destination.port:
            return None
        host, path = (destination.hostname or "").lower(), destination.path
        if kind == "Facebook" and host in {"www.facebook.com", "facebook.com"}:
            if FB_REEL_PATH.fullmatch(path) or FB_POST_PATH.fullmatch(path):
                return "https://www.facebook.com" + path.rstrip("/") + "/"
            if path == "/watch/":
                video_id = dict(parse_qsl(destination.query)).get("v", "")
                if video_id.isdigit():
                    return "https://www.facebook.com/watch/?v=" + video_id
        elif kind == "Instagram" and host in {"www.instagram.com", "instagram.com"}:
            if IG_CONTENT_PATH.fullmatch(path):
                return "https://www.instagram.com" + path.rstrip("/") + "/"
        elif kind == "TikTok" and host in {"www.tiktok.com", "tiktok.com"}:
            if TIKTOK_VIDEO_PATH.fullmatch(path):
                return "https://www.tiktok.com" + path.rstrip("/")
        # Only continue within the originating service's approved domains.
        next_allowed = allowed[kind] | ({"www.tiktok.com", "tiktok.com"} if kind == "TikTok" else set())
        if host not in next_allowed:
            return None
        current = destination.geturl()
    return None


async def resolve_privacy_share(url, kind):
    try:
        return await asyncio.wait_for(asyncio.to_thread(_resolve_share_sync, url, kind), timeout=18)
    except (Exception, asyncio.CancelledError) as error:
        print(f"Privacy link resolution failed ({kind}): {type(error).__name__}")
        return None


def format_companies(companies):
    """Return a nicely formatted string with commas and 'and' before the last item."""
    companies = list(companies)  # ensure it's a list
    if len(companies) == 0:
        return ""
    elif len(companies) == 1:
        return companies[0]
    else:
        return ", ".join(companies[:-1]) + f", and {companies[-1]}"

def load_config():
    """Load configuration from JSON file."""
    global config, mention_reply_author, require_links, REGEX
    with open(CONFIG_PATH, 'r', encoding="utf-8") as f:
        config = json.load(f)
    
    mention_reply_author = config.get("mention_reply_author", default_config["mention_reply_author"])
    require_links = config.get("require_links", default_config["require_links"])
    
    try:
        REGEX = re.compile(config.get("regex_keys", default_config["regex_keys"]))
    except re.error as e:
        raise RuntimeError(f"Invalid regex in config.json: {e}")

def save_config():
    """Save current configuration to JSON file."""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

def load_trackers():
    """Load trackers from JSON file."""
    global trackers, PARAM_INDEX
    with open(TRACKERS_PATH, 'r', encoding="utf-8") as f:
        trackers = json.load(f)
    PARAM_INDEX = {param.lower(): company for company, params in trackers.items() for param in params}

def save_trackers():
    """Save current trackers to JSON file."""
    with open(TRACKERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(trackers, f, indent=4)
#--------------------------------------------------------------------
# Main Program
#--------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.moderation = True

# Replace this with the ID of the private #member-log channel.
MEMBER_LOG_CHANNEL_ID = 1565398175831826462

bot = commands.Bot(command_prefix='!', intents=intents)


async def send_privacy_failure_alert(message, kinds, reason):
    """Alert the bug channel without retaining URL text or sender identity."""
    channel_id = int(config.get("privacy_alert_channel_id") or 0)
    if not channel_id or not message.guild:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.HTTPException, ValueError):
            print("Privacy alert channel is not accessible.")
            return
    # No original URL, URL token, message contents, or author mention.
    details = (
        "⚠️ **Link Cleaner privacy failure**\n"
        f"Service(s): {', '.join(sorted(kinds))}\n"
        f"Reason: {reason}\n"
        f"Server/channel IDs: {message.guild.id} / {message.channel.id}\n"
        "Please review the resolver rules. Original URL intentionally omitted."
    )
    try:
        await channel.send(details, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        print("Unable to post privacy failure alert.")

@bot.event
async def on_ready():
    await initialize_guild_features()
    print(f'Logged in as {bot.user}!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.author.bot or not message.guild:
        return

    # Process commands first
    await bot.process_commands(message)

    if await security_inspect(message):
        return

    if not (has_link(message.content) and require_links):
        return

    urls = re.findall(REGEX, message.content)
    if not urls:
        return

    detected_companies = set()
    sanitized_map = {}
    unresolved = set()
    novel_keys = set()

    for url in urls:
        kind = privacy_share_kind(url)
        if kind:
            resolved = await resolve_privacy_share(url, kind)
            if resolved:
                sanitized_map[url] = resolved
                detected_companies.add(kind)
            else:
                unresolved.add(kind)
            continue

        result = clean_url(url)
        novel_keys.update(unknown_share_parameters(url))

        if result["removed_trackers"]:
            detected_companies.update(result["removed_trackers"].keys())
            sanitized_map[url] = result["clean_url"]

    if unresolved:
        # Privacy takes precedence: remove the whole message if even one
        # high-risk share URL could not be resolved. Never echo the link.
        try:
            await message.delete()
        except discord.Forbidden:
            print("Cannot delete potentially identifying share link; check Manage Messages permission.")
            await send_privacy_failure_alert(message, unresolved, "Could not delete original (permissions)")
            return
        except Exception as e:
            print(f"Could not delete potentially identifying share link: {type(e).__name__}")
            await send_privacy_failure_alert(message, unresolved, "Could not delete original (Discord error)")
            return
        await send_privacy_failure_alert(message, unresolved, "Share link could not be safely resolved; original removed")
        warning = (
            "I removed your message because a shared social-media link might "
            "reveal your account identity, and I couldn't verify a safe direct "
            "link. Please copy the original post/video address instead. "
            "I haven't repeated the potentially identifying link."
        )
        try:
            await message.author.send(warning)
        except (discord.Forbidden, discord.HTTPException):
            try:
                await message.channel.send(f"{message.author.mention} {warning}", delete_after=45)
            except discord.HTTPException:
                print("Could not notify author about privacy removal.")
        return

    if detected_companies:
        sanitized_message = message.content
        # Only replace exact URL matches; a shorter URL might be a prefix of another.
        for original in sorted(sanitized_map, key=len, reverse=True):
            sanitized_message = sanitized_message.replace(original, sanitized_map[original])
        author_mention = f"{message.author.mention} " if mention_reply_author else ""
        notice = (
            f"{author_mention}Your message has been reposted without trackers from "
            f"{format_companies(detected_companies)}:"
        )
        try:
            # Publish successfully before removing the original.
            reply = await message.reply(f"{notice}\n{sanitized_message}", mention_author=False)
        except discord.HTTPException as error:
            print(f"Could not publish cleaned message: {type(error).__name__}")
            if any(privacy_share_kind(url) for url in sanitized_map):
                await send_privacy_failure_alert(message, detected_companies, "Could not post resolved clean replacement")
            return
        try:
            await message.delete()
        except discord.HTTPException as error:
            print(f"Cleaned message posted, but original deletion failed: {type(error).__name__}")
            if any(privacy_share_kind(url) for url in sanitized_map):
                await send_privacy_failure_alert(message, detected_companies, "Original deletion failed after clean repost")
        if novel_keys:
            # Share only bounded, validated parameter NAMES; values can identify people.
            key_names = sorted(k for k in novel_keys if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", k))[:10]
            await send_privacy_failure_alert(
                message, detected_companies or {"Social media"},
                "Unrecognized query parameter name(s) stripped: " + (", ".join(key_names) if key_names else "unprintable key")
            )

#--------------------------------------------------------------------
# Staff-only Membership Logging
#--------------------------------------------------------------------

async def send_member_log(guild, embed):
    """Send a membership event to the private staff channel."""
    if MEMBER_LOG_CHANNEL_ID == 123456789012345678:
        print("Member log is not configured: set MEMBER_LOG_CHANNEL_ID.")
        return

    channel = guild.get_channel(MEMBER_LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await guild.fetch_channel(MEMBER_LOG_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
            print(f"Unable to find membership log channel: {error}")
            return

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as error:
        print(f"Could not write membership log: {error}")


@bot.event
async def on_member_join(member):
    previous_registration = None
    if _guild_features_ready:
        previous_registration = registration_record(member.id)
        if previous_registration:
            # Rejoining Discord never restores the verified Member role by itself.
            with db_connect() as con:
                archive_registration(con, previous_registration, 'discord_rejoined')
                con.execute("UPDATE registrations SET status='rejoined', application_message_id=NULL WHERE user_id=?",
                            (member.id,))
    embed = discord.Embed(
        title="Member Joined",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Account", value=f"{member.mention}\n{member}", inline=False)
    embed.add_field(name="Discord ID", value=f"`{member.id}`", inline=False)
    embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "F"), inline=False)
    embed.add_field(name="Rules Screening", value="Pending" if member.pending else "Not pending", inline=False)
    if previous_registration:
        embed.add_field(
            name='Previous WeNT registration',
            value=(f'Previously `{previous_registration["status"]}` as '
                   f'**{discord.utils.escape_markdown(previous_registration["character"])}**. '
                   'Rejoined Discord; fresh membership verification is required.'),
            inline=False,
        )
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_member_log(member.guild, embed)


@bot.event
async def on_raw_member_remove(payload):
    # Raw removal works even if the member was not cached (e.g. during screening).
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        print(f"Membership departure in unknown guild {payload.guild_id}: {payload.user.id}")
        return
    user = payload.user
    embed = discord.Embed(
        title="Member Departed",
        description=(f"**Account:** {user}\n**Discord ID:** `{user.id}`\n"
                     "Departure may mean a leave, kick, or ban."),
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    await send_member_log(guild, embed)


async def find_role_change_actor(guild, member_id, added_role_ids, removed_role_ids, observed_at):
    """Attribute role edits only when one recent audit entry matches this exact change."""
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.view_audit_log:
        return 'Unknown (View Audit Log permission missing)'
    # Member-update events can arrive before Discord exposes their audit entry.
    await asyncio.sleep(2)
    matches = []
    try:
        async for entry in guild.audit_logs(limit=20, action=discord.AuditLogAction.member_role_update):
            target_id = getattr(entry.target, 'id', None)
            if target_id != member_id or abs((entry.created_at - observed_at).total_seconds()) > 15:
                continue
            old_roles = getattr(entry.before, 'roles', None)
            new_roles = getattr(entry.after, 'roles', None)
            if old_roles is not None and new_roles is not None:
                old_ids = {role.id for role in old_roles}
                new_ids = {role.id for role in new_roles}
                if (new_ids - old_ids) != added_role_ids or (old_ids - new_ids) != removed_role_ids:
                    continue
            matches.append(entry)
    except (discord.Forbidden, discord.HTTPException):
        return 'Unknown (audit log unavailable)'
    if len(matches) != 1 or matches[0].user is None:
        return 'Unknown (no unique audit-log match)'
    return f'{matches[0].user.mention} (`{matches[0].user.id}`)'


@bot.event
async def on_member_update(before, after):
    if before.pending and not after.pending:
        embed = discord.Embed(
            title="Member Passed Screening",
            description=f"**Account:** {after.mention}\n**Discord ID:** `{after.id}`",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        await send_member_log(after.guild, embed)
    previous_roles = {role.id: role for role in before.roles}
    current_roles = {role.id: role for role in after.roles}
    added_roles = [role for role_id, role in current_roles.items() if role_id not in previous_roles]
    removed_roles = [role for role_id, role in previous_roles.items() if role_id not in current_roles]
    if added_roles or removed_roles:
        changed_at = discord.utils.utcnow()
        actor = await find_role_change_actor(
            after.guild, after.id,
            {role.id for role in added_roles}, {role.id for role in removed_roles}, changed_at,
        )
        embed = discord.Embed(
            title='Member Roles Updated',
            color=discord.Color.blue(),
            timestamp=changed_at,
        )
        embed.add_field(name='Account', value=f'{after.mention} (`{after.id}`)', inline=False)
        embed.add_field(name='Changed by', value=actor, inline=False)
        if added_roles:
            embed.add_field(name='Added', value=', '.join(discord.utils.escape_markdown(role.name) for role in added_roles)[:1000], inline=False)
        if removed_roles:
            embed.add_field(name='Removed', value=', '.join(discord.utils.escape_markdown(role.name) for role in removed_roles)[:1000], inline=False)
        if any(role.id == 1573470911129059408 for role in added_roles):
            embed.add_field(name='GuildsForever', value='Role detected; this is not automatic WeNT membership verification.', inline=False)
        embed.set_footer(text='Actor is shown only when one recent audit-log event matches.')
        await send_member_log(after.guild, embed)


@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(
        title="Member Banned",
        description=f"**Account:** {user}\n**Discord ID:** `{user.id}`",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    await send_member_log(guild, embed)


#--------------------------------------------------------------------
# Admin Commands
#--------------------------------------------------------------------

def is_admin(interaction: discord.Interaction) -> bool:
    """Check if user has administrator permissions."""
    return interaction.user.guild_permissions.administrator

@bot.tree.command(name="settings", description="View current bot settings")
async def settings(interaction: discord.Interaction):
    """View current bot settings."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    load_config()
    embed = discord.Embed(
        title="Bot Settings",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Mention Reply Author",
        value="✅ Enabled" if mention_reply_author else "❌ Disabled",
        inline=False
    )
    embed.add_field(
        name="Require Links",
        value="✅ Enabled" if require_links else "❌ Disabled",
        inline=False
    )
    embed.add_field(
        name="Regex Pattern",
        value=f"`{config.get('regex_keys', 'N/A')[:100]}...`" if len(config.get('regex_keys', '')) > 100 else f"`{config.get('regex_keys', 'N/A')}`",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="set_mention", description="Enable or disable mentioning the author when reposting messages")
@app_commands.describe(enabled="Whether to mention the author when reposting")
async def set_mention(interaction: discord.Interaction, enabled: bool):
    """Set whether to mention the author when reposting messages."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    global mention_reply_author
    config["mention_reply_author"] = enabled
    save_config()
    load_config()
    
    await interaction.response.send_message(
        f"✅ Mention reply author has been {'enabled' if enabled else 'disabled'}.",
        ephemeral=True
    )

@bot.tree.command(name="set_require_links", description="Enable or disable requiring links in messages before processing")
@app_commands.describe(enabled="Whether to only process messages that contain links")
async def set_require_links(interaction: discord.Interaction, enabled: bool):
    """Set whether to require links in messages before processing."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    global require_links
    config["require_links"] = enabled
    save_config()
    load_config()
    
    await interaction.response.send_message(
        f"✅ Require links has been {'enabled' if enabled else 'disabled'}.",
        ephemeral=True
    )

@bot.tree.command(name="set_regex", description="Set the regex pattern used to detect URLs")
@app_commands.describe(pattern="The regex pattern to use for URL detection")
async def set_regex(interaction: discord.Interaction, pattern: str):
    """Set the regex pattern used to detect URLs."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    # Validate regex pattern
    try:
        test_regex = re.compile(pattern)
    except re.error as e:
        await interaction.response.send_message(
            f"❌ Invalid regex pattern: {e}\n\nPlease provide a valid regex pattern.",
            ephemeral=True
        )
        return
    
    global REGEX
    config["regex_keys"] = pattern
    save_config()
    load_config()
    
    await interaction.response.send_message(
        f"✅ Regex pattern has been updated.\n\nNew pattern: `{pattern}`",
        ephemeral=True
    )

@bot.tree.command(name="reload_config", description="Reload configuration from file")
async def reload_config(interaction: discord.Interaction):
    """Reload configuration from config.json file."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    try:
        load_config()
        await interaction.response.send_message("✅ Configuration reloaded successfully.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error reloading configuration: {e}", ephemeral=True)

#--------------------------------------------------------------------
# Tracker Management Commands
#--------------------------------------------------------------------

trackers_group = app_commands.Group(name="trackers", description="Manage tracking parameters")

@trackers_group.command(name="list", description="List all trackers organized by provider")
async def trackers_list(interaction: discord.Interaction):
    """List all trackers organized by provider."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    load_trackers()
    
    if not trackers:
        await interaction.response.send_message("❌ No trackers configured.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="Tracking Parameters",
        description="All configured tracking parameters by provider",
        color=discord.Color.blue()
    )
    
    # Discord embeds have a limit of 6000 characters total
    # Split into multiple embeds if needed
    total_length = 0
    fields_added = 0
    
    for provider, params in sorted(trackers.items()):
        if not params:
            continue
        
        params_str = ", ".join(params)
        field_value = f"`{params_str}`"
        
        # Check if adding this field would exceed limits
        # Discord field value limit is 1024 characters, embed total is 6000
        if len(field_value) > 1024:
            # Truncate if too long
            field_value = field_value[:1020] + "..."
        
        if total_length + len(field_value) + len(provider) > 5500 or fields_added >= 25:
            # Add a note that there are more providers
            embed.add_field(
                name="...",
                value=f"*Showing first {fields_added} providers. Use `/trackers list` to see all.*",
                inline=False
            )
            break
        
        embed.add_field(
            name=provider,
            value=field_value,
            inline=False
        )
        total_length += len(field_value) + len(provider)
        fields_added += 1
    
    embed.set_footer(text=f"Total providers: {len(trackers)}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@trackers_group.command(name="add", description="Add a tracker parameter to a provider")
@app_commands.describe(provider="The provider name (e.g., Google, Meta)")
@app_commands.describe(tracker="The tracker parameter name to add")
async def trackers_add(interaction: discord.Interaction, provider: str, tracker: str):
    """Add a tracker parameter to a provider."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    load_trackers()
    
    # Normalize provider name (capitalize first letter)
    provider_normalized = provider.strip()
    if provider_normalized:
        provider_normalized = provider_normalized[0].upper() + provider_normalized[1:].lower()
    
    tracker_normalized = tracker.strip()
    
    if not tracker_normalized:
        await interaction.response.send_message("❌ Tracker parameter name cannot be empty.", ephemeral=True)
        return
    
    # Check if tracker already exists for any provider
    tracker_lower = tracker_normalized.lower()
    existing_provider = None
    for prov, params in trackers.items():
        if tracker_lower in [p.lower() for p in params]:
            existing_provider = prov
            break
    
    if existing_provider:
        if existing_provider == provider_normalized:
            await interaction.response.send_message(
                f"❌ Tracker `{tracker_normalized}` already exists for provider `{provider_normalized}`.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Tracker `{tracker_normalized}` already exists for provider `{existing_provider}`. "
                f"Remove it first if you want to add it to `{provider_normalized}`.",
                ephemeral=True
            )
        return
    
    # Add tracker to provider
    if provider_normalized not in trackers:
        trackers[provider_normalized] = []
    
    trackers[provider_normalized].append(tracker_normalized)
    save_trackers()
    load_trackers()  # Reload to update PARAM_INDEX
    
    await interaction.response.send_message(
        f"✅ Added tracker `{tracker_normalized}` to provider `{provider_normalized}`.",
        ephemeral=True
    )

@trackers_group.command(name="remove", description="Remove a tracker parameter from a provider")
@app_commands.describe(provider="The provider name (e.g., Google, Meta)")
@app_commands.describe(tracker="The tracker parameter name to remove")
async def trackers_remove(interaction: discord.Interaction, provider: str, tracker: str):
    """Remove a tracker parameter from a provider."""
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
        return
    
    load_trackers()
    
    # Normalize provider name (capitalize first letter)
    provider_normalized = provider.strip()
    if provider_normalized:
        provider_normalized = provider_normalized[0].upper() + provider_normalized[1:].lower()
    
    tracker_normalized = tracker.strip()
    
    if provider_normalized not in trackers:
        await interaction.response.send_message(
            f"❌ Provider `{provider_normalized}` not found.",
            ephemeral=True
        )
        return
    
    # Find and remove tracker (case-insensitive)
    tracker_lower = tracker_normalized.lower()
    found = False
    for i, param in enumerate(trackers[provider_normalized]):
        if param.lower() == tracker_lower:
            removed_tracker = trackers[provider_normalized].pop(i)
            found = True
            break
    
    if not found:
        await interaction.response.send_message(
            f"❌ Tracker `{tracker_normalized}` not found for provider `{provider_normalized}`.",
            ephemeral=True
        )
        return
    
    # Remove provider if it has no trackers left
    if not trackers[provider_normalized]:
        del trackers[provider_normalized]
        save_trackers()
        load_trackers()
        await interaction.response.send_message(
            f"✅ Removed tracker `{tracker_normalized}` from provider `{provider_normalized}`. "
            f"Provider `{provider_normalized}` has been removed as it has no trackers left.",
            ephemeral=True
        )
    else:
        save_trackers()
        load_trackers()  # Reload to update PARAM_INDEX
        await interaction.response.send_message(
            f"✅ Removed tracker `{tracker_normalized}` from provider `{provider_normalized}`.",
            ephemeral=True
        )

bot.tree.add_command(trackers_group)

#--------------------------------------------------------------------
# WeNT registration + Security Watch (persisted on Railway volume)
#--------------------------------------------------------------------

REGISTRATION_CHANNEL_ID = 1573517083914797206
APPLICATIONS_CHANNEL_ID = 1573521142252306553
SECURITY_CHANNEL_ID = 1549493675870916668
# Relax behavioral anti-spam alerts in private/community sharing areas.
# Malware-domain and dangerous-attachment checks still apply everywhere.
RELAXED_SECURITY_CHANNEL_IDS = {
    1572977935596654652,  # book club
    1551360139158618242,  # officer
    1551360164781887508,  # council
    1485108921772412932,  # secret-general (Bros)
    1555249125660950629,  # brah mischief
}
MEMBER_ROLE_ID = 1551362160653770863
OFFICER_ROLE_ID = 1551361709459906661
COUNCIL_ROLE_ID = 1551360981861404803
GUILDSFOREVER_ROLE_ID = 1573470911129059408
DB_PATH = os.getenv('SENTINEL_DB_PATH', '/data/guild_sentinel.db')
# Start in monitor mode. Set to "balanced" after staff reviews alerts.
SECURITY_MODE = os.getenv('SENTINEL_SECURITY_MODE', 'monitor').lower()
if SECURITY_MODE not in {'monitor', 'balanced', 'off'}:
    SECURITY_MODE = 'monitor'

_guild_features_ready = False
_guild_features_lock = asyncio.Lock()
_registration_locks = defaultdict(asyncio.Lock)
_link_events = defaultdict(deque)
_security_alert_cooldowns = {}
_security_modules = {
    'repeat_links': True, 'url_bursts': True, 'attachments': True,
    'phishing_language': True, 'blocked_domains': True,
}
# Explicitly configured verified threat domains only. Don't label unknown sites malicious.
BLOCKED_DOMAINS = {
    x.strip().lower() for x in os.getenv('SENTINEL_BLOCKED_DOMAINS', '').split(',')
    if x.strip() and '.' in x
}
DANGEROUS_SUFFIXES = {
    '.exe', '.scr', '.bat', '.cmd', '.com', '.msi', '.msp', '.ps1',
    '.vbs', '.vbe', '.js', '.jse', '.wsf', '.hta', '.jar', '.lnk',
}
PHISHING_PHRASES = (
    'free nitro', 'verify your discord account', 'discord staff verification',
    'claim your free nitro', 'verify your battle.net password',
)


def db_connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def db_initialize():
    # Never silently place production registration records on ephemeral /app.
    if not os.path.isdir(os.path.dirname(DB_PATH)):
        raise RuntimeError(f'Persistent database directory unavailable: {os.path.dirname(DB_PATH)}')
    with db_connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS registrations (
            user_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
            character TEXT NOT NULL, status TEXT NOT NULL,
            requested_at INTEGER NOT NULL, reviewed_at INTEGER,
            reviewer_id INTEGER, application_message_id INTEGER,
            referral_source TEXT, main_changed_at INTEGER)''')
        # Existing production databases were created without referral_source.
        columns = {row['name'] for row in con.execute('PRAGMA table_info(registrations)')}
        if 'referral_source' not in columns:
            con.execute('ALTER TABLE registrations ADD COLUMN referral_source TEXT')
        if 'main_changed_at' not in columns:
            con.execute('ALTER TABLE registrations ADD COLUMN main_changed_at INTEGER')
        con.execute('''CREATE TABLE IF NOT EXISTS bot_metadata (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at INTEGER NOT NULL,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, reason TEXT NOT NULL, action TEXT NOT NULL)''')
        con.execute('''CREATE TABLE IF NOT EXISTS registration_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at INTEGER NOT NULL,
            event TEXT NOT NULL, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
            character TEXT NOT NULL, prior_status TEXT NOT NULL,
            reviewer_id INTEGER, reviewed_at INTEGER)''')


def db_get_metadata(key):
    with db_connect() as con:
        row = con.execute('SELECT value FROM bot_metadata WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def db_set_metadata(key, value):
    with db_connect() as con:
        con.execute('INSERT OR REPLACE INTO bot_metadata (key,value) VALUES (?,?)', (key, str(value)))


def guild_staff(member):
    return isinstance(member, discord.Member) and (
        member.guild_permissions.administrator or
        bool({OFFICER_ROLE_ID, COUNCIL_ROLE_ID} & {r.id for r in member.roles})
    )


def has_member_role(member):
    return isinstance(member, discord.Member) and any(r.id == MEMBER_ROLE_ID for r in member.roles)


async def post_channel(guild, channel_id, **kwargs):
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except discord.HTTPException:
            return None
    try:
        return await channel.send(allowed_mentions=discord.AllowedMentions.none(), **kwargs)
    except discord.HTTPException as error:
        print(f'Cannot post to channel {channel_id}: {type(error).__name__}')
        return None


def registration_record(user_id):
    with db_connect() as con:
        return con.execute('SELECT * FROM registrations WHERE user_id=?', (user_id,)).fetchone()


def archive_registration(con, record, event):
    """Preserve old approval history before rejoining or submitting a fresh application."""
    con.execute('''INSERT INTO registration_history
        (occurred_at,event,user_id,guild_id,character,prior_status,reviewer_id,reviewed_at)
        VALUES (?,?,?,?,?,?,?,?)''',
        (int(time.time()), event, record['user_id'], record['guild_id'], record['character'],
         record['status'], record['reviewer_id'], record['reviewed_at']))


def valid_character_name(name):
    # Basic validation; Blizzard/Forever rules can differ, so avoid false claims
    # of actual character ownership or existence.
    name = name.strip()
    return name if 2 <= len(name) <= 32 and '\n' not in name and '\r' not in name and '@' not in name else None


async def set_character_nickname(member, character):
    try:
        await member.edit(nick=character, reason='WeNT guild registration')
        return None
    except (discord.Forbidden, discord.HTTPException) as error:
        return type(error).__name__


async def update_registered_main(member, new_character):
    """Allow verified members to rename once per 24 hours; preserve approval metadata."""
    async with _registration_locks[member.id]:
        record = registration_record(member.id)
        if not record or record['status'] != 'approved' or not has_member_role(member):
            return 'Only verified guild members can update a registered main.'
        old_character = record['character']
        if old_character.casefold() == new_character.casefold():
            return f'Your registered main is already **{discord.utils.escape_markdown(old_character)}**.'
        previous_change = record['main_changed_at']
        now = int(time.time())
        if previous_change and now - previous_change < 86400:
            remaining = 86400 - (now - previous_change)
            hours, minutes = divmod((remaining + 59) // 60, 60)
            return f'You can change your main again in approximately {hours}h {minutes}m.'
        nickname_error = await set_character_nickname(member, new_character)
        if nickname_error:
            return ('I could not update your server nickname because of Discord permissions. '
                    'Your registered main was not changed; please contact an Officer or Council member.')
        with db_connect() as con:
            con.execute('''UPDATE registrations SET character=?,main_changed_at=?
                WHERE user_id=? AND status='approved' ''', (new_character, now, member.id))
        embed = discord.Embed(
            title='Registered Main Character Updated', color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name='Member', value=f'{member.mention} (`{member.id}`)', inline=False)
        embed.add_field(name='Previous main', value=discord.utils.escape_markdown(old_character), inline=True)
        embed.add_field(name='New main', value=discord.utils.escape_markdown(new_character), inline=True)
        embed.add_field(name='Changed by', value='Self-service registration', inline=False)
        await send_member_log(member.guild, embed)
        return f'Your registered main and server nickname are now **{discord.utils.escape_markdown(new_character)}**.'


class RegistrationModal(discord.ui.Modal, title='WeNT Guild Registration'):
    character = discord.ui.TextInput(
        label='Main WoW character name', placeholder='Your main character',
        min_length=2, max_length=32,
    )
    referral_source = discord.ui.TextInput(
        label='Where did you hear about WeNT?',
        placeholder='GuildsForever, in-game, friend, other...',
        style=discord.TextStyle.short,
        required=False, max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not _guild_features_ready or not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message('Registration is temporarily unavailable.', ephemeral=True)
            return
        name = valid_character_name(str(self.character))
        if not name:
            await interaction.response.send_message('Please enter a valid character name (2–32 characters).', ephemeral=True)
            return
        member = interaction.user
        source = str(self.referral_source).strip()[:100] or 'Not provided'
        guildsforever_linked = any(role.id == GUILDSFOREVER_ROLE_ID for role in member.roles)
        existing = registration_record(member.id)
        if existing and existing['status'] == 'pending':
            await interaction.response.send_message('You already have an application awaiting staff review.', ephemeral=True)
            return
        # Existing verified members can register their main for the first time.
        self_register = has_member_role(member) and not (existing and existing['status'] == 'approved')
        if self_register:
            error = await set_character_nickname(member, name)
            with db_connect() as con:
                con.execute('''INSERT OR REPLACE INTO registrations
                    (user_id,guild_id,character,status,requested_at,reviewed_at,reviewer_id,application_message_id,referral_source)
                    VALUES (?,?,?,?,?,?,?,NULL,?)''',
                    (member.id, interaction.guild.id, name, 'approved', int(time.time()), int(time.time()), member.id, source))
            await interaction.response.send_message(
                f'Character registered as **{discord.utils.escape_markdown(name)}**.' +
                (' Staff must update your nickname due to permissions.' if error else ' Your server nickname is updated.'),
                ephemeral=True,
            )
            return
        if existing and existing['status'] == 'approved' and has_member_role(member):
            result = await update_registered_main(member, name)
            await interaction.response.send_message(result, ephemeral=True)
            return
        now = int(time.time())
        with db_connect() as con:
            if existing:
                archive_registration(con, existing, 'new_application')
            con.execute('''INSERT OR REPLACE INTO registrations
                (user_id,guild_id,character,status,requested_at,reviewed_at,reviewer_id,application_message_id,referral_source)
                VALUES (?,?,?,?,?,NULL,NULL,NULL,?)''',
                (member.id, interaction.guild.id, name, 'pending', now, source))
        embed = discord.Embed(title='Guild membership application', color=discord.Color.gold())
        embed.add_field(name='Discord account', value=f'{member.mention} (`{member.id}`)', inline=False)
        embed.add_field(name='Claimed main character', value=discord.utils.escape_markdown(name), inline=False)
        embed.add_field(name='How they found WeNT', value=discord.utils.escape_markdown(source), inline=False)
        embed.add_field(name='GuildsForever role', value='Present' if guildsforever_linked else 'Not present', inline=False)
        if existing and existing['status'] in {'approved', 'rejoined'}:
            embed.add_field(
                name='Prior registration',
                value=(f'Previous character: **{discord.utils.escape_markdown(existing["character"])}**. '
                       'No current Member role; re-verification required.'),
                inline=False,
            )
        embed.set_footer(text='Confirm actual WoW guild membership before approving.')
        post = await post_channel(interaction.guild, APPLICATIONS_CHANNEL_ID, embed=embed, view=ApplicationReviewView())
        if not post:
            with db_connect() as con:
                con.execute("UPDATE registrations SET status='delivery_failed' WHERE user_id=? AND status='pending'", (member.id,))
            await interaction.response.send_message('Could not submit your application. Please notify leadership.', ephemeral=True)
            return
        with db_connect() as con:
            con.execute('UPDATE registrations SET application_message_id=? WHERE user_id=?', (post.id, member.id))
        await interaction.response.send_message('Application sent to leadership. You will remain a PUG until approved.', ephemeral=True)


class RegistrationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Register for WeNT', style=discord.ButtonStyle.primary, custom_id='went:register')
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _guild_features_ready:
            await interaction.response.send_message('Registration is temporarily unavailable.', ephemeral=True)
            return
        await interaction.response.send_modal(RegistrationModal())


class ApplicationReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def review(self, interaction, approve):
        if not _guild_features_ready or not interaction.guild or not guild_staff(interaction.user):
            await interaction.response.send_message('Only Officers or Council may review applications.', ephemeral=True)
            return
        with db_connect() as con:
            row = con.execute('''SELECT * FROM registrations WHERE application_message_id=? AND guild_id=?''',
                              (interaction.message.id, interaction.guild.id)).fetchone()
        if not row or row['status'] != 'pending':
            await interaction.response.send_message('This application is already resolved or unavailable.', ephemeral=True)
            return
        member = interaction.guild.get_member(row['user_id'])
        if member is None:
            try:
                member = await interaction.guild.fetch_member(row['user_id'])
            except discord.HTTPException:
                member = None
        if approve and member is None:
            await interaction.response.send_message('Applicant is no longer in this server.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if approve:
            role = interaction.guild.get_role(MEMBER_ROLE_ID)
            if not role:
                await interaction.followup.send('Member role not found.', ephemeral=True)
                return
            try:
                await member.add_roles(role, reason=f'Guild membership approved by {interaction.user.id}')
            except (discord.Forbidden, discord.HTTPException):
                await interaction.followup.send('Unable to assign Member role. Check role hierarchy and permissions.', ephemeral=True)
                return
            nickname_error = await set_character_nickname(member, row['character'])
        else:
            nickname_error = None
        with db_connect() as con:
            updated = con.execute('''UPDATE registrations SET status=?,reviewed_at=?,reviewer_id=?
                WHERE user_id=? AND status='pending' ''',
                ('approved' if approve else 'declined', int(time.time()), interaction.user.id, row['user_id']))
            if updated.rowcount != 1:
                await interaction.followup.send('Application was already resolved.', ephemeral=True)
                return
        action = 'Approved' if approve else 'Declined'
        try:
            embed = interaction.message.embeds[0].copy()
            embed.title = f'Guild application — {action}'
            embed.color = discord.Color.green() if approve else discord.Color.red()
            embed.add_field(name='Reviewed by', value=interaction.user.mention, inline=False)
            await interaction.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass
        await send_member_log(interaction.guild, discord.Embed(
            title=f'Guild registration {action.lower()}',
            description=f'User ID: `{row["user_id"]}`\nCharacter: {discord.utils.escape_markdown(row["character"])}\nReviewer: {interaction.user.mention}',
            timestamp=discord.utils.utcnow(),
        ))
        await interaction.followup.send(
            f'{action}.' + (' Member role assigned, but nickname update failed; please update manually.' if nickname_error else ''),
            ephemeral=True,
        )

    @discord.ui.button(label='Approve Member', style=discord.ButtonStyle.success, custom_id='went:approve')
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.review(interaction, True)

    @discord.ui.button(label='Decline', style=discord.ButtonStyle.danger, custom_id='went:decline')
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.review(interaction, False)


async def initialize_guild_features():
    global _guild_features_ready
    if _guild_features_ready:
        return
    async with _guild_features_lock:
        if _guild_features_ready:
            return
        try:
            db_initialize()
            bot.add_view(RegistrationView())
            bot.add_view(ApplicationReviewView())
            # Only post the persistent button once; re-use after reconnects.
            guild = next((g for g in bot.guilds if g.get_channel(REGISTRATION_CHANNEL_ID)), None)
            if guild:
                channel = guild.get_channel(REGISTRATION_CHANNEL_ID)
                message_id = db_get_metadata('registration_panel_message_id')
                panel_exists = False
                if message_id:
                    try:
                        await channel.fetch_message(int(message_id))
                        panel_exists = True
                    except discord.HTTPException:
                        pass
                if not panel_exists:
                    embed = discord.Embed(
                        title='Join We Need Therapy',
                        description=('Joining our WoW guild? Click below and enter your main character name. '
                                     'An Officer or Council member will verify your membership. '
                                     '**PUG guests do not need to register.**'),
                        color=discord.Color.blurple(),
                    )
                    panel = await post_channel(guild, REGISTRATION_CHANNEL_ID, embed=embed, view=RegistrationView())
                    if panel:
                        db_set_metadata('registration_panel_message_id', panel.id)
            _guild_features_ready = True
            print('Guild registration and Security Watch initialized.')
        except (OSError, sqlite3.Error, RuntimeError, discord.HTTPException) as error:
            print(f'Guild features unavailable; link cleaning remains active: {error}')


def domain_matches(domain, candidate):
    return domain == candidate or domain.endswith('.' + candidate)


async def security_alert(message, reason, action):
    if not _guild_features_ready:
        return
    now = int(time.time())
    with db_connect() as con:
        con.execute('''INSERT INTO security_events (occurred_at,guild_id,user_id,channel_id,reason,action)
            VALUES (?,?,?,?,?,?)''', (now, message.guild.id, message.author.id, message.channel.id, reason, action))
    key = (message.author.id, reason)
    if now - _security_alert_cooldowns.get(key, 0) < 120:
        return
    _security_alert_cooldowns[key] = now
    embed = discord.Embed(title='Guild Sentinel — Security Watch', color=discord.Color.orange())
    embed.add_field(name='Reason', value=reason, inline=False)
    embed.add_field(name='Action', value=action, inline=True)
    embed.add_field(name='Account ID', value=f'`{message.author.id}`', inline=True)
    embed.add_field(name='Channel', value=f'<#{message.channel.id}>', inline=True)
    # No content, URL, attachment link, or tokens echoed to alerts.
    await post_channel(message.guild, SECURITY_CHANNEL_ID, embed=embed)


async def security_inspect(message):
    """Return True when the original message was successfully deleted."""
    if not _guild_features_ready or SECURITY_MODE == 'off':
        return False
    now = time.monotonic()
    urls = re.findall(REGEX, message.content)[:20]
    normalized_urls = set()
    blocked = False
    for url in urls:
        parsed = urlparse(url if '://' in url else 'https://' + url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if any(domain_matches(host, domain) for domain in BLOCKED_DOMAINS):
            blocked = True
        normalized_urls.add((host, parsed.path))
    # File extension screening, including double extensions like image.png.exe.
    dangerous_files = [a.filename for a in message.attachments
                       if PurePosixPath(a.filename.lower()).suffix in DANGEROUS_SUFFIXES]
    reason = None
    high_confidence = False
    if dangerous_files:
        reason, high_confidence = 'Executable or script attachment', True
    elif blocked:
        reason, high_confidence = 'Domain on administrator-maintained blocklist', True
    else:
        relaxed = message.channel.id in RELAXED_SECURITY_CHANNEL_IDS
        phrase_match = any(p in message.content.lower() for p in PHISHING_PHRASES)
        if not relaxed:
            history = _link_events[message.author.id]
            history.append((now, message.channel.id, normalized_urls))
            while history and now - history[0][0] > 90:
                history.popleft()
            cross_posts = sum(1 for _, channel, links in history if channel != message.channel.id and links & normalized_urls)
            burst = sum(1 for _, _, links in history if links)
            if normalized_urls and cross_posts >= 2:
                reason = 'Repeated link across multiple channels'
            elif normalized_urls and burst >= 6:
                reason = 'Unusually high link-posting rate'
        if not reason and phrase_match:
            reason = 'Phishing-related message language (review required)'
    if not reason:
        return False
    action = 'Alert only'
    if high_confidence and SECURITY_MODE == 'balanced':
        try:
            await message.delete()
            action = 'Message removed'
        except discord.HTTPException:
            action = 'Deletion failed — check Manage Messages'
    await security_alert(message, reason, action)
    return action == 'Message removed'


security_group = app_commands.Group(name='security', description='Guild Sentinel security controls')


@security_group.command(name='status', description='Check Security Watch health and recent detections')
async def security_status(interaction: discord.Interaction):
    if not guild_staff(interaction.user):
        await interaction.response.send_message('Officer or Council access required.', ephemeral=True)
        return
    if not _guild_features_ready:
        await interaction.response.send_message('Security database is unavailable. Check Railway logs and volume.', ephemeral=True)
        return
    since = int(time.time()) - 86400
    with db_connect() as con:
        recent = con.execute('''SELECT action,COUNT(*) AS count FROM security_events
            WHERE occurred_at>=? GROUP BY action''', (since,)).fetchall()
    actions = ', '.join(f'{row["action"]}: {row["count"]}' for row in recent) or 'None'
    embed = discord.Embed(title='Guild Sentinel — Security Status', color=discord.Color.blue())
    embed.add_field(name='Mode', value=SECURITY_MODE, inline=True)
    embed.add_field(name='Detections (24 hours)', value=str(sum(row['count'] for row in recent)), inline=True)
    embed.add_field(name='Actions (24 hours)', value=actions, inline=False)
    embed.add_field(name='Detectors', value='\n'.join(
        f'{name.replace("_", " ").title()}: {"Enabled" if enabled else "Disabled"}'
        for name, enabled in _security_modules.items()), inline=False)
    embed.add_field(name='Relaxed channels', value=(
        f'{len(RELAXED_SECURITY_CHANNEL_IDS)} channels exempt from behavioral link-frequency alerts; '
        'malicious domains, dangerous attachments and phishing-language alerts remain active.'), inline=False)
    embed.add_field(name='Threat intelligence', value=(
        f'{len(BLOCKED_DOMAINS)} manually configured blocked domains; no automatic threat feed configured. '
        'Freshness: not available.'), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(security_group)

bot.run(bot_token)
