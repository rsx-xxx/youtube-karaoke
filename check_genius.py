# File: backend/check_token.py
import os
from dotenv import load_dotenv
import lyricsgenius

# Load environment variables from .env file
load_dotenv()
token = os.environ.get("GENIUS_API_TOKEN")

if not token:
    print("ERROR: GENIUS_API_TOKEN not found in environment/.env file.")
else:
    print(f"Found Token: ...{token[-6:]}") # Print last few chars for confirmation
    try:
        print("Attempting to initialize Genius client...")
        # Increase timeout for testing
        genius = lyricsgenius.Genius(token, timeout=30, retries=1, verbose=False)
        print("Genius client initialized successfully.")

        # Test search (use a common song known to be on Genius)
        test_title = "Bohemian Rhapsody"
        test_artist = "Queen"
        print(f"Attempting to search for '{test_title}' by {test_artist}...")
        song = genius.search_song(test_title, test_artist)

        if song:
            print(f"SUCCESS: Found song: {song.title} by {song.artist}")
            print(f"Lyrics snippet:\n---\n{song.lyrics[:150]}...\n---")
            print("\nYour Genius Token appears to be working!")
        else:
            print(f"WARNING: Could not find '{test_title}'. This might be a search issue, but the token allowed client initialization.")
            # Try searching just by title
            print(f"Attempting search for title '{test_title}' only...")
            song_title_only = genius.search_song(test_title)
            if song_title_only:
                print(f"SUCCESS (Title only): Found song: {song_title_only.title} by {song_title_only.artist}")
                print("Your Genius Token appears to be working!")
            else:
                print("WARNING: Could not find song by title only either. There might be an issue with the search or the API, but token likely allowed connection.")


    except Exception as e:
        print(f"\n--- ERROR ---")
        print(f"An error occurred while using the Genius token:")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Details: {e}")
        print("This could indicate an invalid token, network issues, or API changes.")
        print("Check your token and network connection.")

print("\nCheck finished.")