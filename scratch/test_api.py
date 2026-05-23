import urllib.request
import json

try:
    req = urllib.request.Request("http://127.0.0.1:8010/api/cards?limit=1200")
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode('utf-8'))
        print("API Cards Response:")
        print("Number of cards:", len(data))
        if len(data) > 0:
            print("First card sample:", data[0])
except Exception as e:
    print("Error:", e)
