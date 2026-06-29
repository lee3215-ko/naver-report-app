import json
import os
import random
import re
import time
import base64
from datetime import datetime
from urllib.parse import quote, urlparse, urlunparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException
from webdriver_manager.chrome import ChromeDriverManager


class NaverReporter:
    """네이버 고객센터 불법성 신고 자동화 (Selenium)"""

    INQUIRY_FORM_URL = (
        "https://help.naver.com/inquiry/input.help?categoryNo=5749&serviceNo=5626&lang=ko"
    )

    def __init__(self,
                 api_key: str,
                 model: str,
                 headless: bool = False,
                 log_callback=None,
                 result_callback=None,
                 progress_callback=None):
        self.api_key = api_key
        self.model = model
        self.headless = headless
        self.log_callback = log_callback or print
        self.result_callback = result_callback
        self.progress_callback = progress_callback
        self.driver = None
        self.cancel_requested = False
        self.client = self._openai_client()

    def request_cancel(self):
        self.cancel_requested = True
        if self.driver:
            self.log("작업 중단 — 브라우저 종료")
            self.quit_driver()

    def _should_stop(self) -> bool:
        return self.cancel_requested

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
        time.sleep(random.uniform(min_sec, max_sec))

    def _cafe_fast_delay(self, min_sec: float = 0.08, max_sec: float = 0.22):
        """카페 신고 팝업 — 짧은 대기."""
        time.sleep(random.uniform(min_sec, max_sec))

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

    def _accept_alert(self, timeout: float = 3) -> str | None:
        try:
            WebDriverWait(self.driver, timeout).until(EC.alert_is_present())
            alert = self.driver.switch_to.alert
            text = alert.text or ""
            alert.accept()
            if text:
                self.log(f"팝업 확인: {text}")
            return text
        except TimeoutException:
            return None
        except Exception as e:
            self.log(f"팝업 처리 오류: {e}")
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

    def _select_illegal_type(self, wait) -> bool:
        try:
            select_btn = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "button.InquiryInput_select_btn__d28Te")
            ))
            self._click_element(select_btn)
            self.log("유형 선택 버튼 클릭")
            self._human_delay(0.6, 1.2)
            illegal_opt = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//button[@role='option' and contains(text(),'불법성')]")
            ))
            self._click_element(illegal_opt)
            self.log("'불법성' 선택")
            self._human_delay(0.8, 1.5)
            return True
        except Exception as e:
            self.log(f"유형 '불법성' 선택 오류: {e}")
            return False

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
            self.log(f"GPT 리라이트 오류: {e}")
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
        self.log("Chrome 드라이버 준비 중...")
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.log("Chrome 드라이버 시작 완료")

    def quit_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.log("Chrome 드라이버 종료")

    def _wait(self, seconds: int = 10):
        return WebDriverWait(self.driver, seconds)

    def _vision_model(self) -> str:
        """CAPTCHA 인식용 Vision 지원 모델."""
        vision_models = {"gpt-4o", "gpt-4-turbo", "gpt-4-turbo-2024-04-09"}
        if self.model in vision_models:
            return self.model
        return "gpt-4o"

    def _is_logged_in(self) -> bool:
        url = self.driver.current_url
        if "inquiry/input.help" in url or "help.naver.com" in url:
            return True
        if "nid.naver.com" not in url:
            return True
        return False

    def _is_account_protected(self) -> bool:
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

    def _vision_answer(self, prompt: str, b64: str | None = None) -> str:
        if not self.client:
            return ""
        content = [{"type": "text", "text": prompt}]
        if b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        response = self.client.chat.completions.create(
            model=self._vision_model(),
            messages=[{"role": "user", "content": content}],
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()

    def _reenter_password(self, naver_pw: str):
        try:
            pw_input = self.driver.find_element(By.ID, "pw")
            if not pw_input.is_displayed():
                return
            self._type_into_element(pw_input, naver_pw, label="비밀번호")
            self.log("비밀번호 재입력 완료")
        except NoSuchElementException:
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
        try:
            el = self.driver.find_element(By.ID, "chptcha")
            if el.is_displayed() and el.is_enabled():
                return el
        except NoSuchElementException:
            pass
        return None

    def _find_captcha_question(self) -> str:
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
        # 질문 문장이 페이지에 직접 표시되는 경우
        try:
            for el in self.driver.find_elements(By.XPATH, "//p | //strong | //span | //div"):
                text = el.text.strip()
                if not text or len(text) > 200:
                    continue
                if any(k in text for k in ("입니까", "얼마", "몇", "무엇", "어떤", "합계", "가격", "개수")):
                    return text
        except Exception:
            pass
        return ""

    def _find_captcha_image(self):
        selectors = ["#captchaimg", "img.captcha_img", "div.captcha img", "img[alt*='캡차']", "img[alt*='captcha']"]
        for sel in selectors:
            try:
                return self.driver.find_element(By.CSS_SELECTOR, sel)
            except NoSuchElementException:
                continue
        return None

    def _submit_login(self):
        wait = self._wait(8)
        for by, sel in [
            (By.ID, "log.login"),
            (By.CSS_SELECTOR, "button.btn_login"),
            (By.CSS_SELECTOR, "input.btn_login"),
            (By.CSS_SELECTOR, "button[type='submit']"),
        ]:
            try:
                btn = wait.until(EC.element_to_be_clickable((by, sel)))
                btn.click()
                self.log("로그인 버튼 클릭")
                return
            except (NoSuchElementException, TimeoutException):
                continue
        try:
            self.driver.execute_script(
                "var b = document.getElementById('log.login'); if (b) b.click();"
            )
            self.log("로그인 버튼 클릭 (JS)")
        except Exception:
            pass

    def _has_receipt_captcha(self) -> bool:
        if self._find_captcha_question():
            return True
        try:
            return bool(self.driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='정답']"))
        except Exception:
            return False

    def _has_char_captcha(self) -> bool:
        try:
            return bool(self.driver.find_element(By.ID, "captchaimg"))
        except NoSuchElementException:
            return False

    def solve_receipt_captcha(self, naver_pw: str) -> bool:
        """영수증/질문형 보안 화면: 비밀번호 → 정답란 → 로그인."""
        if not self.client:
            self.log("OpenAI 클라이언트 없음 - 보안 질문을 해결할 수 없습니다.")
            return False

        try:
            # 1) 비밀번호만 pw 칸에 입력
            self._reenter_password(naver_pw)
            time.sleep(0.3)

            # 2) 질문 분석 및 답 생성
            question = self._find_captcha_question()
            img_el = self._find_captcha_image()
            b64 = self._element_to_b64(img_el) if img_el else None

            if question:
                self.log(f"보안 질문: {question}")
            else:
                self.log("보안 질문 텍스트 추출 실패, 이미지만 분석합니다.")

            prompt = (
                "네이버 로그인 보안 질문입니다. 이미지(영수증/표 등)의 내용을 읽고 질문에 답하세요.\n"
                f"질문: {question or '이미지 내용을 바탕으로 요구된 정답을 찾으세요.'}\n"
                "설명 없이 정답만 출력하세요. 숫자면 숫자만, 문자면 해당 문자만."
            )
            answer = self._vision_answer(prompt, b64)
            answer = answer.split("\n")[0].strip()
            if question and any(k in question for k in ("가격", "얼마", "합계", "개수", "몇")):
                digits = re.sub(r"\D", "", answer)
                if digits:
                    answer = digits
            else:
                answer = re.sub(r"[^\w가-힣]", "", answer)
            if not answer:
                self.log("보안 질문 답변 생성 실패")
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

            # 4) 로그인 버튼
            self._submit_login()
            self.log("정답 입력 및 로그인 시도")
            return True
        except Exception as e:
            self.log(f"보안 질문 처리 오류: {e}")
            return False

    def solve_captcha(self) -> bool:
        """표시된 문자 CAPTCHA 이미지를 API로 풀고 입력합니다."""
        if not self.client:
            self.log("OpenAI 클라이언트 없음 - 캡챠를 해결할 수 없습니다.")
            return False

        if self._has_receipt_captcha():
            return False  # 영수증형은 solve_receipt_captcha에서 처리

        try:
            img_el = self.driver.find_element(By.ID, "captchaimg")
            b64 = self._element_to_b64(img_el)
            self.log("CAPTCHA 이미지 확인, GPT Vision으로 인식 중...")
            captcha_text = re.sub(
                r"[^A-Za-z0-9]",
                "",
                self._vision_answer("이미지에 표시된 문자(숫자/영문)만 정확히 알려주세요. 설명 없이 문자만 출력하세요.", b64),
            )
            self.log(f"CAPTCHA 인식 결과: {captcha_text}")

            chg_txt = self._find_char_captcha_input()
            if not chg_txt:
                self.log("문자 CAPTCHA 입력란 없음")
                return True

            self._type_into_element(chg_txt, captcha_text, label="CAPTCHA")
            time.sleep(0.2)
            self._submit_login()
            self.log("CAPTCHA 입력 및 제출")
            return True
        except NoSuchElementException:
            return True  # 캡챠 없음
        except Exception as e:
            self.log(f"CAPTCHA 처리 오류: {e}")
            return False

    def handle_login_challenges(self, naver_pw: str) -> bool:
        """로그인 중 나타나는 보안 화면(문자/영수증 캡챠)을 처리합니다."""
        if self._has_receipt_captcha():
            return self.solve_receipt_captcha(naver_pw)
        if self._has_char_captcha():
            return self.solve_captcha()
        return True

    def login(self, naver_id: str, naver_pw: str, redirect_url: str | None = None) -> tuple[bool, str]:
        target = redirect_url or self.INQUIRY_FORM_URL
        login_url = (
            "https://nid.naver.com/nidlogin.login?url="
            + quote(target, safe="")
        )
        self.driver.get(login_url)
        self.log(f"네이버 로그인 페이지 접속: {naver_id}")
        self._human_delay(1.0, 2.0)

        wait = self._wait(15)
        try:
            id_input = wait.until(EC.presence_of_element_located((By.ID, "id")))
            pw_input = self.driver.find_element(By.ID, "pw")

            for char in naver_id:
                id_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.08))
            for char in naver_pw:
                pw_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.08))
            self.log("아이디/비밀번호 입력 완료")
            self._human_delay(0.5, 1.2)

            pw_input.send_keys(Keys.RETURN)
            self.log("로그인 시도")
            self._human_delay(1.5, 3.0)

            for attempt in range(5):
                if self._is_account_protected():
                    self.log("계정 보호조치 화면 감지")
                    return False, "protected"
                if self._is_logged_in():
                    self.log("로그인 성공")
                    return True, "ok"

                if not self.handle_login_challenges(naver_pw):
                    self.log(f"보안 화면 처리 실패 (시도 {attempt + 1}/5)")
                self._human_delay(1.5, 3.0)

            if self._is_account_protected():
                self.log("계정 보호조치 화면 감지")
                return False, "protected"
            if self._is_logged_in():
                self.log("로그인 성공")
                return True, "ok"

            self.log("로그인 타임아웃")
            return False, "failed"
        except TimeoutException:
            self.log("로그인 타임아웃")
            return False, "failed"
        except Exception as e:
            self.log(f"로그인 오류: {e}")
            return False, "failed"

    def _find_inquiry_question(self) -> str:
        for xpath in [
            "//*[contains(text(),'빈 칸')]",
            "//*[contains(text(),'입니까')]",
            "//*[contains(text(),'정답을 입력')]",
            "//*[contains(text(),'질문에 정답')]",
        ]:
            try:
                for el in self.driver.find_elements(By.XPATH, xpath):
                    text = el.text.strip()
                    if text and 5 < len(text) < 300:
                        return text
            except Exception:
                continue
        return ""

    def _find_inquiry_captcha_image(self):
        for sel in [
            "div.InquiryInput img",
            "form img[src]",
            ".captcha img",
            "img[alt*='영수증']",
        ]:
            try:
                for img in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if img.is_displayed() and img.size.get("width", 0) > 40:
                        return img
            except Exception:
                continue
        return None

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

        if question:
            self.log(f"문의 폼 추가 질문: {question}")
        b64 = self._element_to_b64(img_el) if img_el else None
        prompt = (
            "네이버 문의 폼 보안 질문입니다. 이미지(영수증/표)를 참고하여 질문에 답하세요.\n"
            f"질문: {question or '이미지 내용을 바탕으로 빈 칸에 들어갈 정답을 찾으세요.'}\n"
            "설명 없이 정답만 출력하세요."
        )
        answer = self._vision_answer(prompt, b64).split("\n")[0].strip()
        if question and any(k in question for k in ("가격", "얼마", "합계", "개수", "몇", "숫자", "번째")):
            digits = re.sub(r"\D", "", answer)
            if digits:
                answer = digits
        else:
            answer = re.sub(r"[^\w가-힣]", "", answer)

        if not answer:
            self.log("추가 질문 답변 생성 실패")
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

    def fill_form(self, site: str, report_type: str, content: str, search_url: str = "") -> bool:
        """문의 작성 폼을 채웁니다."""
        if self._should_stop():
            return False
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
            self._type_into_element(textarea, content, label="상세 내용")
            self.log(f"상세 내용 입력 ({len(content)}자)")
            self._human_delay(0.5, 1.2)

            try:
                if not self._select_illegal_type(wait):
                    self.log("불법성 유형 선택 실패")
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
        for task in tasks:
            site = task.get("site", "")
            search_url = task.get("search_url", "") or site
            item = {
                "account_id": naver_id,
                "account_password": naver_pw,
                "site": site,
                "report_type": task.get("report_type", ""),
                "original": task.get("template", ""),
                "rewritten": "보호조치 해제 필요",
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "success": False,
                "status": "protected",
                "search_url": search_url,
                "search_url_custom": task.get("search_url_custom", False),
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
                    self.log(f"[{naver_id}] 보호조치 화면 — 결과에 기록")
                    self._emit_protection_results(naver_id, naver_pw, tasks)
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

                self._human_delay(1.0, 2.5)
                rewritten = self._rewrite(template, naver_id, site, report_type)
                self.log(f"[{naver_id}] {idx + 1}/{len(tasks)} 리라이트 완료 ({len(rewritten)}자)")
                self._human_delay(0.8, 1.8)

                success = self.fill_form(site, report_type, rewritten, search_url=search_url)
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

    def _is_already_reported_alert(self, text: str) -> bool:
        if not text:
            return False
        return any(
            k in text
            for k in ("이미 신고", "이미 신고되", "이미 신고한", "이미 신고 하", "신고하셨")
        )

    def _dismiss_cafe_popup(self, timeout: float = 2) -> str | None:
        """alert 또는 「확인」 팝업 닫기. 표시된 메시지 반환."""
        text = self._accept_alert(timeout=timeout)
        if text:
            return text
        for by, sel in [
            (By.XPATH, "//button[contains(.,'확인')]"),
            (By.XPATH, "//a[contains(.,'확인')]"),
            (By.CSS_SELECTOR, "button.btn_confirm, a.btn_confirm"),
        ]:
            try:
                el = self.driver.find_element(by, sel)
                if el.is_displayed():
                    body = ""
                    try:
                        body = self.driver.find_element(By.TAG_NAME, "body").text
                    except Exception:
                        pass
                    self._click_element(el)
                    if body:
                        self.log(f"팝업 확인 클릭: {body[:80]}")
                    return body[:200] if body else "확인"
            except NoSuchElementException:
                continue
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
            new_handles = set(self.driver.window_handles) - before_handles
            if new_handles:
                return next(iter(new_handles))
            time.sleep(0.1)
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
        if popup_text and self._is_already_reported_alert(popup_text):
            self.log("이미 신고된 게시물 — 확인 후 다음 진행")
            return "already"

        if not self._select_cafe_illegal_reason_in_context():
            return "failed"
        self._cafe_fast_delay(0.05, 0.15)
        if not self._submit_cafe_report_in_context():
            return "failed"
        self._cafe_fast_delay(0.3, 0.6)
        popup_text = self._dismiss_cafe_popup(timeout=3)
        if popup_text:
            if self._is_already_reported_alert(popup_text):
                self.log("이미 신고됨 — 확인 후 다음 진행")
                return "already"
            if any(k in popup_text for k in ("불가", "제한")):
                self.log(f"신고 불가: {popup_text}")
                return "failed"
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
    ) -> dict:
        return {
            "account_id": account_id,
            "account_password": account_pw,
            "keyword": keyword,
            "url": url,
            "success": success,
            "status": status,
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
