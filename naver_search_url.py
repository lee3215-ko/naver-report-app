"""네이버 통합검색 URL 생성 (tqi, ackey 등 실제 파라미터 포함)."""
import time
from urllib.parse import parse_qs, quote, urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from chrome_browser import DEFAULT_BROWSER_MODE, create_webdriver


def build_naver_search_url_simple(keyword: str) -> str:
    kw = (keyword or "").strip()
    if not kw:
        return ""
    return f"https://search.naver.com/search.naver?query={quote(kw)}"


def _log_fresh_search_url(log, keyword: str, url: str):
    if not log:
        return
    qs = parse_qs(urlparse(url).query)
    tqi = (qs.get("tqi") or [""])[0]
    ackey = (qs.get("ackey") or [""])[0]
    if tqi and ackey:
        log(f"실시간 검색 [{keyword}] → tqi·ackey 신규 발급 (ackey={ackey})")
    else:
        log(f"실시간 검색 [{keyword}] → URL 확보 (tqi·ackey 미포함)")


def fetch_naver_search_url_live(keyword: str, driver=None, log=None, browser_mode: str = DEFAULT_BROWSER_MODE) -> str:
    """매 호출마다 네이버 검색을 수행해 새 tqi·ackey가 붙은 URL을 반환합니다."""
    kw = (keyword or "").strip()
    if not kw:
        return ""

    owns_driver = driver is None
    if owns_driver and log:
        log(f"네이버 실시간 검색 중 [{kw}]...")

    if owns_driver:
        driver, _info = create_webdriver(browser_mode, headless=True)

    try:
        driver.get(f"https://search.naver.com/search.naver?query={quote(kw)}")
        time.sleep(1.2)
        box = driver.find_element(By.CSS_SELECTOR, "input[name='query']")
        box.clear()
        box.send_keys(kw)
        box.send_keys(Keys.ENTER)
        time.sleep(2)
        url = driver.current_url
        if "search.naver.com" in url and "query=" in url:
            _log_fresh_search_url(log, kw, url)
            return url
        if log:
            log(f"실시간 검색 [{kw}] → 기본 URL로 대체")
        return build_naver_search_url_simple(kw)
    except Exception as exc:
        if log:
            log(f"실시간 검색 실패 [{kw}] → 기본 URL ({exc})")
        return build_naver_search_url_simple(kw)
    finally:
        if owns_driver and driver is not None:
            driver.quit()


def build_naver_search_url(keyword: str, *, driver=None, log=None, live: bool = True, browser_mode: str = DEFAULT_BROWSER_MODE) -> str:
    if not live:
        return build_naver_search_url_simple(keyword)
    return fetch_naver_search_url_live(keyword, driver=driver, log=log, browser_mode=browser_mode)
