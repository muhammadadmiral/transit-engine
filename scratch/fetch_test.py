import httpx
query = """
[out:json][timeout:120];
relation["route"="share_taxi"]["network"~"Depok",i];
out geom;
"""
headers = {"User-Agent": "transit-engine/1.0"}
resp = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers=headers, timeout=120)
print(resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print("Found:", len(data.get("elements", [])))
