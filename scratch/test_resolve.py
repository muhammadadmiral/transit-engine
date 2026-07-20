import urllib.parse
from app.core.config import get_settings
import socket

url = get_settings().database_url
parsed = urllib.parse.urlparse(url)
print("Original host:", parsed.hostname)
ip = socket.gethostbyname(parsed.hostname)
print("Resolved IP:", ip)
