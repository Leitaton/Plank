import redis, json
url = "rediss://default:gQAAAAAAAaw7AAIgcDFkNDljMjQ2MzZjZDM0MGZlOTVkY2UyN2ZlMDU0OWI3YQ@divine-lemur-109627.upstash.io:6379"
r = redis.from_url(url, decode_responses=True, socket_connect_timeout=8)

t = r.type("hit_logs")
print("hit_logs type:", t)
if t == "list":
    print("len:", r.llen("hit_logs"))
    items = r.lrange("hit_logs", -5, -1)
    for i in items:
        print("item:", i[:300])
elif t == "stream":
    items = r.xrevrange("hit_logs", count=3)
    for i in items:
        print("stream item:", i)
elif t == "string":
    print("val:", r.get("hit_logs")[:300])

# also check mass_session sample
ms_keys = [k for k in r.keys("mass_session:*")]
if ms_keys:
    k = ms_keys[0]
    t2 = r.type(k)
    print(f"\n{k} type:{t2}")
    if t2 == "string":
        v = r.get(k)
        print(json.dumps(json.loads(v), indent=2)[:500])
    elif t2 == "hash":
        print(r.hgetall(k))
