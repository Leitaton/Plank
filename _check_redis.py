import redis, json
url = "rediss://default:gQAAAAAAAaw7AAIgcDFkNDljMjQ2MzZjZDM0MGZlOTVkY2UyN2ZlMDU0OWI3YQ@divine-lemur-109627.upstash.io:6379"
r = redis.from_url(url, decode_responses=True, socket_connect_timeout=8)
print("ping:", r.ping())
print("dbsize:", r.dbsize())
keys = r.keys("*")
print("all keys:", keys[:50])
for k in keys[:10]:
    t = r.type(k)
    if t == "string":
        print(f"  {k} => {r.get(k)[:100]}")
    elif t == "list":
        print(f"  {k} => list len={r.llen(k)}, first={r.lindex(k,0)}")
    elif t == "hash":
        print(f"  {k} => hash fields={r.hkeys(k)[:5]}")
    else:
        print(f"  {k} => type:{t}")
