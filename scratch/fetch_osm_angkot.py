import httpx
import json

query = """
[out:json][timeout:60];
(
  relation["route"="share_taxi"](-6.44, 106.75, -6.34, 106.87);
  relation["route"="minibus"](-6.44, 106.75, -6.34, 106.87);
  relation["route"="bus"](-6.44, 106.75, -6.34, 106.87);
);
out geom;
"""
headers = {"User-Agent": "transit-engine/1.0"}
response = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers=headers, timeout=60.0)
result = response.json()
relations = result.get("elements", [])
print(f"Found {len(relations)} relations.")
for r in relations:
    tags = r.get('tags', {})
    print(f"- {tags.get('ref', '')}: {tags.get('name', 'Unknown')}")
