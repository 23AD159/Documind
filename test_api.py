import os
from google import genai
from google.genai import types

def test_api_key(api_key):
    print(f"Testing API Key: {api_key[:10]}...")
    try:
        client = genai.Client(api_key=api_key)
        # Try a simple models list to see if key works
        models = client.models.list()
        print("Success: API Key is valid and can list models.")
        
        # Try a tiny generation
        resp = client.models.generate_content(model="gemini-1.5-flash", contents="Hi")
        print(f"Success: Generation worked. Response: {resp.text}")
        return True
    except Exception as e:
        print(f"Error: API Key validation failed: {e}")
        return False

if __name__ == "__main__":
    # The API key from the user's screenshot
    KEY = "AIzaSyAuZeADDySFCP7W8JuyXPZJmW8jYT06w3Y"
    test_api_key(KEY)
