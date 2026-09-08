import json
import os
import random
import re
import time
import base64
from datetime import datetime
from urllib.parse import quote, urlparse, urlunparse

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    NoAlertPresentException,
    ElementNotInteractableException,
    InvalidSessionIdException,
    WebDriverException,
    UnexpectedAlertPresentException,
)
from chrome_browser import create_webdriver, normalize_browser_mode
from naver_search_url import fetch_naver_search_url_live


class NaverReporter:
    """네이버 고객센터 불법성 신고 자동화 (Selenium)"""

    INQUIRY_FORM_URL = (
        "https://help.naver.com/inquiry/input.help?categoryNo=5749&serviceNo=5626&lang=ko"
    )

    def __init__(self,
                 api_key: str,
                 model: str,
                 headless: bool = False,
                 browser_mode: str = "chrome",
                 log_callback=None,
                 result_callback=None,
                 progress_callback=None):
        self.api_key = api_key
        self.model = model
        self.headless = headless
        self.browser_mode = normalize_browser_mode(browser_mode)
        self.log_callback = log_callback or print
        self.result_callback = result_callback
        self.progress_callback = progress_callback
        self.driver = None
        self.cancel_requested = False
        self._last_popup_message = ""
        self._last_login_restriction_reason = ""
        self._last_login_restriction_date = ""
        self.client = self._openai_client()

    def request_cancel(self):
        self.cancel_requested = True
        if self.driver:
            self.log("작업 중단 — 브라우저 종료")
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _should_stop(self) -> bool:
        return self.cancel_requested

    def _interruptible_sleep(self, seconds: float) -> bool:
        """취소 시 즉시 반환. True = 중단됨."""
        if seconds <= 0:
            return self._should_stop()
        end = time.time() + seconds
        while time.time() < end:
            if self._should_stop():
                return True
            time.sleep(min(0.08, end - time.time()))
        return self._should_stop()

    def _openai_client(self):
        try:
            import openai
            return openai.OpenAI(api_key=self.api_key)
        except Exception as e:
            self.log(f"OpenAI 클라이언트 초기화 오류: {e}")
            return None

    def log(self, message):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{ts}] {message}")

    def _human_delay(self, min_sec: float = 0.8, max_sec: float = 2.5):
        self._interruptible_sleep(random.uniform(min_sec, max_sec))

    def _cafe_fast_delay(self, min_sec: float = 0.08, max_sec: float = 0.22):
        """카페 신고 팝업 — 짧은 대기."""
        self._interruptible_sleep(random.uniform(min_sec, max_sec))

    def _wait_until(self, predicate, timeout: float = 15, interval: float = 0.2) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._should_stop() or not self.driver:
                return False
            try:
                if predicate():
                    return True
            except (InvalidSessionIdException, WebDriverException):
                if self._should_stop() or not self.driver:
                    return False
                raise
            except Exception:
                if self._should_stop() or not self.driver:
                    return False
            if self._interruptible_sleep(interval):
                return False
        return False

    def _is_on_inquiry_form(self) -> bool:
        try:
            if "inquiry/input.help" not in self.driver.current_url:
                return False
            el = self.driver.find_element(By.ID, "requiredUrl1")
            return el.is_displayed()
        except Exception:
            return False

    def _go_to_inquiry_page(self):
        if self._is_on_inquiry_form():
            return
        self.driver.get(self.INQUIRY_FORM_URL)
        self.log("신고 작성 페이지로 이동")
        self._human_delay(2.0, 4.0)
        wait = self._wait(25)
        wait.until(EC.visibility_of_element_located((By.ID, "requiredUrl1")))

    def _wait_after_submit(self, timeout: int = 30) -> bool:
        return self._wait_submit_success(timeout)

    def _ensure_default_content(self):
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

    def _alert_present_on_current(self) -> bool:
        try:
            self._ensure_default_content()
            _ = self.driver.switch_to.alert.text
            return True
        except NoAlertPresentException:
            return False
        except Exception:
            return False

    def _read_alert_if_present(self, dismiss: bool = True) -> str | None:
        """현재 창 JS alert 즉시 읽기."""
        try:
            alert = self.driver.switch_to.alert
            text = (alert.text or "").strip()
            if dismiss:
                alert.accept()
                if text:
                    self.log(f"팝업 확인: {text}")
            return text or None
        except NoAlertPresentException:
            return None
        except Exception:
            return None

    def _normalize_popup_text(self, text: str) -> str:
        return (text or "").replace(" ", "").replace("\u00a0", "").replace(".", "").replace("。", "")

    def _read_popup_message(self, timeout: float = 2.0, dismiss: bool = True) -> str | None:
        """alert / HTML 확인 팝업 메시지 읽기."""
        end = time.time() + max(timeout, 0)
        while time.time() < end:
            if self._should_stop():
                return None

            text = self._read_alert_if_present(dismiss=dismiss)
            if text:
                return text

            self._ensure_default_content()
            wait_sec = min(0.6, max(end - time.time(), 0.05))
            try:
                WebDriverWait(self.driver, wait_sec).until(EC.alert_is_present())
                text = self._read_alert_if_present(dismiss=dismiss)
                if text:
                    return text
            except TimeoutException:
                pass
            except UnexpectedAlertPresentException:
                text = self._read_alert_if_present(dismiss=dismiss)
                if text:
                    return text
            except NoAlertPresentException:
                pass
            except WebDriverException as e:
                if "alert" in str(e).lower():
                    text = self._read_alert_if_present(dismiss=dismiss)
                    if text:
                        return text
            except Exception as e:
                err = str(e).lower()
                if "alert" in err or "unexpected alert" in err:
                    text = self._read_alert_if_present(dismiss=dismiss)
                    if text:
                        return text
                    continue
                if "no alert" not in err and "no such alert" not in err:
                    break

            html_text = self._try_read_html_confirm_popup(dismiss=dismiss)
            if html_text:
                return html_text

            layer = self._try_dismiss_naver_blog_alert_layer() if dismiss else None
            if layer:
                return layer

            remaining = end - time.time()
            if remaining <= 0:
                break
            if self._interruptible_sleep(min(0.1, remaining)):
                return None
        return None

    def _try_read_html_confirm_popup(self, dismiss: bool = True) -> str | None:
        try:
            text = self.driver.execute_script(
                """
                var dismiss = arguments[0];
                function readDoc(doc) {
                    if (!doc || !doc.body) return '';
                    var selectors = [
                        '[role="dialog"]', '.modal', '.layer_popup', '.popup', '.ly_pop',
                        'div[class*="popup"]', 'div[class*="layer"]', 'div[class*="alert"]'
                    ];
                    for (var si = 0; si < selectors.length; si++) {
                        var nodes = doc.querySelectorAll(selectors[si]);
                        for (var i = 0; i < nodes.length; i++) {
                            var el = nodes[i];
                            var style = doc.defaultView.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden') continue;
                            var t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                            if (!t || t.length > 400) continue;
                            var btns = el.querySelectorAll('button, a, input[type="button"]');
                            for (var b = 0; b < btns.length; b++) {
                                var btn = btns[b];
                                var bt = (btn.innerText || btn.value || btn.textContent || '').replace(/\\s+/g, '').trim();
                                if (bt === '확인' || bt === 'OK' || bt.indexOf('확인') === 0) {
                                    if (dismiss) btn.click();
                                    return t.slice(0, 300);
                                }
                            }
                        }
                    }
                    return '';
                }
                var found = readDoc(document);
                if (found) return found;
                var frames = document.querySelectorAll('iframe');
                for (var f = 0; f < frames.length; f++) {
                    try {
                        var doc = frames[f].contentDocument || frames[f].contentWindow.document;
                        found = readDoc(doc);
                        if (found) return found;
                    } catch (e) {}
                }
                return '';
                """,
                dismiss,
            )
            if text and text.strip() not in ("확인", "OK"):
                if dismiss:
                    self.log(f"팝업 확인(HTML): {text[:80]}")
                return text.strip()
        except WebDriverException as e:
            if "alert" in str(e).lower():
                return self._read_alert_if_present(dismiss=dismiss)
        except UnexpectedAlertPresentException:
            return self._read_alert_if_present(dismiss=dismiss)
        except Exception:
            pass
        return None

    def _is_already_reported_alert(self, text: str) -> bool:
        if not text or text.strip() in ("확인", "OK", "dialog"):
            return False
        raw = text.strip()
        if "이미 신고" in raw or "이미신고" in raw:
            return True
        normalized = self._normalize_popup_text(text)
        return any(
            k in normalized
            for k in (
                "이미신고",
                "이미신고되",
                "이미신고되었",
                "이미신고한",
                "이미신고하",
                "신고하셨",
                "신고된",
            )
        ) and "성공" not in normalized

    def _is_blog_report_success_alert(self, text: str) -> bool:
        if not text:
            return False
        normalized = self._normalize_popup_text(text)
        if self._is_already_reported_alert(text):
            return False
        return (
            "성공적으로접수" in normalized
            or "신고를성공적으로" in normalized
            or "신고가성공" in normalized
            or ("신고" in normalized and "성공" in normalized and "접수" in normalized)
            or ("접수" in normalized and "완료" in normalized)
            or ("접수" in normalized and "성공" in normalized)
            or "접수했습니다" in normalized
        )

    def _classify_popup_message(self, text: str | None) -> str:
        """ok | already | failed | unknown"""
        if not text or text.strip() in ("확인", "OK", "dialog"):
            return "unknown"
        if self._is_already_reported_alert(text):
            return "already"
        if self._is_blog_report_success_alert(text):
            return "ok"
        if self._is_blog_report_validation_alert(text):
            return "failed"
        if any(k in text for k in ("불가", "제한", "실패", "오류")):
            return "failed"
        return "unknown"

    def _handle_report_popup_if_any(self, timeout: float = 3.0) -> str | None:
        """팝업 문자열을 읽어 ok / already 반환."""
        end = time.time() + timeout
        while time.time() < end:
            if self._should_stop():
                return None
            msg = self._read_popup_message(timeout=min(1.0, end - time.time()), dismiss=True)
            if msg:
                self._last_popup_message = msg
                status = self._classify_popup_message(msg)
                self.log(f"팝업 분류: [{status}] {msg[:120]}")
                if status == "already":
                    return "already"
                if status == "ok":
                    return "ok"
            remaining = end - time.time()
            if remaining <= 0:
                break
            if self._interruptible_sleep(min(0.08, remaining)):
                return None
        return None

    def _wait_report_popup_outcome(self, timeout: float = 12.0) -> str | None:
        """srp2 신고창: JS alert(이미 신고/성공) 또는 사유폼 로드 대기.

        ok / already / failed → 즉시 반환, None → 사유폼 준비됨(신고 진행).
        """
        end = time.time() + max(timeout, 0)
        self.log("신고 팝업 — alert 또는 사유폼 대기...")
        while time.time() < end:
            if self._should_stop() or not self.driver:
                return "stopped"

            text = self._read_alert_if_present(dismiss=True)
            if text:
                self._last_popup_message = text
                status = self._classify_popup_message(text)
                self.log(f"팝업 분류: [{status}] {text[:120]}")
                if status in ("ok", "already", "failed"):
                    return status

            try:
                if self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "input.report_reason, .lst_reason, .list_type, a.btn_submit",
                ):
                    self.log("신고 사유 선택 UI 확인")
                    return None
            except UnexpectedAlertPresentException:
                continue
            except WebDriverException as e:
                if "alert" in str(e).lower():
                    continue

            remaining = end - time.time()
            if remaining <= 0:
                break
            if self._interruptible_sleep(min(0.12, remaining)):
                return "stopped"

        text = self._read_popup_message(timeout=2.5, dismiss=True)
        if text:
            self._last_popup_message = text
            status = self._classify_popup_message(text)
            self.log(f"팝업 분류(최종): [{status}] {text[:120]}")
            if status in ("ok", "already", "failed"):
                return status
        return None

    def _accept_alert_on_current(self, timeout: float = 3) -> str | None:
        """현재 창 alert 확인 (창 전환 없음)."""
        return self._read_popup_message(timeout=timeout, dismiss=True)

    def _accept_already_reported_on_current(self) -> bool:
        """현재 창에서 '이미 신고' alert만 확인."""
        if not self._alert_present_on_current():
            return False
        try:
            self._ensure_default_content()
            alert = self.driver.switch_to.alert
            text = (alert.text or "").strip()
            if not self._is_already_reported_alert(text):
                return False
            alert.accept()
            self._last_popup_message = text
            self.log(f"이미 신고된 게시물 — 확인: {text}")
            return True
        except Exception:
            return False

    def _try_accept_alert_now(self) -> str | None:
        return self._accept_alert_on_current(timeout=0)

    def _dismiss_blocking_alert_now(self) -> str | None:
        return self._accept_alert_on_current(timeout=0.05)

    def _try_dismiss_naver_blog_alert_layer(self) -> str | None:
        """네이버 블로그 커스텀 확인 레이어(alert 형태) 처리."""
        self._ensure_default_content()
        try:
            text = self.driver.execute_script(
                """
                function clickAlreadyReported(doc) {
                    if (!doc || !doc.body) return '';
                    var candidates = doc.querySelectorAll(
                        'p, div, span, strong, li, td, .msg, .text, [class*="alert"], [class*="Alert"], [class*="popup"], [class*="layer"]'
                    );
                    for (var i = 0; i < candidates.length; i++) {
                        var el = candidates[i];
                        if (!el.offsetParent && el.getBoundingClientRect().height === 0) continue;
                        var t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!t || t.length > 120) continue;
                        if (t.indexOf('이미 신고') < 0 && t.indexOf('이미신고') < 0) continue;
                        var root = el;
                        for (var up = 0; up < 12 && root; up++) {
                            var btns = root.querySelectorAll
                                ? root.querySelectorAll('button, a, span, div[role="button"], input[type="button"]')
                                : [];
                            for (var b = 0; b < btns.length; b++) {
                                var btn = btns[b];
                                var bt = (btn.innerText || btn.value || btn.textContent || '').replace(/\\s+/g, '').trim();
                                if (bt === '확인' || bt === 'OK' || bt.indexOf('확인') === 0) {
                                    btn.click();
                                    return t.slice(0, 200);
                                }
                            }
                            root = root.parentElement;
                        }
                    }
                    return '';
                }
                var found = clickAlreadyReported(document);
                if (found) return found;
                var frames = document.querySelectorAll('iframe#mainFrame, iframe#mainframe, iframe.name_blog, iframe');
                for (var f = 0; f < frames.length; f++) {
                    try {
                        var doc = frames[f].contentDocument || frames[f].contentWindow.document;
                        found = clickAlreadyReported(doc);
                        if (found) return found;
                    } catch (e) {}
                }
                return '';
                """
            )
            if text and self._is_already_reported_alert(text):
                self.log(f"이미 신고 레이어 확인: {text[:80]}")
                return text
        except WebDriverException as e:
            if "alert" in str(e).lower():
                dismissed = self._dismiss_blocking_alert_now()
                if dismissed and self._is_already_reported_alert(dismissed):
                    return dismissed
        except Exception:
            pass
        return None

    def _dismiss_already_reported_on_any_window(self) -> bool:
        """(레거시) 현재 창 alert만 확인 — 창 전환하지 않음."""
        return self._accept_already_reported_on_current()

    def _try_dismiss_already_reported_modal(self) -> str | None:
        """alert가 아닌 HTML 모달에서 '이미 신고' 확인."""
        try:
            text = self.driver.execute_script(
                """
                function tryDoc(doc) {
                    if (!doc || !doc.body) return '';
                    var nodes = doc.querySelectorAll(
                        '.layer_popup, .popup, .ly_pop, [role="dialog"], .modal, div[class*="popup"], div[class*="layer"]'
                    );
                    for (var i = 0; i < nodes.length; i++) {
                        var el = nodes[i];
                        var style = doc.defaultView.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        var t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!t || t.length > 300) continue;
                        if (t.indexOf('이미 신고') < 0 && t.indexOf('이미신고') < 0) continue;
                        var btns = el.querySelectorAll('button, a, input[type="button"]');
                        for (var j = 0; j < btns.length; j++) {
                            var btn = btns[j];
                            var bt = (btn.innerText || btn.value || btn.textContent || '').trim();
                            if (bt === '확인' || bt.indexOf('확인') >= 0) {
                                btn.click();
                                return t.slice(0, 200);
                            }
                        }
                    }
                    return '';
                }
                var found = tryDoc(document);
                if (found) return found;
                var frames = document.querySelectorAll('iframe#mainFrame, iframe#mainframe, iframe.name_blog, iframe');
                for (var f = 0; f < frames.length; f++) {
                    try {
                        var doc = frames[f].contentDocument || frames[f].contentWindow.document;
                        found = tryDoc(doc);
                        if (found) return found;
                    } catch (e) {}
                }
                return '';
                """
            )
            if text and self._is_already_reported_alert(text):
                self.log(f"이미 신고 모달 확인: {text[:80]}")
                return text
        except Exception:
            pass
        return None

    def _poll_once_already_reported(self) -> str | None:
        """현재 창 팝업 1회 확인 → ok / already / None."""
        msg = self._read_popup_message(timeout=1.2, dismiss=True)
        if msg:
            self._last_popup_message = msg
            status = self._classify_popup_message(msg)
            if status == "already":
                self.log(f"이미 신고된 게시물 — 확인: {msg[:80]}")
                return "already"
            if status == "ok":
                self.log(f"신고 접수 완료 — 확인: {msg[:80]}")
                return "ok"
        layer = self._try_dismiss_naver_blog_alert_layer()
        if layer:
            self._last_popup_message = layer
            self.log("이미 신고된 게시물 — 확인 후 다음 진행")
            return "already"
        modal = self._try_dismiss_already_reported_modal()
        if modal:
            self._last_popup_message = modal
            self.log("이미 신고된 게시물 — 확인 후 다음 진행")
            return "already"
        return None

    def _dismiss_alert_any_window(self, timeout: float = 5.0) -> str | None:
        """현재 창 alert 확인 (창 전환 없음)."""
        return self._accept_alert_on_current(timeout=timeout)

    def _handle_already_reported_if_any(self, timeout: float = 6.0) -> str | None:
        """팝업 문자열 읽기 → ok / already / None."""
        return self._handle_report_popup_if_any(timeout=timeout)

    def _accept_alert(self, timeout: float = 3) -> str | None:
        end = time.time() + timeout
        while time.time() < end:
            text = self._try_accept_alert_now()
            if text:
                return text
            time.sleep(0.1)
        return None

    def _is_wrong_captcha_alert(self, text: str) -> bool:
        if not text:
            return False
        return any(k in text for k in ("정답을 정확", "다시 입력", "정확하게"))

    def _has_inquiry_captcha(self) -> bool:
        return bool(
            self._find_inquiry_question()
            or self._find_inquiry_captcha_image()
            or self._find_inquiry_answer_input()
        )

    def _wait_submit_success(self, timeout: int = 30) -> bool:
        self.log("신고 접수 완료 확인 대기...")
        end = time.time() + timeout
        while time.time() < end:
            alert_text = self._accept_alert(timeout=0.8)
            if alert_text and self._is_wrong_captcha_alert(alert_text):
                self.log("접수 대기 중 오답 팝업 감지")
                return False

            try:
                body = self.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                body = ""

            success_keywords = (
                "문의가 접수",
                "접수되었",
                "접수 완료",
                "등록되었",
                "문의하기가 완료",
                "정상적으로 접수",
                "문의가 정상",
            )
            if any(k in body for k in success_keywords):
                self.log("신고 접수 완료 확인")
                return True

            time.sleep(0.5)

        self.log("신고 접수 완료 확인 실패")
        return False

    def _clear_input(self, element):
        try:
            element.click()
            element.clear()
        except Exception:
            self.driver.execute_script("""
                var el = arguments[0];
                el.focus();
                el.value = '';
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            """, element)

    def _click_element(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        self._human_delay(0.2, 0.5)
        try:
            element.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", element)

    INQUIRY_CATEGORY_LABELS: dict[str, str] = {
        "illegal": "불법성",
        "spam": "스팸성",
    }

    def _select_inquiry_category(self, wait, category: str = "illegal") -> bool:
        label = self.INQUIRY_CATEGORY_LABELS.get(category, "불법성")
        try:
            select_btn = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "button.InquiryInput_select_btn__d28Te")
            ))
            self._click_element(select_btn)
            self.log("유형 선택 버튼 클릭")
            self._human_delay(0.6, 1.2)
            option = wait.until(EC.presence_of_element_located(
                (By.XPATH, f"//button[@role='option' and contains(text(),'{label}')]")
            ))
            self._click_element(option)
            self.log(f"'{label}' 선택")
            self._human_delay(0.8, 1.5)
            return True
        except Exception as e:
            self.log(f"유형 '{label}' 선택 오류: {e}")
            return False

    def _select_illegal_type(self, wait) -> bool:
        return self._select_inquiry_category(wait, "illegal")

    @staticmethod
    def _rewrite_rules() -> str:
        return (
            "- '신고 대상:', '사이트:', '신고 사항:', '유형:', 'URL:', '---' 같은 구조적 요약은 절대 넣지 마세요.\n"
            "- 한국어 자연스러운 문단 형식으로만 작성하세요.\n"
            "- 네이버 아이디, 계정명, '저는 ... 계정을 사용' 같은 계정 관련 표현은 절대 넣지 마세요.\n"
            "- 다른 신고 문구와 겹치지 않도록 표현/어체/문장 흐름을 다양하게 바꿔주세요."
        )

    def _rewrite(self, template: str, account_id: str, site: str, report_type: str) -> str:
        """GPT로 원본을 리라이트합니다."""
        if not self.client:
            return template
        prompt = (
            "아래 원본 신고 내용을 토대로, 같은 의미와 맥락을 유지하면서 "
            "단어, 문장구조, 어체(해라체/합쇼체/해요체), 표현 방식을 바꿔서 "
            "새로운 신고 내용을 250~400자 내외로 작성해주세요.\n\n"
            f"[원본 신고 내용]\n{template}\n\n"
            "[규칙]\n"
            + self._rewrite_rules()
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "당신은 불법 금융 사이트 신고 내용을 자연스럽고 다양하게 변형하는 전문 보조원입니다."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
                max_tokens=700,
            )
            return self._clean_output(response.choices[0].message.content.strip())
        except Exception as e:
            self.log(f"GPT 리라이트 오류: {self._format_openai_error(e)}")
            return template

    @staticmethod
    def _clean_output(text: str) -> str:
        lines = text.splitlines()
        cleaned = []
        skip_prefixes = ("신고 대상", "사이트", "신고 사항", "유형", "URL", "주소", "---")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("---") and "계정" in stripped:
                continue
            if any(stripped.startswith(p) for p in skip_prefixes):
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def start_driver(self):
        self.log("브라우저 준비 중...")
        self.driver, info = create_webdriver(self.browser_mode, headless=self.headless)
        version = info.get("version") or ""
        label = info.get("label") or "브라우저"
        if version:
            self.log(f"{label} 사용: {version}")
        else:
            self.log(f"{label} 사용")
        ua = info.get("user_agent") or ""
        if ua:
            self.log(f"브라우저 시작 완료 ({ua})")
        else:
            self.log("브라우저 시작 완료")

    def quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.log("브라우저 종료")

    def _wait(self, seconds: int = 10):
        return WebDriverWait(self.driver, seconds)

    def _vision_model(self) -> str:
        """CAPTCHA 인식용 Vision 지원 모델."""
        vision_models = {"gpt-4o", "gpt-4-turbo", "gpt-4-turbo-2024-04-09"}
        if self.model in vision_models:
            return self.model
        return "gpt-4o"

    def _build_login_url(self, target: str) -> str:
        return (
            "https://nid.naver.com/nidlogin.login"
            f"?mode=form&locale=ko&url={quote(target, safe='')}"
        )

    def _has_naver_session_cookie(self) -> bool:
        try:
            for cookie in self.driver.get_cookies():
                if cookie.get("name") in ("NID_AUT", "NID_SES", "NID_JKL"):
                    return True
        except Exception:
            pass
        return False

    def _ensure_password_encrypted(self, max_wait: float = 6.0) -> bool:
        """login.js v4: pw 입력 후 eccpw 필드가 채워져야 폼 제출이 유효합니다."""
        end = time.time() + max_wait
        last_state: dict = {}
        while time.time() < end:
            last_state = self.driver.execute_script(
                "var ecc=document.getElementById('eccpw');"
                "var dyn=document.getElementById('dynamicKey');"
                "var pw=document.getElementById('pw');"
                "return {"
                "  eccpw: !!(ecc && ecc.value),"
                "  dynamicKey: !!(dyn && dyn.value),"
                "  pwLen: pw && pw.value ? pw.value.length : 0"
                "};"
            ) or {}
            if last_state.get("eccpw"):
                return True
            try:
                pw_input = self._find_login_pw_input()
                self.driver.execute_script(
                    "var el=arguments[0];"
                    "el.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,key:'a'}));"
                    "el.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'a'}));"
                    "el.dispatchEvent(new Event('input',{bubbles:true}));"
                    "el.dispatchEvent(new Event('change',{bubbles:true}));"
                    "el.blur();",
                    pw_input,
                )
            except Exception:
                pass
            time.sleep(0.35)
        ecc_ready = self.driver.execute_script(
            "var ecc=document.getElementById('eccpw');"
            "return !!(ecc && ecc.value);"
        )
        if ecc_ready:
            return True
        self.log(
            "비밀번호 암호화(eccpw) 미완료"
            f" (dynamicKey={last_state.get('dynamicKey')})"
        )
        return False

    def _is_on_login_page(self) -> bool:
        url = self.driver.current_url
        return any(
            token in url
            for token in ("nidlogin.login", "nidlogin.passkey", "nidlogin.rcaptcha", "nidlogin.captcha")
        )

    def _is_receipt_captcha_question(self, text: str) -> bool:
        if not text or self._is_char_captcha_instruction(text):
            return False
        return any(
            k in text
            for k in (
                "입니까", "얼마", "무엇", "몇", "합계", "가격", "개수", "빈 칸",
                "전화번호", "영수증", "가게", "제품", "번째 숫자", "번째숫자",
            )
        )

    def _find_receipt_captcha_question(self) -> str:
        """영수증/질문형 보안 화면의 질문 문구."""
        xpaths = [
            "//*[contains(text(),'무엇입니까')]",
            "//*[contains(text(),'입니까')]",
            "//*[contains(text(),'얼마')]",
            "//*[contains(text(),'빈 칸')]",
            "//*[contains(text(),'전화번호')]",
            "//*[contains(text(),'번째 숫자')]",
            "//*[contains(@class,'captcha')]//*[contains(text(),'입니까')]",
        ]
        for xpath in xpaths:
            try:
                for el in self.driver.find_elements(By.XPATH, xpath):
                    if not el.is_displayed():
                        continue
                    text = (el.text or "").strip()
                    if 8 < len(text) < 180 and self._is_receipt_captcha_question(text):
                        return text
            except Exception:
                continue
        return ""

    def _find_receipt_captcha_image(self):
        """영수증형 캡챠 이미지 (큰 영수증 이미지)."""
        best = None
        best_area = 0
        for img in self.driver.find_elements(By.CSS_SELECTOR, "div.captcha img, .captcha_box img, .captcha_inner img"):
            try:
                if not img.is_displayed():
                    continue
                w = img.size.get("width", 0) or 0
                h = img.size.get("height", 0) or 0
                area = w * h
                if area > best_area and w >= 100 and h >= 60:
                    best = img
                    best_area = area
            except Exception:
                continue
        return best

    def _find_char_captcha_image(self):
        """문자 왜곡 캡챠 이미지 (좁은 문자열 이미지)."""
        try:
            img = self.driver.find_element(By.ID, "captchaimg")
            if img.is_displayed():
                return img
        except NoSuchElementException:
            pass
        for img in self.driver.find_elements(By.CSS_SELECTOR, "img.captcha_img"):
            try:
                if not img.is_displayed():
                    continue
                w = img.size.get("width", 0) or 0
                h = img.size.get("height", 0) or 0
                if w <= 220 and h <= 80:
                    return img
            except Exception:
                continue
        return None

    def _is_char_captcha_instruction(self, text: str) -> bool:
        compact = (text or "").replace(" ", "").lower()
        return any(
            k in compact
            for k in (
                "자동입력방지",
                "자동입력",
                "문자를입력",
                "캡차",
                "captcha",
            )
        )

    def _is_still_on_captcha_challenge(self) -> bool:
        url = self.driver.current_url
        if any(token in url for token in ("rcaptcha", "nidlogin.captcha")):
            return True
        if self._has_receipt_captcha() or self._has_char_captcha():
            return True
        err = self._read_login_page_errors()
        if any(k in err for k in ("정답", "자동 입력", "일치하지", "다시 입력", "틀렸")):
            return True
        return False

    def _is_active_captcha_challenge(self) -> bool:
        """로그인 제출 대신 캡챠 확인이 필요한 화면인지 판별."""
        if self._has_receipt_captcha():
            return True
        if self._has_char_captcha():
            return True
        return False

    def _has_login_form(self) -> bool:
        if not self._is_on_login_page():
            return False
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, "#id, input[name='id']"):
                if el.is_displayed() and el.is_enabled():
                    return True
            for el in self.driver.find_elements(By.CSS_SELECTOR, "#pw, input[name='pw']"):
                if el.is_displayed() and el.is_enabled():
                    return True
            for el in self.driver.find_elements(
                By.CSS_SELECTOR, "#loginBtn_row, #loginBtn_column"
            ):
                if el.is_displayed():
                    return True
        except Exception:
            pass
        return self._is_on_login_page()

    def _has_naver_logged_in_ui(self) -> bool:
        checks = [
            (By.CSS_SELECTOR, "#account"),
            (By.CSS_SELECTOR, ".MyView-module__btn_logout___bsTOJ"),
            (By.CSS_SELECTOR, ".MyView-module__my_info___GNmHz"),
            (By.CSS_SELECTOR, "#gnb_logout_button"),
            (By.XPATH, "//button[contains(.,'로그아웃')]"),
            (By.XPATH, "//*[contains(@class,'btn_logout')]"),
        ]
        for by, sel in checks:
            try:
                for el in self.driver.find_elements(by, sel):
                    if el.is_displayed():
                        return True
            except Exception:
                continue
        return False

    def _is_logged_in(self) -> bool:
        if self._is_on_login_page():
            return False
        if self._is_on_inquiry_form():
            return self._has_naver_session_cookie()
        url = self.driver.current_url
        if "inquiry/input.help" in url or "help.naver.com/inquiry" in url:
            return self._has_naver_session_cookie()
        if "cafe.naver.com" in url:
            return self._has_naver_session_cookie()
        if "blog.naver.com" in url:
            return self._has_naver_session_cookie() and not self._is_on_login_page()
        if "www.naver.com" in url:
            return self._has_naver_logged_in_ui() or self._has_naver_session_cookie()
        if "help.naver.com" in url and "nid.naver.com" not in url:
            return self._has_naver_session_cookie()
        if "nid.naver.com" in url:
            return False
        return self._has_naver_session_cookie()

    def _wait_for_login_redirect(self, timeout: int = 25) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._should_stop() or not self.driver:
                return False
            if self._is_account_protected():
                return False
            if self._is_logged_in():
                return True
            if self._interruptible_sleep(0.5):
                return False
        return self._is_logged_in()

    def _is_blog_target(self, url: str) -> bool:
        return "blog.naver.com" in (url or "")

    def _finalize_blog_login(self, target: str) -> bool:
        norm = self._normalize_blog_url(target)
        if not self._has_naver_session_cookie():
            self.log("블로그 로그인 — 세션 쿠키 없음")
            return False

        current = self.driver.current_url
        if self._is_on_login_page() or self._has_login_form():
            self.log("블로그 로그인 — 로그인 페이지에 머무름")
            return False

        target_log = self._blog_log_no(norm)
        current_log = self._blog_log_no(current)
        if target_log and current_log == target_log and "blog.naver.com" in current:
            self.log("블로그 게시물 페이지 로그인 확인")
            self._human_delay(1.5, 2.5)
            self._wait_blog_post_ui(target_log, timeout=15)
            return True

        self.driver.get(norm)
        self.log(f"블로그 게시물 이동: {self._truncate_url(norm)}")
        self._human_delay(2.5, 4.0)
        self.driver.switch_to.default_content()

        if self._is_on_login_page() or self._has_login_form():
            self.log("블로그 접근 시 로그인 페이지로 이동됨")
            return False
        if not self._has_naver_session_cookie():
            self.log("블로그 접근 후 세션 없음")
            return False

        self._wait_blog_post_ui(target_log, timeout=15)
        self.log("블로그 로그인 완료")
        return True

    def _finalize_login(self, target: str) -> bool:
        if self._is_blog_target(target):
            return self._finalize_blog_login(target)

        current = self.driver.current_url
        self.log(f"로그인 완료 확인 → {current[:100]}")
        if self._is_on_inquiry_form() and self._has_naver_session_cookie():
            return True
        if "www.naver.com" not in current:
            self.driver.get("https://www.naver.com")
            self.log("네이버 메인에서 로그인 UI 확인")
            self._human_delay(1.5, 2.5)
        if not self._has_naver_logged_in_ui():
            if not self._has_naver_session_cookie():
                self.log("로그인 세션 쿠키 없음 — 로그인 미완료")
                return False
            self.log("로그인 UI 미표시 — 세션 쿠키만 확인됨")
        self.driver.get(target)
        self.log("신고 작성 페이지로 이동 (세션 확인)")
        self._human_delay(2.0, 3.5)
        if self._is_on_login_page() or self._has_login_form():
            self.log("신고 페이지 접근 시 로그인 세션 없음 — 로그인 페이지로 이동됨")
            return False
        try:
            self._wait(20).until(lambda d: self._is_on_inquiry_form())
            return True
        except TimeoutException:
            if self._is_on_login_page():
                self.log("신고 폼 대기 중 로그인 페이지로 돌아감")
                return False
            self.log("신고 작성 폼(requiredUrl1) 로드 실패")
            return False

    def _find_login_id_input(self):
        wait = self._wait(15)
        for by, sel in [
            (By.ID, "id"),
            (By.CSS_SELECTOR, "input[name='id'][type='text']"),
            (By.CSS_SELECTOR, "input.input_text[type='text']"),
        ]:
            try:
                el = wait.until(EC.element_to_be_clickable((by, sel)))
                if el.is_displayed():
                    return el
            except TimeoutException:
                continue
        raise TimeoutException("로그인 아이디 입력란을 찾지 못했습니다")

    def _find_login_pw_input(self):
        for by, sel in [
            (By.ID, "pw"),
            (By.CSS_SELECTOR, "input[name='pw'][type='password']"),
            (By.CSS_SELECTOR, "input.input_text[type='password']"),
        ]:
            try:
                el = self.driver.find_element(by, sel)
                if el.is_displayed() and el.is_enabled():
                    return el
            except NoSuchElementException:
                continue
        raise NoSuchElementException("로그인 비밀번호 입력란을 찾지 못했습니다")

    def _extract_login_restriction(self) -> dict | None:
        """로그인 제한 화면에서 제한일자·제한사유 추출."""
        try:
            info = self.driver.execute_script(
                """
                function cellAfter(header) {
                    var ths = document.querySelectorAll('th');
                    for (var i = 0; i < ths.length; i++) {
                        var t = (ths[i].innerText || ths[i].textContent || '').replace(/\\s+/g, '').trim();
                        if (t.indexOf(header) >= 0) {
                            var row = ths[i].closest('tr');
                            if (row) {
                                var td = row.querySelector('td');
                                if (td) {
                                    return (td.innerText || td.textContent || '').replace(/\\s+/g, ' ').trim();
                                }
                            }
                        }
                    }
                    return '';
                }
                var body = document.body ? (document.body.innerText || '') : '';
                if (body.indexOf('제한사유') < 0 && body.indexOf('로그인 제한') < 0
                    && body.indexOf('로그인제한') < 0 && body.indexOf('제한일자') < 0) {
                    return null;
                }
                var reason = cellAfter('제한사유');
                var date = cellAfter('제한일자');
                if (!reason && !date) return null;
                return {reason: reason || '', date: date || ''};
                """
            )
            if info and (info.get("reason") or info.get("date")):
                return info
        except Exception:
            pass
        try:
            reason = ""
            date = ""
            for row in self.driver.find_elements(By.CSS_SELECTOR, "tr"):
                try:
                    row_text = (row.text or "").replace("\n", " ").strip()
                    if "제한사유" in row_text:
                        tds = row.find_elements(By.TAG_NAME, "td")
                        if tds:
                            reason = (tds[0].text or "").strip()
                    if "제한일자" in row_text:
                        tds = row.find_elements(By.TAG_NAME, "td")
                        if tds:
                            date = (tds[0].text or "").strip()
                except Exception:
                    continue
            if reason or date:
                return {"reason": reason, "date": date}
        except Exception:
            pass
        return None

    def _login_restriction_detail(self) -> str:
        parts: list[str] = []
        if self._last_login_restriction_date:
            parts.append(f"제한일자: {self._last_login_restriction_date}")
        if self._last_login_restriction_reason:
            parts.append(f"제한사유: {self._last_login_restriction_reason}")
        return ", ".join(parts)

    def _check_login_blocked(self) -> str | None:
        """로그인 제한/보호조치 감지. 차단 시 'protected' 반환 및 로그."""
        info = self._extract_login_restriction()
        if info:
            self._last_login_restriction_reason = (info.get("reason") or "").strip()
            self._last_login_restriction_date = (info.get("date") or "").strip()
            detail = self._login_restriction_detail()
            self.log(f"로그인 제한 — {detail}" if detail else "로그인 제한 화면 감지")
            return "protected"
        if self._is_account_protection_page():
            self.log("계정 보호조치 화면 감지")
            return "protected"
        return None

    def _is_account_protection_page(self) -> bool:
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            if "회원님의 아이디를 보호하고 있습니다" in body:
                return True
            if "보호조치 해제" in body:
                return True
        except Exception:
            pass
        try:
            return bool(self.driver.find_elements(
                By.XPATH, "//*[contains(text(),'보호조치 해제') or contains(text(),'아이디를 보호')]"
            ))
        except Exception:
            pass
        return False

    def _is_account_protected(self) -> bool:
        return bool(self._extract_login_restriction()) or self._is_account_protection_page()

    def _element_to_b64(self, img_el) -> str:
        src = img_el.get_attribute("src")
        if src and src.startswith("data:image"):
            return src.split(",")[1]
        return self.driver.execute_script("""
            var img = arguments[0];
            var c = document.createElement('canvas');
            c.width = img.naturalWidth || img.width;
            c.height = img.naturalHeight || img.height;
            c.getContext('2d').drawImage(img, 0, 0);
            return c.toDataURL('image/png').split(',')[1];
        """, img_el)

    def _format_openai_error(self, exc: Exception) -> str:
        msg = str(exc)
        lower = msg.lower()
        if "insufficient_quota" in lower or "exceeded your current quota" in lower:
            return (
                "OpenAI API 사용 한도/잔액이 부족합니다. "
                "platform.openai.com → Billing에서 결제·크레딧을 확인하세요."
            )
        if "429" in msg or "rate_limit" in lower:
            return "OpenAI API 요청 한도 초과(429). 잠시 후 다시 시도하거나 요금제를 확인하세요."
        if "invalid_api_key" in lower or "incorrect api key" in lower:
            return "OpenAI API Key가 올바르지 않습니다. Settings에서 키를 확인하세요."
        return msg

    def _captcha_element_to_b64(self, img_el) -> str:
        """캡챠 이미지를 고해상도로 캡처해 Vision 인식률을 높입니다."""
        try:
            raw = img_el.screenshot_as_base64
            if raw:
                return raw
        except Exception:
            pass
        try:
            return self.driver.execute_script(
                "var img=arguments[0];"
                "var scale=3;"
                "var c=document.createElement('canvas');"
                "var w=img.naturalWidth||img.width||120;"
                "var h=img.naturalHeight||img.height||40;"
                "c.width=w*scale;c.height=h*scale;"
                "var ctx=c.getContext('2d');"
                "ctx.imageSmoothingEnabled=false;"
                "ctx.drawImage(img,0,0,c.width,c.height);"
                "return c.toDataURL('image/png').split(',')[1];",
                img_el,
            )
        except Exception:
            return self._element_to_b64(img_el)

    def _normalize_char_captcha_text(self, raw: str) -> str:
        text = re.sub(r"[^A-Za-z0-9]", "", (raw or "").strip())
        if not text:
            return ""
        if len(text) > 8:
            self.log(f"CAPTCHA 인식값 비정상(길이 {len(text)}) — 무시")
            return ""
        if len(text) < 4:
            return ""
        return text

    def _recognize_char_captcha(self, img_el) -> str:
        b64 = self._captcha_element_to_b64(img_el)
        prompts = [
            (
                "네이버 로그인 자동입력방지 캡챠입니다. 이미지에 보이는 왜곡된 문자는 "
                "보통 6개입니다. 왼쪽부터 순서대로 영문 대소문자/숫자만 출력하세요. "
                "공백·설명·다른 글자 없이 문자만."
            ),
            (
                "CAPTCHA image with about 6 distorted letters/numbers. "
                "Read each character left to right. Output ONLY the characters, nothing else."
            ),
        ]
        for idx, prompt in enumerate(prompts, start=1):
            raw = self._vision_answer(prompt, b64, detail="high")
            text = self._normalize_char_captcha_text(raw.split("\n")[0])
            if text:
                if idx > 1:
                    self.log(f"CAPTCHA 재인식 성공 (프롬프트 {idx})")
                return text
        return ""

    def _click_captcha_refresh(self) -> bool:
        """캡챠 새로고침 버튼 클릭 (확인/로그인 버튼 제외)."""
        selectors = [
            (By.ID, "captcha_reload"),
            (By.ID, "btnCaptchaReload"),
            (By.CSS_SELECTOR, "button.btn_reload"),
            (By.CSS_SELECTOR, "button[class*='refresh']"),
            (By.CSS_SELECTOR, "button[class*='reload']"),
            (By.XPATH, "//button[contains(@class,'refresh') or contains(@class,'reload')]"),
        ]
        for by, sel in selectors:
            try:
                for el in self.driver.find_elements(by, sel):
                    if not el.is_displayed() or not el.is_enabled():
                        continue
                    el_id = (el.get_attribute("id") or "").lower()
                    if el_id in ("log.login", "loginbtn_row", "loginbtn_column"):
                        continue
                    classes = (el.get_attribute("class") or "").lower()
                    if "btn_done" in classes:
                        continue
                    el.click()
                    self.log("CAPTCHA 이미지 새로고침")
                    self._human_delay(0.8, 1.2)
                    return True
            except Exception:
                continue
        try:
            clicked = self.driver.execute_script(
                "var btns=document.querySelectorAll('button');"
                "for(var i=0;i<btns.length;i++){"
                "  var b=btns[i];"
                "  var cls=(b.className||'').toLowerCase();"
                "  var id=(b.id||'').toLowerCase();"
                "  if(id==='log.login'||id.indexOf('loginbtn')>=0) continue;"
                "  if(cls.indexOf('btn_done')>=0) continue;"
                "  if((cls.indexOf('refresh')>=0||cls.indexOf('reload')>=0)"
                "     &&b.offsetParent!==null){b.click();return true;}"
                "}"
                "return false;"
            )
            if clicked:
                self.log("CAPTCHA 이미지 새로고침 (JS)")
                self._human_delay(0.8, 1.2)
                return True
        except Exception:
            pass
        return False

    def _clear_char_captcha_input(self):
        try:
            inp = self._find_char_captcha_input()
            if not inp:
                return
            inp.click()
            inp.clear()
            self.driver.execute_script("arguments[0].value='';", inp)
        except Exception:
            pass

    def _vision_answer(self, prompt: str, b64: str | None = None, detail: str = "auto") -> str:
        if not self.client:
            return ""
        content = [{"type": "text", "text": prompt}]
        if b64:
            image_url: dict = {"url": f"data:image/png;base64,{b64}"}
            if detail in ("low", "high", "auto"):
                image_url["detail"] = detail
            content.append({"type": "image_url", "image_url": image_url})
        try:
            response = self.client.chat.completions.create(
                model=self._vision_model(),
                messages=[{"role": "user", "content": content}],
                max_tokens=100,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            self.log(f"OpenAI Vision 오류: {self._format_openai_error(e)}")
            raise

    def _reenter_password(self, naver_pw: str):
        try:
            pw_input = self._find_login_pw_input()
            if not pw_input.is_displayed():
                return
            pw_input.click()
            pw_input.clear()
            self.driver.execute_script("arguments[0].value = '';", pw_input)
            for char in naver_pw:
                pw_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.1))
            self.log("비밀번호 재입력 완료")
        except (NoSuchElementException, TimeoutException):
            pass

    def _read_element_value(self, element) -> str:
        try:
            val = element.get_attribute("value")
            if val:
                return val.strip()
        except Exception:
            pass
        try:
            return (self.driver.execute_script("return arguments[0].value || '';", element) or "").strip()
        except Exception:
            return ""

    def _dispatch_input_events(self, element, text: str):
        """React/네이티브 폼 검증이 value 변경을 인식하도록 이벤트 전파."""
        self.driver.execute_script("""
            var el = arguments[0];
            var val = arguments[1];
            el.focus();
            try { el.click(); } catch (e) {}
            var proto = el instanceof HTMLTextAreaElement
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            var desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) {
                desc.set.call(el, val);
            } else {
                el.value = val;
            }
            try {
                el.dispatchEvent(new InputEvent('beforeinput', {
                    bubbles: true, cancelable: true, inputType: 'insertFromPaste', data: val
                }));
            } catch (e) {}
            el.dispatchEvent(new Event('input', {bubbles: true}));
            try {
                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true, inputType: 'insertFromPaste', data: val
                }));
            } catch (e) {}
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'Enter'}));
            el.dispatchEvent(new Event('blur', {bubbles: true}));
        """, element, text)

    def _paste_into_element(self, element, text: str, label: str = "입력"):
        """URL 등 긴 문자열 붙여넣기 — 폼 검증이 인식하는지 확인 후 재시도."""
        expected = text.strip()
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        self._human_delay(0.2, 0.4)
        try:
            element.click()
        except Exception:
            pass

        self._dispatch_input_events(element, expected)
        actual = self._read_element_value(element)

        if actual != expected:
            self.log(f"{label} JS 입력 미인식 → send_keys 재시도")
            try:
                element.click()
                element.clear()
                self._human_delay(0.1, 0.2)
                element.send_keys(expected)
            except ElementNotInteractableException:
                self._dispatch_input_events(element, expected)
            actual = self._read_element_value(element)

        if actual != expected:
            self.driver.execute_script("""
                var el = arguments[0]; var val = arguments[1];
                el.focus();
                try { el.select(); } catch (e) {}
                document.execCommand('insertText', false, val);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true}));
            """, element, expected)
            actual = self._read_element_value(element)

        if actual == expected:
            self.log(f"{label} 입력 확인 ({len(expected)}자)")
        else:
            self.log(f"{label} 입력 경고: 기대 {len(expected)}자, 실제 {len(actual)}자")

    def _ensure_url_fields(self, site: str, search_url: str = ""):
        """requiredUrl 필드가 실제로 채워졌는지 검증 후 재입력."""
        effective_search = (search_url or site).strip()
        fields: list[tuple[str, str, str]] = [("requiredUrl1", site, "게시물 URL")]
        try:
            url2 = self.driver.find_element(By.ID, "requiredUrl2")
            if url2.is_displayed():
                fields.append(("requiredUrl2", effective_search, "검색결과 URL"))
        except NoSuchElementException:
            pass
        for field_id, value, label in fields:
            el = self.driver.find_element(By.ID, field_id)
            if self._read_element_value(el) != value.strip():
                self.log(f"{label} 미입력 감지 → 재입력")
                self._paste_into_element(el, value, label=label)
                self._human_delay(0.3, 0.6)

    def _type_into_element(self, element, text: str, label: str = "입력"):
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.15)
        try:
            element.click()
            element.clear()
            for char in text:
                element.send_keys(char)
                time.sleep(random.uniform(0.03, 0.08))
        except ElementNotInteractableException:
            self.log(f"{label} 직접 입력 실패 → JS 입력 시도")
            self.driver.execute_script("""
                var el = arguments[0];
                var val = arguments[1];
                el.focus();
                el.value = val;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            """, element, text)

    def _find_receipt_answer_input(self):
        """영수증/질문형 보안 화면의 정답 입력란 (비밀번호·숨김 chptcha 제외)."""
        excluded_ids = {"id", "pw", "chptcha"}

        # 1) placeholder/title에 '정답'이 있는 보이는 입력란
        for xpath in [
            "//input[contains(@placeholder,'정답')]",
            "//input[contains(@title,'정답')]",
            "//input[contains(@aria-label,'정답')]",
        ]:
            for el in self.driver.find_elements(By.XPATH, xpath):
                el_id = (el.get_attribute("id") or "").lower()
                if el_id in excluded_ids:
                    continue
                if el.is_displayed() and el.is_enabled():
                    return el

        # 2) captcha 이미지 주변 입력란
        for el in self.driver.find_elements(
            By.XPATH,
            "//img[@id='captchaimg']/ancestor::div[1]//input | "
            "//div[contains(@class,'captcha')]//input[@type='text' or not(@type)]",
        ):
            el_id = (el.get_attribute("id") or "").lower()
            if el_id in excluded_ids:
                continue
            if el.is_displayed() and el.is_enabled():
                return el

        # 3) id/name=captcha (chptcha보다 우선 — 영수증형)
        for by, sel in [
            (By.ID, "captcha"),
            (By.CSS_SELECTOR, "input[name='captcha']"),
            (By.CSS_SELECTOR, "input.captcha_input"),
            (By.CSS_SELECTOR, "input#captchaimg + input"),
        ]:
            try:
                el = self.driver.find_element(by, sel)
                el_id = (el.get_attribute("id") or "").lower()
                if el_id in excluded_ids:
                    continue
                if el.is_displayed() and el.is_enabled():
                    return el
            except NoSuchElementException:
                continue

        # 4) 보이는 text input 중 id/pw/chptcha 제외
        for el in self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
            el_id = (el.get_attribute("id") or "").lower()
            if el_id in excluded_ids:
                continue
            ph = el.get_attribute("placeholder") or ""
            if el.is_displayed() and el.is_enabled() and "비밀번호" not in ph:
                return el
        return None

    def _find_char_captcha_input(self):
        for by, sel in [
            (By.ID, "chptcha"),
            (By.ID, "captcha"),
            (By.CSS_SELECTOR, "input[name='captcha']"),
            (By.CSS_SELECTOR, "input[placeholder*='정답']"),
        ]:
            try:
                el = self.driver.find_element(by, sel)
                if el.is_displayed() and el.is_enabled():
                    return el
            except NoSuchElementException:
                continue
        return None

    def _find_captcha_question(self) -> str:
        receipt_q = self._find_receipt_captcha_question()
        if receipt_q:
            return receipt_q
        try:
            for el in self.driver.find_elements(
                By.XPATH,
                "//*[contains(text(),'입니까') or contains(text(),'얼마') or contains(text(),'몇') or contains(text(),'합계')]",
            ):
                text = el.text.strip()
                if text and len(text) < 150:
                    return text
        except Exception:
            pass

        selectors = [
            "div.captcha_message",
            "div#captcha_info",
            "p.captcha_message",
            "span.captcha_message",
            "div.captcha_box",
            "div#captcha_inner",
        ]
        for sel in selectors:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                text = el.text.strip()
                if text and len(text) > 3:
                    return text
            except NoSuchElementException:
                continue
        try:
            for el in self.driver.find_elements(By.XPATH, "//p | //strong | //span | //label | //div"):
                text = el.text.strip()
                if not text or len(text) > 200:
                    continue
                if self._is_char_captcha_instruction(text):
                    return text
                if any(k in text for k in ("입니까", "얼마", "몇", "무엇", "어떤", "합계", "가격", "개수", "빈 칸")):
                    return text
        except Exception:
            pass
        return ""

    def _find_captcha_image(self):
        receipt_img = self._find_receipt_captcha_image()
        if receipt_img:
            return receipt_img
        return self._find_char_captcha_image()

    def _wait_login_page_ready(self):
        wait = self._wait(20)
        wait.until(EC.presence_of_element_located((By.ID, "frmNIDLogin")))
        wait.until(EC.presence_of_element_located((By.ID, "loginBtn_row")))
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        try:
            wait.until(
                lambda d: bool(
                    d.execute_script(
                        "var k=document.getElementById('dynamicKey');"
                        "return !!(k && k.value);"
                    )
                )
            )
        except TimeoutException:
            self.log("로그인 dynamicKey 대기 타임아웃 (계속 진행)")
        self._human_delay(0.8, 1.2)

    def _type_login_credentials(self, id_input, pw_input, naver_id: str, naver_pw: str):
        """login.js v4는 실제 키 입력 후 eccpw 암호화·제출이 필요합니다 (JS value 주입만으로는 실패)."""
        for element, text, label in (
            (id_input, naver_id, "아이디"),
            (pw_input, naver_pw, "비밀번호"),
        ):
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            self._human_delay(0.15, 0.3)
            element.click()
            try:
                element.clear()
            except Exception:
                pass
            if label != "비밀번호":
                self.driver.execute_script("arguments[0].value = '';", element)
            for char in text:
                element.send_keys(char)
                time.sleep(random.uniform(0.05, 0.12))
            if label == "비밀번호":
                self.driver.execute_script(
                    "var el=arguments[0];"
                    "el.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'a'}));"
                    "el.dispatchEvent(new Event('change',{bubbles:true}));",
                    element,
                )
            actual = self._read_element_value(element)
            shown = len(actual) if actual else len(text)
            self.log(f"{label} 입력 ({shown}자)")

    def _read_login_page_errors(self) -> str:
        errors: list[str] = []
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, ".form_message"):
                if not el.is_displayed():
                    continue
                text_el = el
                try:
                    inner = el.find_elements(By.CSS_SELECTOR, ".text")
                    if inner:
                        text_el = inner[0]
                except Exception:
                    pass
                text = (text_el.text or "").strip()
                if text and text not in errors:
                    errors.append(text)
        except Exception:
            pass
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            for phrase in (
                "아이디(로그인 전화번호, 로그인 전용 아이디) 또는 비밀번호",
                "비밀번호가 잘못",
                "존재하지 않는",
                "로그인에 실패",
            ):
                if phrase in body and phrase not in errors:
                    errors.append(phrase)
        except Exception:
            pass
        restriction = self._extract_login_restriction()
        if restriction:
            reason = (restriction.get("reason") or "").strip()
            date = (restriction.get("date") or "").strip()
            parts = []
            if date:
                parts.append(f"제한일자: {date}")
            if reason:
                parts.append(f"제한사유: {reason}")
            if parts:
                msg = ", ".join(parts)
                if msg not in errors:
                    errors.append(msg)
        return " / ".join(errors)

    def _is_security_confirm_candidate(self, el) -> bool:
        if not el.is_displayed() or not el.is_enabled():
            return False
        el_id = (el.get_attribute("id") or "").lower()
        if el_id in ("loginbtn_row", "loginbtn_column"):
            return False
        if el_id == "log.login":
            return True
        classes = (el.get_attribute("class") or "").lower()
        if any(k in classes for k in ("refresh", "voice", "reload", "captcha_refresh", "btn_refresh")):
            return False
        try:
            if el.find_elements(By.CSS_SELECTOR, "span[data-i18n='btnConfirm']"):
                return True
        except Exception:
            pass
        text = (el.text or "").strip().replace("\n", "")
        return text == "확인"

    def _find_security_confirm_button(self):
        """보안 추가 확인 화면의 '확인' 버튼 (#log.login 만)."""
        selectors = [
            (By.ID, "log.login"),
            (By.XPATH, "//button[@id='log.login']"),
            (By.XPATH, "//button[.//span[@data-i18n='btnConfirm']]"),
            (By.XPATH, "//button[.//span[normalize-space()='확인'] and not(@id='loginBtn_row')]"),
        ]
        for by, sel in selectors:
            try:
                for el in self.driver.find_elements(by, sel):
                    if self._is_security_confirm_candidate(el):
                        return el
            except Exception:
                continue
        return None

    def _click_security_confirm(self) -> bool:
        btn = self._find_security_confirm_button()
        if btn:
            try:
                btn_id = btn.get_attribute("id") or "btn_done"
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                self._human_delay(0.2, 0.4)
                btn.click()
                self.log(f"보안 확인 버튼 클릭 ({btn_id})")
                return True
            except Exception:
                try:
                    btn_id = btn.get_attribute("id") or "btn_done"
                    self.driver.execute_script("arguments[0].click();", btn)
                    self.log(f"보안 확인 버튼 클릭 (JS: {btn_id})")
                    return True
                except Exception:
                    pass
        try:
            clicked = self.driver.execute_script(
                "var ids=['log.login'];"
                "for(var i=0;i<ids.length;i++){"
                "  var b=document.getElementById(ids[i]);"
                "  if(b&&b.offsetParent!==null){b.click();return ids[i];}"
                "}"
                "var done=document.querySelector('button.btn_done');"
                "if(done&&done.offsetParent!==null){done.click();return 'btn_done';}"
                "return '';"
            )
            if clicked:
                self.log(f"보안 확인 버튼 클릭 (JS: {clicked})")
                return True
        except Exception:
            pass
        return False

    def _has_visible_captcha_answer_input(self) -> bool:
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, "#captcha, input[name='captcha']"):
                if not el.is_displayed() or not el.is_enabled():
                    continue
                ph = el.get_attribute("placeholder") or ""
                if "정답" in ph:
                    return True
        except Exception:
            pass
        return False

    def _is_post_captcha_login_form(self) -> bool:
        """캡챠 통과 후 돌아온 일반 로그인 폼 — 비밀번호 재입력 후 로그인."""
        url = self.driver.current_url
        if "rcaptcha" in url:
            return False
        if not self._is_on_login_page():
            return False
        if self._find_receipt_captcha_image():
            return False
        if self._find_char_captcha_image():
            return False
        if self._has_visible_captcha_answer_input():
            return False
        try:
            btn = self.driver.find_element(By.ID, "loginBtn_row")
            id_input = self.driver.find_element(By.ID, "id")
            if not (btn.is_displayed() and btn.is_enabled()):
                return False
            return bool(self._read_element_value(id_input))
        except NoSuchElementException:
            return False

    def _click_login_button(self) -> bool:
        for elem_id in ("loginBtn_row", "loginBtn_column"):
            try:
                btn = self.driver.find_element(By.ID, elem_id)
                if btn.is_displayed() and btn.is_enabled():
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    self._human_delay(0.15, 0.3)
                    btn.click()
                    self.log(f"로그인 버튼 클릭 ({elem_id})")
                    return True
            except NoSuchElementException:
                continue
        try:
            clicked = self.driver.execute_script(
                "var ids=['loginBtn_row','loginBtn_column'];"
                "for (var i=0;i<ids.length;i++){"
                "  var b=document.getElementById(ids[i]);"
                "  if(b && b.offsetParent!==null){ b.click(); return ids[i]; }"
                "}"
                "return '';"
            )
            if clicked:
                self.log(f"로그인 버튼 클릭 (JS: {clicked})")
                return True
        except Exception:
            pass
        return False

    def _complete_password_login(self, naver_pw: str) -> bool:
        """보안 확인 후 로그인 폼으로 돌아왔을 때 비밀번호 재입력 → 로그인."""
        if not self._is_post_captcha_login_form():
            return False
        self.log("보안 확인 완료 — 비밀번호 재입력 후 로그인")
        try:
            pw_input = self._find_login_pw_input()
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pw_input)
            self._human_delay(0.15, 0.3)
            pw_input.click()
            try:
                pw_input.clear()
            except Exception:
                pass
            self.driver.execute_script("arguments[0].value = '';", pw_input)
            for char in naver_pw:
                pw_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.12))
            self.log(f"비밀번호 재입력 ({len(naver_pw)}자)")
            self._human_delay(0.5, 1.0)
            if not self._ensure_password_encrypted():
                self.log("비밀번호 암호화 대기 실패 — 로그인 버튼 제출 시도")
            if self._click_login_button():
                self.log("로그인 시도")
                return True
            self.log("로그인 버튼을 찾지 못했습니다")
            return False
        except Exception as e:
            self.log(f"비밀번호 재로그인 오류: {e}")
            return False

    def _submit_login(self):
        if self._is_active_captcha_challenge():
            if self._click_security_confirm():
                return
        if self._click_login_button():
            return
        try:
            pw_input = self._find_login_pw_input()
            pw_input.send_keys(Keys.ENTER)
            self.log("로그인 시도 (Enter)")
            return
        except NoSuchElementException:
            pass
        self.log("로그인 버튼을 찾지 못했습니다")

    def _has_receipt_captcha(self) -> bool:
        if not self._find_receipt_captcha_image():
            return False
        return bool(self._find_receipt_captcha_question())

    def _has_char_captcha(self) -> bool:
        if self._has_receipt_captcha():
            return False
        url = self.driver.current_url
        if "rcaptcha" in url:
            return True
        question = self._find_captcha_question()
        if question and self._is_char_captcha_instruction(question):
            return True
        img = self._find_char_captcha_image()
        return img is not None

    def _classify_receipt_question(self, question: str) -> str:
        """영수증 보안 질문 유형 분류 (키워드 우선순위 중요)."""
        if not question:
            return "generic"
        if re.search(r"(\d+)번째.*숫자", question) or "전화번호" in question:
            return "phone_digit"
        if "빈 칸" in question or "[?]" in question:
            return "blank"
        # 이름/무엇 — '가격이 싼 물건의 이름'처럼 가격 키워드가 있어도 이름 우선
        if any(k in question for k in ("이름", "무엇입니까", "무엇 입니까", "제품명", "품목명")):
            return "name"
        if "무엇" in question and "물건" in question:
            return "name"
        if any(k in question for k in ("종류", "몇 종", "몇종")):
            return "kind_count"
        if any(k in question for k in ("몇 개", "총 몇", "몇개", "개 입니까", "개입니까")):
            return "item_count"
        if any(k in question for k in ("가격", "얼마", "합계", "한 개 당", "한개당", "kcal", "열량", " kg", "kg ")):
            return "price"
        return "generic"

    def _is_refusal_answer(self, answer: str) -> bool:
        compact = (answer or "").replace(" ", "").lower()
        return any(k in compact for k in ("죄송", "제공할수", "sorry", "cannot", "unable", "can't"))

    def _validate_receipt_answer(self, question: str, answer: str, qtype: str) -> bool:
        if not answer or self._is_refusal_answer(answer):
            return False
        if qtype in ("kind_count", "item_count", "price", "phone_digit"):
            if not re.fullmatch(r"\d+", answer):
                return False
            if len(answer) > 8:
                return False
        if qtype == "name":
            if re.fullmatch(r"\d+", answer):
                return False
            if len(answer) > 40:
                return False
        if qtype == "blank":
            if len(answer) > 20 or len(answer) < 1:
                return False
        if qtype == "generic" and len(answer) > 50:
            return False
        return True

    def _normalize_receipt_answer(self, answer: str, qtype: str) -> str:
        line = (answer or "").split("\n")[0].strip()
        if qtype in ("kind_count", "item_count", "price", "phone_digit"):
            return re.sub(r"\D", "", line)
        if qtype in ("name", "blank"):
            return re.sub(r"[^\w가-힣]", "", line)
        if qtype == "generic":
            if re.fullmatch(r"[\d,]+", line.replace(",", "")):
                return re.sub(r"\D", "", line)
            return re.sub(r"[^\w가-힣0-9]", "", line)
        return line

    def _receipt_prompt_for_type(self, question: str, qtype: str) -> str:
        base = "네이버 영수증 보안 질문입니다. 영수증 이미지를 자세히 읽고 질문에 맞는 정답만 출력하세요.\n"
        base += "설명·이유·단위(원/kg/kcal) 없이 정답만. 확실하지 않으면 영수증 표에서 해당 값을 다시 확인하세요.\n"
        base += f"질문: {question}\n\n"
        extras = {
            "phone_digit": (
                "가게 전화번호(☎ 옆)를 찾아 숫자만 나열하세요. "
                "질문의 N번째 숫자 하나만 최종 출력하세요."
            ),
            "blank": "주소·지명 등 [?] 빈 칸에 들어갈 단어 하나만 출력하세요.",
            "name": (
                "질문이 묻는 상품/품목 이름만 출력하세요. 가격 숫자는 출력하지 마세요.\n"
                "- '가장 가격이 싼/적은' → 단가가 가장 낮은 품목명\n"
                "- '가장 가격이 비싼/많은' → 단가가 가장 높은 품목명\n"
                "- '적게 구매한' → 수량이 가장 적은 품목명\n"
                "영수증 품목란에 적힌 이름 그대로."
            ),
            "kind_count": (
                "영수증 표에서 서로 다른 상품(품목) 종류 수를 세세요. "
                "합계·할인 행은 제외. 숫자 하나만 (예: 3)."
            ),
            "item_count": (
                "영수증에서 구매한 모든 상품의 수량(개수) 합계를 세세요. "
                "각 품목 옆 수량을 모두 더한 값. 숫자 하나만."
            ),
            "price": (
                "질문에 해당하는 금액·가격·수치 하나만 숫자로 출력하세요. "
                "'한 개 당'이면 단가, '합계'면 해당 합계 금액."
            ),
            "generic": "질문 형식(숫자/단어)에 맞는 정답만 출력하세요.",
        }
        return base + extras.get(qtype, extras["generic"])

    def _solve_receipt_answer(self, question: str, img_el, retry: bool = True) -> str:
        """영수증 이미지 + 질문으로 정답 추출."""
        if not img_el:
            return ""
        b64 = self._captcha_element_to_b64(img_el)
        qtype = self._classify_receipt_question(question)

        if qtype == "phone_digit":
            phone_raw = self._vision_answer(
                "영수증 이미지에서 가게 전화번호(☎ 표시 옆)를 찾아 숫자만 출력하세요. "
                "기호 없이 숫자만. 예: 0242664",
                b64,
                detail="high",
            )
            digits = re.sub(r"\D", "", phone_raw.split("\n")[0])
            pos_match = re.search(r"(\d+)번째", question or "")
            if pos_match and digits:
                pos = int(pos_match.group(1)) - 1
                if 0 <= pos < len(digits):
                    return digits[pos]

        prompt = self._receipt_prompt_for_type(question or "", qtype)
        raw = self._vision_answer(prompt, b64, detail="high")
        answer = self._normalize_receipt_answer(raw, qtype)

        if qtype == "phone_digit" and question:
            pos_match = re.search(r"(\d+)번째", question)
            digits = re.sub(r"\D", "", answer)
            if pos_match and digits:
                pos = int(pos_match.group(1)) - 1
                if 0 <= pos < len(digits):
                    answer = digits[pos]

        if self._validate_receipt_answer(question or "", answer, qtype):
            return answer

        if retry:
            self.log(f"영수증 답변 검증 실패({qtype}: '{answer[:30]}') — 재인식")
            retry_prompt = (
                f"{prompt}\n\n"
                "이전 답이 형식에 맞지 않았습니다. 영수증 표를 행 단위로 다시 읽고 "
                "질문에 정확히 해당하는 값만 출력하세요."
            )
            raw2 = self._vision_answer(retry_prompt, b64, detail="high")
            answer2 = self._normalize_receipt_answer(raw2, qtype)
            if self._validate_receipt_answer(question or "", answer2, qtype):
                return answer2

        return answer if answer and not self._is_refusal_answer(answer) else ""

    def solve_receipt_captcha(self, naver_pw: str) -> bool:
        """영수증/질문형 보안 화면: 비밀번호 → 정답란 → 확인."""
        if not self.client:
            self.log("OpenAI 클라이언트 없음 - 보안 질문을 해결할 수 없습니다.")
            return False

        try:
            self._clear_char_captcha_input()

            question = self._find_receipt_captcha_question() or self._find_captcha_question()
            img_el = self._find_receipt_captcha_image()
            if not img_el:
                self.log("영수증 이미지 없음")
                return False

            if question:
                self.log(f"영수증 보안 질문: {question}")
            else:
                self.log("보안 질문 텍스트 추출 실패, 이미지만 분석합니다.")

            answer = self._solve_receipt_answer(question, img_el)
            if any(k in answer for k in ("죄송", "제공할수", "sorry", "cannot", "unable")):
                self.log("보안 질문 답변 생성 실패 (거절 응답)")
                self._click_captcha_refresh()
                return False
            if not answer:
                self.log("보안 질문 답변 생성 실패")
                self._click_captcha_refresh()
                return False

            self.log(f"보안 질문 답변: {answer}")

            # 3) 정답 입력란에만 답 입력 (chptcha/pw 제외)
            answer_input = self._find_receipt_answer_input()
            if not answer_input:
                self.log("정답 입력란을 찾을 수 없습니다.")
                return False

            aid = answer_input.get_attribute("id") or ""
            placeholder = answer_input.get_attribute("placeholder") or ""
            self.log(f"정답 입력란: id={aid}, placeholder={placeholder}")
            self._type_into_element(answer_input, answer, label="정답")
            time.sleep(0.3)

            # 4) 보안 확인 버튼 (#log.login)
            if not self._click_security_confirm():
                self.log("보안 확인 버튼(#log.login)을 찾지 못했습니다")
                return False
            self.log("정답 입력 및 확인 시도")
            self._human_delay(1.5, 2.5)
            if self._is_post_captcha_login_form():
                self.log("캡챠 통과 — 로그인 폼으로 이동")
                return True
            if self._is_still_on_captcha_challenge():
                self.log("보안 질문 오답 — 새 질문으로 재시도")
                self._clear_char_captcha_input()
                self._click_captcha_refresh()
                return False
            return True
        except Exception as e:
            self.log(f"보안 질문 처리 오류: {self._format_openai_error(e)}")
            return False

    def solve_char_captcha_login(self, naver_pw: str) -> bool:
        """문자 캡챠(자동입력방지) 화면 처리."""
        if not self.client:
            self.log("OpenAI 클라이언트 없음 - 문자 CAPTCHA를 해결할 수 없습니다.")
            return False

        try:
            self._clear_char_captcha_input()

            img_el = self._find_char_captcha_image()
            if not img_el:
                self.log("문자 CAPTCHA 이미지 없음")
                return False

            self.log("문자 CAPTCHA 인식 중...")
            captcha_text = self._recognize_char_captcha(img_el)
            if not captcha_text:
                self.log("CAPTCHA 인식 실패 — 새 이미지로 재시도")
                self._click_captcha_refresh()
                return False
            self.log(f"CAPTCHA 인식 결과: {captcha_text}")

            answer_input = self._find_char_captcha_input()
            if not answer_input:
                self.log("CAPTCHA 입력란 없음")
                return False

            aid = answer_input.get_attribute("id") or ""
            placeholder = answer_input.get_attribute("placeholder") or ""
            self.log(f"CAPTCHA 입력란: id={aid}, placeholder={placeholder}")
            self._type_into_element(answer_input, captcha_text, label="CAPTCHA")
            time.sleep(0.3)

            if not self._click_security_confirm():
                if not self._click_login_button():
                    self.log("CAPTCHA 확인/로그인 버튼을 찾지 못했습니다")
                    return False
            self.log("CAPTCHA 입력 및 확인 시도")
            self._human_delay(1.5, 2.5)
            if self._is_still_on_captcha_challenge():
                self.log("CAPTCHA 오답 — 새 이미지로 재시도")
                self._clear_char_captcha_input()
                self._click_captcha_refresh()
                return False
            return True
        except (InvalidSessionIdException, WebDriverException) as e:
            if "invalid session" in str(e).lower():
                self.log("브라우저 세션 종료됨 — 로그인 중단")
                raise
            self.log(f"문자 CAPTCHA 처리 오류: {e}")
            return False
        except Exception as e:
            self.log(f"문자 CAPTCHA 처리 오류: {self._format_openai_error(e)}")
            return False

    def solve_captcha(self) -> bool:
        """표시된 문자 CAPTCHA 이미지를 API로 풀고 입력합니다."""
        return self.solve_char_captcha_login("")

    def handle_login_challenges(self, naver_pw: str) -> bool:
        """로그인 중 나타나는 보안 화면(문자/영수증 캡챠)을 처리합니다."""
        if self._has_receipt_captcha():
            self.log("영수증형 보안 질문 감지")
            return self.solve_receipt_captcha(naver_pw)
        if self._has_char_captcha():
            self.log("문자 CAPTCHA 감지")
            return self.solve_char_captcha_login(naver_pw)
        return True

    def login(self, naver_id: str, naver_pw: str, redirect_url: str | None = None) -> tuple[bool, str]:
        if self._should_stop() or not self.driver:
            return False, "stopped"
        target = redirect_url or self.INQUIRY_FORM_URL
        login_url = self._build_login_url(target)
        self._last_login_restriction_reason = ""
        self._last_login_restriction_date = ""
        self.driver.get(login_url)
        self.log(f"네이버 로그인 페이지 접속: {naver_id}")
        self._human_delay(1.0, 2.0)
        if self._should_stop() or not self.driver:
            return False, "stopped"

        try:
            self._wait_login_page_ready()
            id_input = self._find_login_id_input()
            pw_input = self._find_login_pw_input()

            self._type_login_credentials(id_input, pw_input, naver_id, naver_pw)
            self.log("아이디/비밀번호 입력 완료")
            self._human_delay(0.5, 1.0)
            if not self._ensure_password_encrypted():
                self.log("비밀번호 암호화 대기 실패 — 로그인 버튼 제출 시도")

            self._submit_login()
            self.log("로그인 시도")

            for attempt in range(8):
                if self._should_stop() or not self.driver:
                    return False, "stopped"
                blocked = self._check_login_blocked()
                if blocked:
                    return False, blocked

                if self._wait_for_login_redirect(timeout=8):
                    if self._finalize_login(target):
                        return True, "ok"
                    self.log("로그인 리다이렉트 후 세션 확인 실패")
                    return False, "failed"

                err = self._read_login_page_errors()
                if err:
                    self.log(f"로그인 화면 메시지: {err}")

                if self._is_on_login_page():
                    self.log(f"로그인 페이지 대기 중 (URL: {self.driver.current_url[:90]})")
                    if self._is_post_captcha_login_form():
                        if not self._complete_password_login(naver_pw):
                            self.log(f"캡챠 통과 후 로그인 실패 (시도 {attempt + 1}/8)")
                    elif self._has_receipt_captcha() or self._has_char_captcha():
                        if not self.handle_login_challenges(naver_pw):
                            self.log(f"보안 화면 처리 실패 — 재시도 ({attempt + 1}/8)")
                        else:
                            self._human_delay(1.0, 2.0)
                            if self._is_post_captcha_login_form():
                                if not self._complete_password_login(naver_pw):
                                    self.log(f"캡챠 통과 후 로그인 실패 (시도 {attempt + 1}/8)")
                            elif self._is_still_on_captcha_challenge():
                                self.log(f"보안 화면 유지 — 재시도 ({attempt + 1}/8)")
                    else:
                        self.log(f"로그인 폼 대기 중 (시도 {attempt + 1}/8)")
                if self._should_stop() or not self.driver:
                    return False, "stopped"
                self._human_delay(2.0, 3.5)

            if self._should_stop() or not self.driver:
                return False, "stopped"
            blocked = self._check_login_blocked()
            if blocked:
                return False, blocked
            if self._wait_for_login_redirect(timeout=5) and self._finalize_login(target):
                return True, "ok"

            err = self._read_login_page_errors()
            if err:
                self.log(f"로그인 실패: {err}")
            else:
                self.log(f"로그인 타임아웃 (현재 URL: {self.driver.current_url[:100]})")
            return False, "failed"
        except TimeoutException:
            blocked = self._check_login_blocked()
            if blocked:
                return False, blocked
            self.log("로그인 타임아웃")
            return False, "failed"
        except InvalidSessionIdException:
            self.log("브라우저 세션 종료됨")
            return False, "stopped" if self._should_stop() else "failed"
        except WebDriverException as e:
            if "invalid session" in str(e).lower():
                self.log("브라우저 세션 종료됨")
                return False, "stopped" if self._should_stop() else "failed"
            self.log(f"로그인 오류: {e}")
            return False, "failed"
        except Exception as e:
            self.log(f"로그인 오류: {e}")
            return False, "failed"

    def _find_inquiry_question(self) -> str:
        xpaths = [
            "//*[contains(text(),'무엇입니까')]",
            "//*[contains(text(),'입니까')]",
            "//*[contains(text(),'얼마')]",
            "//*[contains(text(),'빈 칸')]",
            "//*[contains(text(),'전화번호')]",
            "//*[contains(text(),'번째 숫자')]",
            "//*[contains(text(),'정답을 입력')]",
        ]
        for xpath in xpaths:
            try:
                for el in self.driver.find_elements(By.XPATH, xpath):
                    if not el.is_displayed():
                        continue
                    text = (el.text or "").strip()
                    if 8 < len(text) < 300 and self._is_receipt_captcha_question(text):
                        return text
            except Exception:
                continue
        return ""

    def _find_inquiry_captcha_image(self):
        best = None
        best_area = 0
        selectors = [
            "div.InquiryInput img",
            "form img[src]",
            ".captcha img",
            "img[alt*='영수증']",
            "div.captcha img",
            ".captcha_box img",
        ]
        for sel in selectors:
            try:
                for img in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if not img.is_displayed():
                        continue
                    w = img.size.get("width", 0) or 0
                    h = img.size.get("height", 0) or 0
                    area = w * h
                    if area > best_area and w >= 80 and h >= 50:
                        best = img
                        best_area = area
            except Exception:
                continue
        return best

    def _find_inquiry_answer_input(self):
        skip_ids = {"requiredurl1", "requiredurl2"}
        for el in self.driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
            el_id = (el.get_attribute("id") or "").lower()
            if el_id in skip_ids or "motext" in el_id:
                continue
            ph = el.get_attribute("placeholder") or ""
            if el.is_displayed() and el.is_enabled() and "정답" in ph:
                return el
        for el in self.driver.find_elements(By.CSS_SELECTOR, "input.InquiryInput_input_text__5duMq"):
            el_id = (el.get_attribute("id") or "").lower()
            if el_id in skip_ids:
                continue
            if el.is_displayed() and el.is_enabled():
                ph = el.get_attribute("placeholder") or ""
                if "정답" in ph or not el.get_attribute("value"):
                    return el
        return None

    def _solve_inquiry_followup(self, clear_first: bool = False) -> bool:
        """사유 선택 후 추가 보안 질문 처리."""
        question = self._find_inquiry_question()
        img_el = self._find_inquiry_captcha_image()
        answer_input = self._find_inquiry_answer_input()

        if not question and not img_el and not answer_input:
            return True

        if not self.client:
            self.log("추가 질문 있음 — OpenAI 클라이언트 없음")
            return False

        if not img_el:
            self.log("문의 폼 영수증 이미지 없음")
            return False

        if question:
            qtype = self._classify_receipt_question(question)
            self.log(f"문의 폼 추가 질문({qtype}): {question}")
        else:
            qtype = "generic"
            self.log("문의 폼 추가 질문 — 질문 텍스트 없음, 이미지만 분석")

        answer = self._solve_receipt_answer(question, img_el)
        if self._is_refusal_answer(answer):
            self.log("추가 질문 답변 생성 실패 (거절 응답)")
            self._click_captcha_refresh()
            return False
        if not answer:
            self.log("추가 질문 답변 생성 실패")
            self._click_captcha_refresh()
            return False

        if not answer_input:
            answer_input = self._find_inquiry_answer_input()
        if not answer_input:
            self.log("문의 폼 정답 입력란을 찾을 수 없습니다.")
            return False

        if clear_first:
            self._clear_input(answer_input)
            self._human_delay(0.3, 0.6)
            answer_input = self._find_inquiry_answer_input() or answer_input

        self.log(f"추가 질문 답변: {answer}")
        self._type_into_element(answer_input, answer, label="문의폼 정답")
        self._human_delay(0.5, 1.2)
        return True

    def _submit_inquiry(self, wait) -> bool:
        """문의하기 제출. 오답 팝업 시 새 질문으로 재시도."""
        max_attempts = 5
        for attempt in range(max_attempts):
            if attempt > 0:
                self._human_delay(1.0, 2.0)
                if not self._solve_inquiry_followup(clear_first=True):
                    self.log(f"재시도 {attempt + 1} — 보안 질문 처리 실패")
                    continue

            self._human_delay(0.5, 1.0)
            try:
                submit_btn = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "button.CommonBtn_common_btn__dVKik.CommonBtn_on__jCMSz")
                ))
            except TimeoutException:
                self.log("문의하기 버튼을 찾을 수 없습니다.")
                return False

            self._click_element(submit_btn)
            self.log(f"문의하기 버튼 클릭 ({attempt + 1}/{max_attempts})")
            self._human_delay(1.0, 2.0)

            alert_text = self._accept_alert(timeout=4)
            if alert_text and self._is_wrong_captcha_alert(alert_text):
                self.log("보안 질문 오답 — 새 질문으로 재시도")
                self._human_delay(1.5, 2.5)
                continue

            if self._wait_submit_success():
                return True

            if self._is_on_inquiry_form() and self._has_inquiry_captcha():
                self.log("접수 미완료 — 보안 질문 재시도")
                continue

            self.log("접수 완료 확인 실패 — 재시도")
            self._human_delay(1.0, 2.0)

        self.log("문의 제출 실패 (최대 재시도 초과)")
        return False

    def fill_form(
        self,
        site: str,
        report_type: str,
        content: str,
        search_url: str = "",
        inquiry_category: str = "illegal",
    ) -> bool:
        """문의 작성 폼을 채웁니다."""
        if self._should_stop():
            return False
        category = inquiry_category if inquiry_category in self.INQUIRY_CATEGORY_LABELS else "illegal"
        category_label = self.INQUIRY_CATEGORY_LABELS[category]
        effective_search = (search_url or site).strip()
        try:
            self._go_to_inquiry_page()
            wait = self._wait(15)
            self._human_delay(0.8, 1.5)

            url_input = wait.until(EC.presence_of_element_located((By.ID, "requiredUrl1")))
            self._paste_into_element(url_input, site, label="게시물 URL")
            self.log(f"게시물 URL 입력: {site}")
            self._human_delay(0.4, 1.0)

            try:
                url2 = self.driver.find_element(By.ID, "requiredUrl2")
                if url2.is_displayed():
                    self._paste_into_element(url2, effective_search, label="검색결과 URL")
                    self.log(f"검색결과 URL 입력: {effective_search}")
                    self._human_delay(0.4, 1.0)
            except NoSuchElementException:
                pass

            self._ensure_url_fields(site, effective_search)

            mo_texts = self.driver.find_elements(By.ID, "moText1CA")
            if len(mo_texts) >= 1:
                self._type_into_element(mo_texts[0], report_type, label="유형 키워드")
                self.log(f"유형(키워드) 입력: {report_type}")
                self._human_delay(0.3, 0.8)
            if len(mo_texts) >= 2:
                self._paste_into_element(mo_texts[1], site, label="사이트 키워드")
                self.log(f"사이트(키워드) 입력: {site}")
                self._human_delay(0.3, 0.8)

            textarea = wait.until(EC.presence_of_element_located((By.ID, "moText2CA")))
            self._paste_into_element(textarea, content, label="상세 내용")
            self.log(f"상세 내용 붙여넣기 ({len(content)}자)")
            self._human_delay(0.3, 0.6)

            try:
                if not self._select_inquiry_category(wait, category):
                    self.log(f"{category_label} 유형 선택 실패")
                    return False
                if not self._solve_inquiry_followup():
                    self.log("추가 질문 처리 실패")
                    return False
            except Exception as e:
                self.log(f"유형 선택 처리 오류: {e}")
                return False

            if not self._submit_inquiry(wait):
                self.log("문의 접수 실패")
                return False
            return True
        except Exception as e:
            self.log(f"폼 작성 오류: {e}")
            return False

    def _emit_protection_results(self, naver_id: str, naver_pw: str, tasks: list):
        detail = self._login_restriction_detail()
        rewritten = detail or "보호조치/로그인 제한 — 해제 필요"
        for task in tasks:
            site = task.get("site", "")
            report_type = task.get("report_type", "")
            search_url = task.get("search_url", "") or site
            if task.get("search_url_auto") and report_type:
                search_url = fetch_naver_search_url_live(report_type, driver=self.driver, log=self.log)
            item = {
                "account_id": naver_id,
                "account_password": naver_pw,
                "site": site,
                "report_type": task.get("report_type", ""),
                "original": task.get("template", ""),
                "rewritten": rewritten,
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "success": False,
                "status": "protected",
                "restriction_reason": self._last_login_restriction_reason,
                "restriction_date": self._last_login_restriction_date,
                "search_url": search_url,
                "search_url_custom": task.get("search_url_custom", False),
                "search_url_auto": task.get("search_url_auto", False),
            }
            if self.result_callback:
                self.result_callback(item)
            if self.progress_callback:
                self.progress_callback(1)

    def report(self, naver_id: str, naver_pw: str, tasks: list) -> list:
        """한 계정으로 모든 task를 처리합니다."""
        results = []
        try:
            self.start_driver()
            ok, reason = self.login(naver_id, naver_pw)
            if not ok:
                if reason == "protected":
                    detail = self._login_restriction_detail()
                    if detail:
                        self.log(f"[{naver_id}] 로그인 제한 — {detail}")
                    else:
                        self.log(f"[{naver_id}] 보호조치 화면 — 결과에 기록")
                    self._emit_protection_results(naver_id, naver_pw, tasks)
                else:
                    err_detail = self._login_restriction_detail() or self._read_login_page_errors()
                    if err_detail:
                        self.log(f"[{naver_id}] 로그인 실패 — {err_detail}")
                    else:
                        self.log(f"[{naver_id}] 로그인 실패로 중단")
                return results

            for idx, task in enumerate(tasks):
                if self._should_stop():
                    self.log("사용자 요청으로 신고 중단")
                    break

                site = task.get("site", "")
                report_type = task.get("report_type", "")
                template = task.get("template", "")
                search_url = task.get("search_url", "") or site
                search_url_custom = task.get("search_url_custom", False)
                search_url_auto = task.get("search_url_auto", False)
                inquiry_category = task.get("inquiry_category", "illegal")
                if search_url_auto and report_type:
                    search_url = fetch_naver_search_url_live(report_type, driver=self.driver, log=self.log)

                self._human_delay(1.0, 2.5)
                rewritten = self._rewrite(template, naver_id, site, report_type)
                self.log(f"[{naver_id}] {idx + 1}/{len(tasks)} 리라이트 완료 ({len(rewritten)}자)")
                self._human_delay(0.8, 1.8)

                success = self.fill_form(
                    site, report_type, rewritten,
                    search_url=search_url,
                    inquiry_category=inquiry_category,
                )
                dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                results.append({
                    "account_id": naver_id,
                    "account_password": naver_pw,
                    "site": site,
                    "report_type": report_type,
                    "original": template,
                    "rewritten": rewritten,
                    "datetime": dt,
                    "success": success,
                    "search_url": search_url,
                    "search_url_custom": search_url_custom,
                    "search_url_auto": search_url_auto,
                })
                if self.result_callback:
                    self.result_callback(results[-1])
                if self.progress_callback:
                    self.progress_callback(1)
                self._human_delay(2.0, 4.5)
        finally:
            self.quit_driver()
        return results

    CAFE_SEARCH_URL = "https://search.naver.com/search.naver?ssc=tab.ur.all&query="
    CAFE_ARTICLE_PATH_RE = re.compile(
        r"/([A-Za-z0-9_-]+)/(\d+)",
        re.IGNORECASE,
    )

    def _normalize_cafe_article_url(self, href: str) -> str | None:
        """통합검색 노출 URL 전체 유지 (?art= 토큰 포함)."""
        if not href or "cafe.naver.com" not in href:
            return None
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            href = "https://cafe.naver.com" + href
        parsed = urlparse(href.split("#")[0])
        if "cafe.naver.com" not in parsed.netloc:
            return None
        if not self.CAFE_ARTICLE_PATH_RE.search(parsed.path or ""):
            return None
        scheme = parsed.scheme or "https"
        return urlunparse((scheme, parsed.netloc, parsed.path, "", parsed.query, ""))

    def _cafe_article_dedup_key(self, url: str) -> str | None:
        """게시물 경로(cafe_id/article_id)로 중복 제거 — 검색 순서는 첫 등장 유지."""
        parsed = urlparse(url.split("#")[0])
        m = self.CAFE_ARTICLE_PATH_RE.search(parsed.path or "")
        if m:
            return f"{m.group(1).lower()}/{m.group(2)}"
        return None

    def _extract_anchor_title(self, anchor) -> str:
        for attr in ("innerText", "textContent"):
            try:
                raw = anchor.get_attribute(attr) or ""
                text = " ".join(raw.split())
                if text:
                    return text
            except Exception:
                pass
        return (anchor.get_attribute("title") or "").strip()

    def collect_cafe_article_targets(self, keyword: str, max_pages: int = 3) -> list[dict]:
        """통합검색에서 카페 게시물 URL·제목 수집 (검색 노출 순서 유지)."""
        encoded = quote(keyword)
        key_to_index: dict[str, int] = {}
        targets: list[dict] = []
        for page in range(max_pages):
            if self._should_stop():
                break
            start = 1 + page * 10
            search_url = f"{self.CAFE_SEARCH_URL}{encoded}&start={start}"
            self.driver.get(search_url)
            self.log(f"통합검색: {keyword} (페이지 {page + 1})")
            self._human_delay(2.0, 3.5)
            anchors = self.driver.find_elements(
                By.CSS_SELECTOR, "a[href*='cafe.naver.com'][href*='art=']",
            )
            if not anchors:
                anchors = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='cafe.naver.com']")
            for anchor in anchors:
                href = anchor.get_attribute("href") or ""
                norm = self._normalize_cafe_article_url(href)
                if not norm:
                    continue
                dedup = self._cafe_article_dedup_key(norm)
                if not dedup:
                    continue
                title = self._extract_anchor_title(anchor)
                if dedup in key_to_index:
                    existing = targets[key_to_index[dedup]]
                    if "art=" in norm and "art=" not in existing["url"]:
                        existing["url"] = norm
                    if title and not existing.get("title"):
                        existing["title"] = title
                    continue
                key_to_index[dedup] = len(targets)
                targets.append({"url": norm, "title": title})
                label = title or "(제목 없음)"
                self.log(f"  수집: {label} | {self._truncate_url(norm)}")
        return targets

    def _truncate_url(self, url: str, max_len: int = 72) -> str:
        if len(url) <= max_len:
            return url
        return url[:max_len] + "..."

    def _click_cafe_report_button(self) -> bool:
        wait = self._wait(12)
        try:
            report_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "a.button_report, a[class*='button_report']")
                )
            )
        except TimeoutException:
            return False
        self._click_element(report_btn)
        self.log("카페 신고 버튼 클릭")
        self._cafe_fast_delay(0.25, 0.5)
        return True

    def _select_cafe_illegal_reason_in_context(self) -> bool:
        try:
            clicked = self.driver.execute_script("""
                var labels = document.querySelectorAll('label');
                for (var i = 0; i < labels.length; i++) {
                    var t = (labels[i].textContent || '').replace(/\\s+/g, '');
                    if (t.indexOf('불법정보') >= 0 && t.indexOf('포함') >= 0) {
                        labels[i].click();
                        return 'label';
                    }
                }
                var radios = document.querySelectorAll('input[type=radio]');
                for (var j = 0; j < radios.length; j++) {
                    var r = radios[j];
                    if (r.id === '3' || r.value === '3') {
                        r.checked = true;
                        r.dispatchEvent(new Event('change', {bubbles: true}));
                        r.click();
                        return 'radio';
                    }
                }
                return '';
            """)
            if clicked:
                self.log("불법정보 포함 선택")
                return True
        except Exception:
            pass

        wait = self._wait(5)
        selectors = [
            (By.CSS_SELECTOR, "label[for='3']"),
            (By.CSS_SELECTOR, "input#3[type='radio']"),
            (By.CSS_SELECTOR, "input[type='radio'][value='3']"),
            (By.XPATH, "//label[contains(.,'불법정보를 포함하고 있습니다')]"),
            (By.XPATH, "//label[contains(.,'불법정보') and contains(.,'포함')]"),
            (By.XPATH, "//li[contains(.,'불법정보')]//label"),
            (By.XPATH, "//*[contains(text(),'불법정보를 포함')]/ancestor::label[1]"),
        ]
        for by, sel in selectors:
            try:
                el = wait.until(EC.element_to_be_clickable((by, sel)))
                if not el.is_displayed():
                    continue
                self._click_element(el)
                self.log("불법정보 포함 선택")
                return True
            except TimeoutException:
                continue
            except Exception:
                continue
        self.log("불법정보 항목 선택 실패")
        return False

    def _submit_cafe_report_in_context(self) -> bool:
        wait = self._wait(5)
        for by, sel in [
            (By.XPATH, "//button[contains(.,'신고하기')]"),
            (By.XPATH, "//a[contains(.,'신고하기')]"),
            (By.XPATH, "//button[contains(.,'신고') and not(contains(.,'취소'))]"),
            (By.CSS_SELECTOR, "button.btn_report, a.btn_report"),
            (By.CSS_SELECTOR, "input[type='submit']"),
        ]:
            try:
                btn = wait.until(EC.element_to_be_clickable((by, sel)))
                self._click_element(btn)
                return True
            except TimeoutException:
                continue
            except Exception:
                continue
        self.log("신고하기 버튼을 찾지 못했습니다")
        return False

    def _dismiss_cafe_popup(self, timeout: float = 2) -> str | None:
        """alert / HTML 확인 팝업 닫기. 표시된 메시지 반환."""
        end = time.time() + max(timeout, 0)
        while time.time() < end:
            if self._should_stop():
                return None
            msg = self._read_popup_message(timeout=min(0.8, end - time.time()), dismiss=True)
            if msg:
                return msg
            remaining = end - time.time()
            if remaining <= 0:
                break
            if self._interruptible_sleep(min(0.1, remaining)):
                return None
        return None

    def _close_extra_windows(self, main_handle: str) -> None:
        try:
            for handle in list(self.driver.window_handles):
                if handle != main_handle:
                    try:
                        self.driver.switch_to.window(handle)
                        self.driver.close()
                    except Exception:
                        pass
            if main_handle in self.driver.window_handles:
                self.driver.switch_to.window(main_handle)
            elif self.driver.window_handles:
                self.driver.switch_to.window(self.driver.window_handles[0])
            self.driver.switch_to.default_content()
        except Exception:
            pass

    def _wait_for_new_window(self, before_handles: set[str], timeout: float = 15) -> str | None:
        """신고 클릭 후 열린 새 창(handle) 대기."""
        end = time.time() + timeout
        while time.time() < end:
            if self._should_stop() or not self.driver:
                return None
            try:
                new_handles = set(self.driver.window_handles) - before_handles
                if new_handles:
                    return next(iter(new_handles))
            except WebDriverException:
                pass
            if self._interruptible_sleep(0.15):
                return None
        return None

    def _finish_cafe_report_in_active_window(self) -> str:
        """현재 창(신고 팝업)에서 사유 선택 → 신고하기. ok / already / failed."""
        try:
            WebDriverWait(self.driver, 6).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            pass

        popup_text = self._dismiss_cafe_popup(timeout=0.8)
        if popup_text:
            result = self._parse_blog_report_popup(popup_text)
            if result in ("ok", "already"):
                return result

        if not self._select_cafe_illegal_reason_in_context():
            return "failed"
        self._cafe_fast_delay(0.05, 0.15)
        if not self._submit_cafe_report_in_context():
            popup = self._handle_report_popup_if_any(timeout=2)
            if popup in ("ok", "already"):
                return popup
            return "failed"
        self._cafe_fast_delay(0.3, 0.6)
        popup_text = self._dismiss_cafe_popup(timeout=3)
        if popup_text:
            result = self._parse_blog_report_popup(popup_text)
            if result in ("ok", "already", "failed"):
                return result
        self.log("카페 신고 접수")
        return "ok"

    def _try_cafe_report_inline_layers(self) -> str:
        """새 창이 없을 때 iframe/레이어에서 신고 완료 시도."""
        self.driver.switch_to.default_content()
        frames_to_try: list = [None]
        try:
            frames_to_try.extend(self.driver.find_elements(By.CSS_SELECTOR, "iframe"))
        except Exception:
            pass
        for frame in frames_to_try:
            try:
                self.driver.switch_to.default_content()
                if frame is not None:
                    self.driver.switch_to.frame(frame)
                result = self._finish_cafe_report_in_active_window()
                if result in ("ok", "already"):
                    return result
            except Exception:
                continue
        self.driver.switch_to.default_content()
        return "failed"

    def _report_cafe_in_current_context(self) -> str:
        before_handles = set(self.driver.window_handles)
        main_handle = self.driver.current_window_handle

        if not self._click_cafe_report_button():
            return "failed"

        popup_text = self._dismiss_cafe_popup(timeout=1.2)
        if popup_text and self._is_already_reported_alert(popup_text):
            self.log("이미 신고된 게시물 — 확인 후 다음 진행")
            return "already"

        popup_handle = self._wait_for_new_window(before_handles)
        if popup_handle:
            try:
                self.driver.switch_to.window(popup_handle)
                self.log("신고 새 창으로 전환")
                self._cafe_fast_delay(0.2, 0.45)
                popup_text = self._dismiss_cafe_popup(timeout=1.0)
                if popup_text and self._is_already_reported_alert(popup_text):
                    self.log("이미 신고됨 — 확인 후 다음 진행")
                    self._close_extra_windows(main_handle)
                    return "already"
                result = self._finish_cafe_report_in_active_window()
            except Exception as e:
                self.log(f"신고 새 창 처리 오류: {e}")
                result = "failed"
            self._close_extra_windows(main_handle)
            if result == "ok":
                return "ok"
            if result == "already":
                return "already"
            self.log("새 창 신고 실패 — 레이어 방식 재시도")

        try:
            self.driver.switch_to.window(main_handle)
        except Exception:
            pass
        inline = self._try_cafe_report_inline_layers()
        if inline == "ok":
            return "ok"
        if inline == "already":
            return "already"
        return "failed"

    def report_cafe_article(self, url: str) -> str:
        try:
            self.log(f"게시물 접속: {self._truncate_url(url)}")
            self.driver.get(url)
            self._human_delay(2.5, 4.0)
            self.driver.switch_to.default_content()

            # 게시물 본문은 cafe_main iframe 안에 있는 경우가 많음
            article_frame = None
            for iframe_sel in ("iframe#cafe_main", "iframe.name_cafe_main"):
                try:
                    article_frame = self.driver.find_element(By.CSS_SELECTOR, iframe_sel)
                    break
                except NoSuchElementException:
                    continue

            if article_frame:
                self.driver.switch_to.frame(article_frame)
                result = self._report_cafe_in_current_context()
                self.driver.switch_to.default_content()
                if result in ("ok", "already"):
                    return result
            else:
                result = self._report_cafe_in_current_context()
                if result in ("ok", "already"):
                    return result

            self.driver.switch_to.default_content()
            result = self._report_cafe_in_current_context()
            if result in ("ok", "already"):
                return result

            self.log("카페 신고 UI를 찾지 못했습니다")
            return "failed"
        except Exception as e:
            self.log(f"카페 게시물 신고 오류: {e}")
            return "failed"
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def _cafe_result(
        self,
        account_id: str,
        account_pw: str,
        keyword: str,
        url: str,
        success: bool,
        status: str,
        restriction_reason: str = "",
        restriction_date: str = "",
    ) -> dict:
        return {
            "account_id": account_id,
            "account_password": account_pw,
            "keyword": keyword,
            "url": url,
            "success": success,
            "status": status,
            "restriction_reason": restriction_reason or getattr(self, "_last_login_restriction_reason", "") or "",
            "restriction_date": restriction_date or getattr(self, "_last_login_restriction_date", "") or "",
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def collect_all_cafe_targets(
        self, keywords: list[str], max_pages: int = 3,
    ) -> list[dict]:
        """모든 키워드 × 최대 N페이지에서 카페 URL·제목 일괄 수집 (검색 순서)."""
        seen_keys: set[str] = set()
        targets: list[dict] = []
        for kw in keywords:
            if self._should_stop():
                break
            for item in self.collect_cafe_article_targets(kw, max_pages=max_pages):
                dedup = self._cafe_article_dedup_key(item["url"])
                if not dedup or dedup in seen_keys:
                    continue
                seen_keys.add(dedup)
                targets.append({
                    "keyword": kw,
                    "url": item["url"],
                    "title": item.get("title", ""),
                })
        return targets

    def report_cafe_urls_for_account(
        self,
        naver_id: str,
        naver_pw: str,
        targets: list[dict],
        skip_pairs: set[tuple[str, str]],
    ) -> list[dict]:
        """한 계정으로 수집된 URL 목록 전체 순차 신고."""
        results: list[dict] = []
        if not targets:
            return results

        first_kw = targets[0].get("keyword", "")
        redirect = f"{self.CAFE_SEARCH_URL}{quote(first_kw)}"
        ok, reason = self.login(naver_id, naver_pw, redirect_url=redirect)
        if not ok:
            if reason == "stopped" or self._should_stop():
                return results
            status = "protected" if reason == "protected" else "login_failed"
            item = self._cafe_result(naver_id, naver_pw, "", "", False, status)
            results.append(item)
            if self.result_callback:
                self.result_callback(item)
            if self.progress_callback:
                self.progress_callback(1)
            return results

        self.log(f"[{naver_id}] 수집 URL {len(targets)}건 순차 신고")
        for idx, target in enumerate(targets):
            if self._should_stop():
                break
            kw = target.get("keyword", "")
            url = target.get("url", "")
            title = target.get("title", "")
            if (naver_id, url) in skip_pairs:
                self.log(f"[{naver_id}] 스킵(이미 신고): {title or self._truncate_url(url)}")
                continue
            label = title or self._truncate_url(url)
            self.log(f"[{naver_id}] {idx + 1}/{len(targets)} 신고 시도 — {label}")
            result = self.report_cafe_article(url)
            if result == "ok":
                success, status = True, "ok"
            elif result == "already":
                success, status = False, "already_reported"
            else:
                success, status = False, "failed"
            item = self._cafe_result(naver_id, naver_pw, kw, url, success, status)
            results.append(item)
            if self.result_callback:
                self.result_callback(item)
            if self.progress_callback:
                self.progress_callback(1)
            self._human_delay(2.0, 4.0)
        return results

    def report_cafe_batch(
        self,
        accounts: list[dict],
        keywords: list[str],
        skip_pairs: set[tuple[str, str]],
        targets_callback=None,
    ) -> list[dict]:
        """1) 통합검색 URL 수집 → 2) 계정별 전체 URL 신고."""
        all_results: list[dict] = []
        try:
            self.log("=== 카페 URL 수집 (통합검색 최대 3페이지) ===")
            self.start_driver()
            targets = self.collect_all_cafe_targets(keywords, max_pages=3)
            self.quit_driver()
            self.log(f"수집 완료: 카페 URL {len(targets)}건")
            if targets_callback:
                targets_callback(targets)
            if not targets:
                self.log("수집된 카페 URL이 없습니다.")
                return all_results

            for i, target in enumerate(targets, 1):
                title = target.get("title") or target.get("keyword", "")
                self.log(f"  [{i}] {title} → {self._truncate_url(target['url'])}")

            for account in accounts:
                if self._should_stop():
                    break
                account_id = account.get("id", "")
                account_pw = account.get("password", "")
                self.log(f"[카페] 계정 시작: {account_id}")
                self.start_driver()
                batch = self.report_cafe_urls_for_account(
                    account_id, account_pw, targets, skip_pairs,
                )
                all_results.extend(batch)
                self.quit_driver()
                self._human_delay(2.0, 4.0)
                self.log(f"[카페] 계정 완료: {account_id}")
        finally:
            self.quit_driver()
        return all_results

    # ── 블로그 신고 ─────────────────────────────────────────────

    BLOG_REPORT_REASONS: dict[str, str] = {
        "0": "혐오/차별적/생명경시/욕설 표현입니다.",
        "1": "스팸홍보/도배입니다.",
        "2": "청소년에게 유해한 내용입니다.",
        "3": "불법정보를 포함하고 있습니다.",
        "4": "음란물입니다.",
        "5": "불쾌한 표현이 있습니다.",
    }

    BLOG_POST_URL_RE = re.compile(
        r"blog\.naver\.com/(?:([^/?#]+)/(\d+)|PostView\.naver\?[^#]*?blogId=([^&]+)[^#]*?logNo=(\d+))",
        re.IGNORECASE,
    )

    def _normalize_blog_url(self, url: str) -> str:
        url = (url or "").strip()
        m = self.BLOG_POST_URL_RE.search(url)
        if not m:
            return url
        if m.group(1) and m.group(2):
            return f"https://blog.naver.com/{m.group(1)}/{m.group(2)}"
        blog_id = m.group(3)
        log_no = m.group(4)
        return f"https://blog.naver.com/{blog_id}/{log_no}"

    def _blog_log_no(self, url: str) -> str | None:
        m = self.BLOG_POST_URL_RE.search(self._normalize_blog_url(url))
        if not m:
            return None
        return m.group(2) or m.group(4)

    def _blog_ids_from_url(self, url: str) -> tuple[str | None, str | None]:
        m = self.BLOG_POST_URL_RE.search(self._normalize_blog_url(url))
        if not m:
            return None, None
        if m.group(1) and m.group(2):
            return m.group(1), m.group(2)
        return m.group(3), m.group(4)

    def _blog_post_view_url(self, url: str) -> str | None:
        blog_id, log_no = self._blog_ids_from_url(url)
        if blog_id and log_no:
            return f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
        return None

    def _switch_to_blog_main_frame(self) -> bool:
        self.driver.switch_to.default_content()
        for sel in ("iframe#mainFrame", "iframe#mainframe", "iframe.name_blog"):
            try:
                frame = self.driver.find_element(By.CSS_SELECTOR, sel)
                self.driver.switch_to.frame(frame)
                return True
            except NoSuchElementException:
                continue
        return False

    def _find_blog_overflow_el(self, log_no: str | None = None):
        selectors: list[tuple[str, str]] = []
        if log_no:
            selectors.extend([
                (By.XPATH, f"//a[contains(@class,'btn_overflow_menu') and contains(@class,'_param({log_no})')]"),
                (By.XPATH, f"//a[contains(@class,'_open_overflowmenu') and contains(@class,'_param({log_no})')]"),
                (By.CSS_SELECTOR, f"a[class*='_param({log_no})']"),
            ])
        selectors.extend([
            (By.CSS_SELECTOR, "a.btn_overflow_menu._open_overflowmenu"),
            (By.CSS_SELECTOR, "a.btn_overflow_menu"),
            (By.CSS_SELECTOR, "a._open_overflowmenu"),
            (By.XPATH, "//a[contains(@class,'btn_overflow_menu')]"),
            (By.XPATH, "//a[.//span[contains(@class,'blind') and contains(.,'본문 기타 기능')]]"),
        ])
        for by, sel in selectors:
            try:
                for el in self.driver.find_elements(by, sel):
                    try:
                        if el.is_displayed():
                            return el
                    except Exception:
                        continue
            except Exception:
                continue
        try:
            return self.driver.execute_script(
                """
                var logNo = arguments[0] || '';
                var nodes = document.querySelectorAll(
                    'a.btn_overflow_menu, a._open_overflowmenu, a[class*="_open_overflowmenu"]'
                );
                function visible(el) {
                    if (!el) return false;
                    var r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }
                for (var i = 0; i < nodes.length; i++) {
                    var el = nodes[i];
                    if (logNo && (el.className || '').indexOf('_param(' + logNo + ')') < 0) continue;
                    if (visible(el)) return el;
                }
                for (var j = 0; j < nodes.length; j++) {
                    if (visible(nodes[j])) return nodes[j];
                }
                return null;
                """,
                log_no or "",
            )
        except Exception:
            return None

    def _blog_overflow_exists(self, log_no: str | None = None) -> bool:
        try:
            return bool(self.driver.execute_script(
                """
                var logNo = arguments[0] || '';
                function hasBtn(doc) {
                    var nodes = doc.querySelectorAll('a.btn_overflow_menu, a._open_overflowmenu');
                    for (var i = 0; i < nodes.length; i++) {
                        var el = nodes[i];
                        if (logNo && (el.className || '').indexOf('_param(' + logNo + ')') < 0) continue;
                        var r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return true;
                    }
                    for (var j = 0; j < nodes.length; j++) {
                        var rect = nodes[j].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) return true;
                    }
                    return false;
                }
                var frames = document.querySelectorAll(
                    'iframe#mainFrame, iframe#mainframe, iframe.name_blog, iframe'
                );
                for (var fi = 0; fi < frames.length; fi++) {
                    try {
                        var doc = frames[fi].contentDocument || frames[fi].contentWindow.document;
                        if (doc && hasBtn(doc)) return true;
                    } catch (e) {}
                }
                return hasBtn(document);
                """,
                log_no or "",
            ))
        except Exception:
            return False

    def _wait_blog_post_ui(self, log_no: str | None = None, timeout: int = 15) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._should_stop() or not self.driver:
                return False
            self.driver.switch_to.default_content()
            if self._blog_overflow_exists(log_no):
                return True
            if self._interruptible_sleep(0.5):
                return False
        self.log("블로그 게시물 UI(⋯ 메뉴) 로드 대기 타임아웃")
        return False

    def _click_blog_overflow_via_parent_js(self, log_no: str | None = None) -> bool:
        if not self._wait_until(lambda: self._blog_overflow_exists(log_no), timeout=15):
            return False

        clicked = self.driver.execute_script(
            """
            var logNo = arguments[0] || '';
            function tryClick(doc, win) {
                var nodes = doc.querySelectorAll('a.btn_overflow_menu, a._open_overflowmenu');
                for (var i = 0; i < nodes.length; i++) {
                    var el = nodes[i];
                    if (logNo && (el.className || '').indexOf('_param(' + logNo + ')') < 0) continue;
                    var r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    el.scrollIntoView({block: 'center', inline: 'center'});
                    var view = win || window;
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: view}));
                    el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: view}));
                    el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: view}));
                    if (typeof el.click === 'function') el.click();
                    return true;
                }
                for (var j = 0; j < nodes.length; j++) {
                    var e = nodes[j];
                    var rect = e.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        e.scrollIntoView({block: 'center'});
                        e.click();
                        return true;
                    }
                }
                return false;
            }
            var frames = document.querySelectorAll('iframe#mainFrame, iframe#mainframe, iframe.name_blog');
            for (var fi = 0; fi < frames.length; fi++) {
                try {
                    var doc = frames[fi].contentDocument || frames[fi].contentWindow.document;
                    var win = frames[fi].contentWindow;
                    if (doc && tryClick(doc, win)) return 'iframe';
                } catch (e) {}
            }
            if (tryClick(document, window)) return 'direct';
            return '';
            """,
            log_no or "",
        )
        if clicked:
            self.log(f"블로그 ⋯ 메뉴 클릭 ({clicked})")
            self._switch_to_blog_main_frame()
            self._cafe_fast_delay(0.5, 1.0)
            return True
        return False

    def _click_blog_report_via_parent_js(self) -> bool:
        clicked = self.driver.execute_script(
            """
            function tryClick(doc) {
                var links = doc.querySelectorAll('a._report, a[class*="_report"]');
                for (var i = 0; i < links.length; i++) {
                    var el = links[i];
                    var text = (el.textContent || '').replace(/\\s+/g, '');
                    if (text.indexOf('신고') < 0) continue;
                    var r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return true;
                }
                return false;
            }
            var frames = document.querySelectorAll('iframe#mainFrame, iframe#mainframe, iframe.name_blog');
            for (var fi = 0; fi < frames.length; fi++) {
                try {
                    var doc = frames[fi].contentDocument || frames[fi].contentWindow.document;
                    if (doc && tryClick(doc)) return true;
                } catch (e) {}
            }
            return tryClick(document);
            """
        )
        if clicked:
            self.log("신고하기 메뉴 클릭 (iframe JS)")
            return True
        return False

    def _blog_frame_candidates(self) -> list:
        frames: list = []
        try:
            preferred = self.driver.find_elements(
                By.CSS_SELECTOR, "iframe#mainFrame, iframe#mainframe, iframe.name_blog",
            )
            others = self.driver.find_elements(By.CSS_SELECTOR, "iframe")
            seen = set()
            for frame in preferred + others:
                fid = frame.id or frame.get_attribute("name") or frame.get_attribute("src")
                if fid in seen:
                    continue
                seen.add(fid)
                frames.append(frame)
        except Exception:
            pass
        frames.append(None)
        return frames

    def _click_blog_overflow_menu(self, log_no: str | None = None) -> bool:
        self.driver.switch_to.default_content()
        if self._click_blog_overflow_via_parent_js(log_no):
            return True

        for frame in self._blog_frame_candidates():
            try:
                self.driver.switch_to.default_content()
                if frame is not None:
                    self.driver.switch_to.frame(frame)

                try:
                    WebDriverWait(self.driver, 10).until(
                        lambda d: self._find_blog_overflow_el(log_no) is not None
                    )
                except TimeoutException:
                    continue

                btn = self._find_blog_overflow_el(log_no)
                if not btn:
                    continue

                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});", btn,
                )
                self._cafe_fast_delay(0.2, 0.4)
                try:
                    self.driver.execute_script(
                        """
                        var el = arguments[0];
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, view:window}));
                        el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
                        if (typeof el.click === 'function') el.click();
                        return true;
                        """,
                        btn,
                    )
                except Exception:
                    self._click_element(btn)

                self._cafe_fast_delay(0.4, 0.8)
                try:
                    WebDriverWait(self.driver, 4).until(
                        EC.presence_of_element_located((
                            By.CSS_SELECTOR, "a._report, a[class*='_report']",
                        ))
                    )
                except TimeoutException:
                    pass

                self.log("블로그 ⋯ 메뉴 클릭")
                return True
            except Exception:
                continue

        self.log("블로그 ⋯ 메뉴를 찾지 못했습니다")
        return False

    def _click_blog_report_menu_item(self) -> bool:
        self.driver.switch_to.default_content()
        if self._click_blog_report_via_parent_js():
            return True

        if self._switch_to_blog_main_frame():
            pass
        else:
            self.driver.switch_to.default_content()

        wait = self._wait(8)
        for by, sel in [
            (By.CSS_SELECTOR, "a._report"),
            (By.CSS_SELECTOR, "a[class*='_report']"),
            (By.XPATH, "//a[contains(@class,'_report') and contains(.,'신고')]"),
            (By.XPATH, "//a[contains(.,'신고하기')]"),
        ]:
            try:
                link = wait.until(EC.presence_of_element_located((by, sel)))
                if link.is_displayed():
                    self._click_element(link)
                    self.log("신고하기 메뉴 클릭")
                    return True
            except TimeoutException:
                continue
            except Exception:
                continue
        try:
            clicked = self.driver.execute_script(
                """
                var links = document.querySelectorAll('a._report, a[class*="_report"]');
                for (var i = 0; i < links.length; i++) {
                    var el = links[i];
                    var text = (el.textContent || '').replace(/\\s+/g, '');
                    if (text.indexOf('신고') >= 0) {
                        el.scrollIntoView({block:'center'});
                        el.click();
                        return true;
                    }
                }
                return false;
                """
            )
            if clicked:
                self.log("신고하기 메뉴 클릭")
                return True
        except Exception:
            pass
        self.log("신고하기 메뉴를 찾지 못했습니다")
        return False

    def _verify_blog_report_reason_selected(self, reason_id: str) -> bool:
        reason_id = str(reason_id or "3")
        try:
            return bool(self.driver.execute_script(
                """
                var rid = arguments[0];
                var radio = document.getElementById(rid);
                return !!(radio && radio.checked);
                """,
                reason_id,
            ))
        except Exception:
            return False

    def _select_blog_report_reason(self, reason_id: str = "3") -> str:
        """selected | already | ok | failed | stopped"""
        popup = self._poll_once_already_reported()
        if popup in ("already", "ok"):
            return popup
        reason_id = str(reason_id or "3")
        label_text = self.BLOG_REPORT_REASONS.get(reason_id, "")

        end = time.time() + 8
        loaded = False
        while time.time() < end:
            if self._should_stop() or not self.driver:
                return "stopped"
            popup = self._poll_once_already_reported()
            if popup in ("already", "ok"):
                return popup
            try:
                if self.driver.find_elements(
                    By.CSS_SELECTOR, "input.report_reason, .lst_reason, .list_type",
                ):
                    loaded = True
                    break
            except UnexpectedAlertPresentException:
                popup = self._poll_once_already_reported()
                if popup in ("already", "ok"):
                    return popup
            except WebDriverException as e:
                if "alert" in str(e).lower():
                    popup = self._poll_once_already_reported()
                    if popup:
                        return popup
            if self._interruptible_sleep(0.12):
                return "stopped"
        if not loaded:
            popup = self._handle_already_reported_if_any(timeout=5)
            if popup in ("already", "ok"):
                return popup
            self.log("신고 사유 선택 UI 로드 실패")
            return "failed"

        for attempt in range(3):
            popup = self._poll_once_already_reported()
            if popup in ("already", "ok"):
                return popup
            for by, sel in [
                (By.CSS_SELECTOR, f"label[for='{reason_id}']"),
                (By.CSS_SELECTOR, f"div.check_area label[for='{reason_id}']"),
                (By.CSS_SELECTOR, f"input#{reason_id}.report_reason"),
                (By.XPATH, f"//label[@for='{reason_id}']"),
                (By.XPATH, f"//label[contains(.,'{label_text[:10]}')]") if label_text else (By.ID, "__none__"),
            ]:
                if sel == "__none__":
                    continue
                try:
                    el = self.driver.find_element(by, sel)
                    if not el.is_displayed():
                        continue
                    self._click_element(el)
                    self._cafe_fast_delay(0.15, 0.35)
                    if self._verify_blog_report_reason_selected(reason_id):
                        self.log(f"신고 사유 선택: {label_text or reason_id}")
                        return "selected"
                except Exception:
                    continue

            try:
                selected = self.driver.execute_script(
                    """
                    var rid = arguments[0];
                    var labelText = arguments[1];
                    var label = document.querySelector('label[for="' + rid + '"]');
                    if (label) {
                        label.scrollIntoView({block: 'center'});
                        label.click();
                        var radio = document.getElementById(rid);
                        if (radio) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('input', {bubbles: true}));
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                        return !!(radio && radio.checked);
                    }
                    var labels = document.querySelectorAll('label');
                    for (var i = 0; i < labels.length; i++) {
                        var t = (labels[i].textContent || '').replace(/\\s+/g, '');
                        if (labelText && t.indexOf(labelText.replace(/\\s+/g, '').slice(0, 6)) >= 0) {
                            labels[i].click();
                            var forId = labels[i].getAttribute('for');
                            var r = forId ? document.getElementById(forId) : null;
                            return !!(r && r.checked);
                        }
                    }
                    return false;
                    """,
                    reason_id,
                    label_text,
                )
                if selected and self._verify_blog_report_reason_selected(reason_id):
                    self.log(f"신고 사유 선택: {label_text or reason_id}")
                    return "selected"
            except Exception:
                pass
            self._cafe_fast_delay(0.2, 0.4)

        popup = self._poll_once_already_reported()
        if popup in ("already", "ok"):
            return popup
        self.log("신고 사유 선택 실패")
        return "failed"

    def _submit_blog_report_popup(self) -> str:
        """clicked | ok | already | failed"""
        popup = self._poll_once_already_reported()
        if popup in ("ok", "already"):
            return popup
        end = time.time() + 6
        while time.time() < end:
            popup = self._poll_once_already_reported()
            if popup in ("ok", "already"):
                return popup
            for by, sel in [
                (By.CSS_SELECTOR, "a.btn_submit"),
                (By.XPATH, "//a[contains(@class,'btn_submit')]"),
                (By.XPATH, "//a[contains(.,'신고하기') and contains(@class,'btn')]"),
            ]:
                try:
                    btn = self.driver.find_element(by, sel)
                    if btn.is_displayed() and btn.is_enabled():
                        self._click_element(btn)
                        self.log("신고 팝업 — 신고하기 클릭")
                        return "clicked"
                except WebDriverException as e:
                    if "alert" in str(e).lower():
                        popup = self._poll_once_already_reported()
                        if popup in ("ok", "already"):
                            return popup
                except Exception:
                    continue
            if self._interruptible_sleep(0.15):
                return "failed"
        self.log("신고 팝업 신고하기 버튼을 찾지 못했습니다")
        return "failed"

    def _is_blog_report_validation_alert(self, text: str) -> bool:
        if not text:
            return False
        return any(
            k in text
            for k in ("신고 유형", "사유를 선택", "사유 선택", "유형을 선택", "선택하세요", "선택해")
        )

    def _parse_blog_report_popup(self, popup_text: str | None) -> str:
        """팝업 메시지 → already / ok / failed."""
        if popup_text:
            self._last_popup_message = popup_text
        status = self._classify_popup_message(popup_text)
        if status == "already":
            self.log("이미 신고됨 — 확인 후 다음 진행")
            return "already"
        if status == "ok":
            self.log("블로그 신고 접수 완료")
            return "ok"
        if status == "failed":
            self.log(f"신고 실패: {popup_text}")
            return "failed"
        if not popup_text:
            return "failed"
        self.log(f"신고 결과 미확인: {popup_text}")
        return "failed"

    def _finish_blog_report_in_popup(self, reason_id: str = "3", *, skip_initial_wait: bool = False) -> str:
        """신고 팝업 창에서 사유 선택 → 제출 1회. ok / already / failed."""
        if self._should_stop() or not self.driver:
            return "stopped"

        if not skip_initial_wait:
            popup = self._wait_report_popup_outcome(timeout=10)
            if popup in ("ok", "already", "failed", "stopped"):
                return "stopped" if popup == "stopped" else popup

        for attempt in range(2):
            if self._should_stop() or not self.driver:
                return "stopped"

            select_result = self._select_blog_report_reason(reason_id)
            if select_result in ("already", "ok"):
                return select_result
            if select_result == "stopped":
                return "stopped"
            if select_result != "selected":
                popup = self._handle_already_reported_if_any(timeout=1.5)
                if popup in ("ok", "already"):
                    return popup
                return "failed"
            if not self._verify_blog_report_reason_selected(reason_id):
                self.log(f"신고 사유 선택 확인 실패 (시도 {attempt + 1}/2)")
                if attempt == 0:
                    continue
                return "failed"

            self._cafe_fast_delay(0.2, 0.4)
            submit_result = self._submit_blog_report_popup()
            if submit_result in ("ok", "already"):
                return submit_result
            if submit_result != "clicked":
                popup = self._handle_already_reported_if_any(timeout=2)
                if popup in ("ok", "already"):
                    return popup
                return "failed"

            self._cafe_fast_delay(0.4, 0.8)
            popup_text = self._dismiss_cafe_popup(timeout=4)
            if not popup_text:
                popup = self._handle_already_reported_if_any(timeout=2)
                if popup in ("ok", "already"):
                    return popup
            result = self._parse_blog_report_popup(popup_text)
            if result in ("ok", "already"):
                return result
            if result == "failed" and popup_text and self._is_blog_report_validation_alert(popup_text):
                if attempt == 0:
                    self.log("신고 사유 재선택 후 재시도")
                    continue
            return result

        return "failed"

    def _report_blog_in_current_context(self, reason_id: str = "3", log_no: str | None = None) -> str:
        if self._should_stop() or not self.driver:
            return "stopped"
        before_handles = set(self.driver.window_handles)
        main_handle = self.driver.current_window_handle

        if not self._click_blog_overflow_menu(log_no):
            return "failed"
        if not self._click_blog_report_menu_item():
            return "failed"

        popup_handle = self._wait_for_new_window(before_handles)
        if popup_handle:
            try:
                self.driver.switch_to.window(popup_handle)
                self.log("신고 팝업 창으로 전환")
                outcome = self._wait_report_popup_outcome(timeout=12)
                if outcome in ("ok", "already"):
                    self._close_extra_windows(main_handle)
                    return outcome
                if outcome == "stopped":
                    self._close_extra_windows(main_handle)
                    return "stopped"
                if outcome == "failed":
                    self._close_extra_windows(main_handle)
                    return "failed"
                result = self._finish_blog_report_in_popup(reason_id, skip_initial_wait=True)
            except WebDriverException as e:
                err = str(e).lower()
                if "alert" in err:
                    popup = self._handle_already_reported_if_any(timeout=2)
                    result = popup if popup in ("ok", "already") else "failed"
                    if result == "failed":
                        self.log(f"신고 팝업 alert 처리: {e}")
                else:
                    self.log(f"신고 팝업 처리 오류: {e}")
                    result = "failed"
            except Exception as e:
                self.log(f"신고 팝업 처리 오류: {e}")
                result = "failed"
            self._close_extra_windows(main_handle)
            try:
                self.driver.switch_to.window(main_handle)
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return result

        self.log("신고 팝업 창이 열리지 않았습니다")
        popup = self._handle_already_reported_if_any(timeout=1)
        if popup in ("ok", "already"):
            self._close_extra_windows(main_handle)
            return popup
        return "failed"

    def report_blog_post(self, url: str, reason_id: str = "3") -> str:
        if self._should_stop() or not self.driver:
            return "stopped"
        norm = self._normalize_blog_url(url)
        log_no = self._blog_log_no(norm)
        if not log_no:
            self.log(f"블로그 URL 형식 오류: {url}")
            return "failed"

        self._last_blog_title = ""
        page_urls = [norm]
        post_view = self._blog_post_view_url(norm)
        if post_view and post_view not in page_urls:
            page_urls.append(post_view)

        try:
            for page_url in page_urls:
                if self._should_stop() or not self.driver:
                    return "stopped"
                current = self.driver.current_url
                current_log = self._blog_log_no(current)
                if current_log == log_no and "blog.naver.com" in current:
                    self.log(f"블로그 게시물 이미 열림: {self._truncate_url(current)}")
                    self._human_delay(1.0, 2.0)
                else:
                    self.log(f"블로그 접속: {self._truncate_url(page_url)}")
                    self.driver.get(page_url)
                    self._human_delay(3.0, 5.0)
                if self._should_stop() or not self.driver:
                    return "stopped"

                self.driver.switch_to.default_content()
                if not self._wait_blog_post_ui(log_no, timeout=15):
                    if self._should_stop() or not self.driver:
                        return "stopped"
                    continue
                self._last_blog_title = self._extract_blog_post_title()
                if self._last_blog_title:
                    self.log(f"게시물 제목: {self._last_blog_title[:60]}")
                result = self._report_blog_in_current_context(reason_id, log_no)
                if result == "stopped":
                    return "stopped"
                if result in ("ok", "already"):
                    return result

            self.log("블로그 신고 UI를 찾지 못했습니다")
            return "failed"
        except InvalidSessionIdException:
            return "stopped" if self._should_stop() else "failed"
        except WebDriverException as e:
            if "invalid session" in str(e).lower() or self._should_stop():
                return "stopped"
            self.log(f"블로그 신고 오류: {e}")
            return "failed"
        except Exception as e:
            self.log(f"블로그 신고 오류: {e}")
            return "failed"
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def _extract_blog_post_title(self) -> str:
        self.driver.switch_to.default_content()
        try:
            title = self.driver.execute_script(
                """
                function fromDoc(doc) {
                    if (!doc) return '';
                    var box = doc.querySelector(
                        '.se-title-text, div.se-module-text.se-title-text, .se_module_title'
                    );
                    if (box) {
                        var t = (box.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (t) return t;
                    }
                    var legacy = doc.querySelector('.pcol1 .htitle, .tit_h3, .se-title');
                    return legacy ? (legacy.textContent || '').replace(/\\s+/g, ' ').trim() : '';
                }
                var frames = document.querySelectorAll('iframe#mainFrame, iframe#mainframe, iframe.name_blog');
                for (var i = 0; i < frames.length; i++) {
                    try {
                        var doc = frames[i].contentDocument || frames[i].contentWindow.document;
                        var t = fromDoc(doc);
                        if (t) return t;
                    } catch (e) {}
                }
                return fromDoc(document);
                """
            )
            return (title or "").strip()
        except Exception:
            return ""
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def _blog_result(
        self,
        account_id: str,
        account_pw: str,
        url: str,
        reason_id: str,
        success: bool,
        status: str,
        title: str = "",
        popup_message: str = "",
        restriction_reason: str = "",
        restriction_date: str = "",
    ) -> dict:
        return {
            "account_id": account_id,
            "account_password": account_pw,
            "url": url,
            "title": title or "",
            "reason_id": reason_id,
            "reason": self.BLOG_REPORT_REASONS.get(str(reason_id), ""),
            "success": success,
            "status": status,
            "popup_message": popup_message or getattr(self, "_last_popup_message", "") or "",
            "restriction_reason": restriction_reason or getattr(self, "_last_login_restriction_reason", "") or "",
            "restriction_date": restriction_date or getattr(self, "_last_login_restriction_date", "") or "",
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _normalize_blog_entries(self, entries: list) -> list[dict]:
        normalized: list[dict] = []
        for item in entries or []:
            if isinstance(item, dict) and item.get("url"):
                normalized.append({
                    "url": self._normalize_blog_url(item["url"]),
                    "reason_id": str(item.get("reason_id", "3")),
                })
            elif isinstance(item, str) and item.strip():
                normalized.append({
                    "url": self._normalize_blog_url(item),
                    "reason_id": "3",
                })
        return normalized

    def _assign_blog_url_accounts(
        self,
        accounts: list[dict],
        entries: list,
        skip_pairs: set[tuple[str, str]],
    ) -> list[tuple[dict, dict]]:
        """(구) 게시물당 계정 1개 배정 — report_blog_batch에서 미사용."""
        tasks = self._normalize_blog_entries(entries)
        if not accounts or not tasks:
            return []
        pairs: list[tuple[dict, dict]] = []
        acc_idx = 0
        for entry in tasks:
            norm = entry["url"]
            assigned = False
            for _ in range(len(accounts)):
                acc = accounts[acc_idx % len(accounts)]
                acc_idx += 1
                aid = acc.get("id", "")
                if (aid, norm) in skip_pairs:
                    continue
                pairs.append((acc, entry))
                assigned = True
                break
            if not assigned:
                self.log(f"스킵(모든 계정이 이미 신고): {self._truncate_url(norm)}")
        return pairs

    def report_blog_urls_for_account(
        self,
        naver_id: str,
        naver_pw: str,
        entries: list[dict],
        skip_pairs: set[tuple[str, str]],
        known_titles: dict[tuple[str, str], str] | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        known_titles = known_titles or {}
        all_entries = self._normalize_blog_entries(entries)
        pending: list[dict] = []

        for entry in all_entries:
            url = entry["url"]
            reason_id = entry["reason_id"]
            pair = (naver_id, url)
            if pair in skip_pairs:
                title = known_titles.get(pair, "")
                item = self._blog_result(
                    naver_id, naver_pw, url, reason_id, False, "previously_reported", title=title,
                )
                results.append(item)
                self.log(f"[{naver_id}] 이미 신고 기록 — 스킵: {self._truncate_url(url)}")
                if self.result_callback:
                    self.result_callback(item)
                if self.progress_callback:
                    self.progress_callback(1)
                continue
            pending.append(entry)

        if not pending:
            return results

        ok, reason = self.login(naver_id, naver_pw, redirect_url=pending[0]["url"])
        if not ok:
            if reason == "stopped" or self._should_stop():
                return results
            status = "protected" if reason == "protected" else "login_failed"
            for entry in pending:
                item = self._blog_result(
                    naver_id, naver_pw, entry["url"], entry["reason_id"], False, status,
                )
                results.append(item)
                if self.result_callback:
                    self.result_callback(item)
                if self.progress_callback:
                    self.progress_callback(1)
            return results

        self.log(f"[{naver_id}] 블로그 {len(pending)}건 순차 신고")
        session_done: set[tuple[str, str]] = set()
        for idx, entry in enumerate(pending):
            if self._should_stop():
                break
            url = entry["url"]
            reason_id = entry["reason_id"]
            pair = (naver_id, url)
            if pair in session_done:
                self.log(f"[{naver_id}] 이번 실행 중 처리됨 — 스킵: {self._truncate_url(url)}")
                if self.progress_callback:
                    self.progress_callback(1)
                continue
            self.log(f"[{naver_id}] {idx + 1}/{len(pending)} — {self._truncate_url(url)}")
            self._last_popup_message = ""
            result = self.report_blog_post(url, reason_id=reason_id)
            if result == "stopped" or self._should_stop():
                break
            title = getattr(self, "_last_blog_title", "") or ""
            popup_message = getattr(self, "_last_popup_message", "") or ""
            if result == "ok":
                success, status = True, "ok"
                session_done.add(pair)
            elif result == "already":
                success, status = False, "already_reported"
                session_done.add(pair)
            else:
                success, status = False, "failed"
            item = self._blog_result(
                naver_id, naver_pw, url, reason_id, success, status,
                title=title, popup_message=popup_message,
            )
            results.append(item)
            if self.result_callback:
                self.result_callback(item)
            if self.progress_callback:
                self.progress_callback(1)
            self._human_delay(1.5, 3.0)
        return results

    def report_blog_batch(
        self,
        accounts: list[dict],
        entries: list,
        skip_pairs: set[tuple[str, str]],
        known_titles: dict[tuple[str, str], str] | None = None,
    ) -> list[dict]:
        """계정당 등록된 모든 URL을 순차 신고 (URL·계정당 1회)."""
        all_results: list[dict] = []
        tasks = self._normalize_blog_entries(entries)
        if not accounts or not tasks:
            self.log("신고할 블로그 URL이 없습니다.")
            return all_results

        self.log(
            f"블로그 신고: URL {len(tasks)}개, 계정 {len(accounts)}개 "
            f"(계정당 전체 URL 순차 신고)"
        )

        for acc in accounts:
            if self._should_stop():
                break
            aid = acc.get("id", "")
            has_pending = any((aid, e["url"]) not in skip_pairs for e in tasks)
            if not has_pending:
                self.log(f"[{aid}] 모든 URL 이미 신고됨 — 로그인 생략, 다음 계정으로")
                if self.progress_callback:
                    for _ in tasks:
                        self.progress_callback(1)
                continue

            self.log(f"[블로그] 계정 시작: {aid}")
            self.start_driver()
            try:
                batch = self.report_blog_urls_for_account(
                    aid,
                    acc.get("password", ""),
                    tasks,
                    skip_pairs,
                    known_titles,
                )
                all_results.extend(batch)
            finally:
                self.quit_driver()
            self._human_delay(1.5, 2.5)
            self.log(f"[블로그] 계정 완료: {aid}")
        return all_results
