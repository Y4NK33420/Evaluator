import json, urllib.request
with urllib.request.urlopen("http://localhost:8080/openapi.json") as r:
    d = json.loads(r.read())
for path, methods in sorted(d["paths"].items()):
    for method in methods:
        op = d["paths"][path][method]
        tag = (op.get("tags") or [""])[0]
        print(f"{method.upper():7} {path}  [{tag}]")
