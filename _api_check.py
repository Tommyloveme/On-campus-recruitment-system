import urllib.request, json, http.cookiejar as hc

cj = hc.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def post(u, d):
    req = urllib.request.Request(u, data=json.dumps(d).encode(), headers={"Content-Type": "application/json"})
    return json.loads(op.open(req).read())

def get(u):
    return json.loads(op.open(u).read())

me = post("http://127.0.0.1:8000/api/login", {"username": "admin", "password": "admin123"})
print("login", me["display_name"])
o = get("http://127.0.0.1:8000/api/permissions/options")
print("users", len(o["users"]), "fields", [f["key"] for f in o["user_fields"]])
print("modules", [m["key"] for m in o["modules"]])
a = get("http://127.0.0.1:8000/api/module-acl")
print("acl entries", len(a), "sample", a[0] if a else None)
print("account opts keys", list(get("http://127.0.0.1:8000/api/account/options").keys()))
mods = get("http://127.0.0.1:8000/api/permissions/modules")
print("modules payload sections", [m["key"] for m in mods["modules"]])
