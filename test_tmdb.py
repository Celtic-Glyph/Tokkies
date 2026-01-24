import os
import requests
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

def test_tmdb():
    url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": "Inception"  # test with a known movie
    }
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            movie = data["results"][0]
            print("✅ TMDb API is working!")
            print("First result:", movie["title"], f"(id: {movie['id']})")
        else:
            print("⚠️ API worked, but no results found.")
    else:
        print("❌ Something went wrong:", response.status_code, response.text)

if __name__ == "__main__":
    test_tmdb()
