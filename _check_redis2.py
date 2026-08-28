import redis
url = "rediss://default:gQAAAAAAAaw7AAIgcDFkNDljMjQ2MzZjZDM0MGZlOTVkY2UyN2ZlMDU0OWI3YQ@divine-lemur-109627.upstash.io:6379"
r = redis.from_url(url, decode_responses=True, socket_connect_timeout=8)
keys = r.keys("*")
non_bin = [k for k in keys if not k.startswith("bin:")]
print("non-bin keys:", non_bin)
for k in non_bin:
    t = r.type(k)
    print(f"  {k} => type:{t}")
    if t == "string":
        print(f"    val: {r.get(k)[:200]}")
    elif t == "list":
        print(f"    len={r.llen(k)}, sample={r.lrange(k,0,2)}")
    elif t == "hash":
        print(f"    fields={r.hgetall(k)}")
    elif t == "set":
        print(f"    members={list(r.smembers(k))[:5]}")
