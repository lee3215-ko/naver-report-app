import json
import os
import random
import re
import time
import base64
from datetime import datetime
from urllib.parse import quote

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
        self.client = self._openai_client()

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

    def login(self, naver_id: str, naver_pw: str) -> tuple[bool, str]:
        login_url = (
            "https://nid.naver.com/nidlogin.login?url="
            + quote(self.INQUIRY_FORM_URL, safe="")
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

    def fill_form(self, site: str, report_type: str, content: str) -> bool:
        """문의 작성 폼을 채웁니다."""
        try:
            self._go_to_inquiry_page()
            wait = self._wait(15)
            self._human_delay(0.8, 1.5)

            url_input = wait.until(EC.presence_of_element_located((By.ID, "requiredUrl1")))
            self._type_into_element(url_input, site, label="게시물 URL")
            self.log(f"게시물 URL 입력: {site}")
            self._human_delay(0.4, 1.0)

            try:
                url2 = self.driver.find_element(By.ID, "requiredUrl2")
                if url2.is_displayed():
                    self._type_into_element(url2, site, label="검색결과 URL")
                    self.log(f"검색결과 URL 입력: {site}")
                    self._human_delay(0.4, 1.0)
            except NoSuchElementException:
                pass

            mo_texts = self.driver.find_elements(By.ID, "moText1CA")
            if len(mo_texts) >= 1:
                self._type_into_element(mo_texts[0], report_type, label="유형 키워드")
                self.log(f"유형(키워드) 입력: {report_type}")
                self._human_delay(0.3, 0.8)
            if len(mo_texts) >= 2:
                self._type_into_element(mo_texts[1], site, label="사이트 키워드")
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
            item = {
                "account_id": naver_id,
                "account_password": naver_pw,
                "site": task.get("site", ""),
                "report_type": task.get("report_type", ""),
                "original": task.get("template", ""),
                "rewritten": "보호조치 해제 필요",
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "success": False,
                "status": "protected",
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
                site = task.get("site", "")
                report_type = task.get("report_type", "")
                template = task.get("template", "")

                self._human_delay(1.0, 2.5)
                rewritten = self._rewrite(template, naver_id, site, report_type)
                self.log(f"[{naver_id}] {idx + 1}/{len(tasks)} 리라이트 완료 ({len(rewritten)}자)")
                self._human_delay(0.8, 1.8)

                success = self.fill_form(site, report_type, rewritten)
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
                })
                if self.result_callback:
                    self.result_callback(results[-1])
                if self.progress_callback:
                    self.progress_callback(1)
                self._human_delay(2.0, 4.5)
        finally:
            self.quit_driver()
        return results
