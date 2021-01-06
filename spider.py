import functools
import json
import logging
import os
import pickle
import random
import tempfile
import time
import webbrowser
from concurrent.futures import ProcessPoolExecutor

import requests
from bs4 import BeautifulSoup

from config import GlobalConfig
from logger import logger
from utils import parse_json


class Request:
    def __init__(self):
        self.session = requests.session()
        self.session.headers = self.headers
        self.cookies_path = "./.cookies"

    def load_cookies_from_local(self):
        if not os.path.exists(self.cookies_path):
            return False
        with open(self.cookies_path, "rb") as f:
            self.session.cookies.update(pickle.load(f))

    def save_cookies_to_local(self):
        with open(self.cookies_path, "wb") as f:
            pickle.dump(self.session.cookies, f)

    @property
    def headers(self):
        # yapf: disable
        return {
            "Referer": "https://passport.jd.com/new/login.asp",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_3) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/87.0.4280.88 Safari/537.36",
        }
        # yapf: enable


class QRCode:
    def __init__(self, request):
        self.request = request

    def login_by_qrcode(self):
        if self.validate_cookies():
            return

        if not self.open_qrcode():
            logger.warning("二维码下载失败")
            return

        timeout, interval = 180, 5
        for _ in range(int(timeout / interval)):
            ticket = self._get_qrcode_ticket()
            if ticket:
                logger.info("手机客户端确认成功")
                break
            time.sleep(interval)
        else:
            logger.warning("二维码已失效")
            return

        if not self._validate_qrcode_ticket(ticket):
            logger.error("二维码信息校验失败")
        else:
            logger.info("扫码登陆成功")

    def validate_cookies(self):
        url = "https://order.jd.com/center/list.action"
        params = {"rid": int(time.time() * 1000)}
        resp = self.request.session.get(
            url=url,
            params=params,
            allow_redirects=False,
        )
        return resp.status_code == requests.codes.ok

    def open_qrcode(self):
        url = "https://qr.m.jd.com/show"
        params = {
            "appid": 133,
            "size": 147,
            "t": int(time.time() * 1000),
        }
        resp = self.request.session.get(url=url, params=params)
        if not resp.status_code == requests.codes.ok:
            return False
        with tempfile.NamedTemporaryFile() as f:
            for chunk in resp.iter_content(chunk_size=1024):
                f.write(chunk)
            f.flush()
            webbrowser.open_new_tab("file://%s" % f.name)
            time.sleep(1)
        return True

    def _get_qrcode_ticket(self):
        url = "https://qr.m.jd.com/check"
        params = {
            "appid": 133,
            "callback": "jQuery%s" % random.randint(1000000, 9999999),
            "token": self.request.session.cookies.get("wlfstk_smdl"),
            "_": int(time.time() * 1000),
        }
        resp = self.request.session.get(url=url, params=params)
        resp_json = parse_json(resp.text)
        if resp_json["code"] == 200:
            return resp_json["ticket"]
        else:
            logger.info(resp_json["msg"])
        return None

    def _validate_qrcode_ticket(self, ticket):
        url = "https://passport.jd.com/uc/qrCodeTicketValidation"
        params = {"t": ticket}
        resp = self.request.session.get(url=url, params=params)
        return resp.json()["returnCode"] == 0


class Econnoisseur:
    def __init__(self):
        self.request = Request()
        self.request.load_cookies_from_local()

        self.qrcode = QRCode(self.request)

        self.sku_id = GlobalConfig.sku_id
        self.sku_num = GlobalConfig.sku_num
        self.password = GlobalConfig.password
        self.eid = GlobalConfig.eid
        self.fp = GlobalConfig.fp
        self.order_data = self._get_seckill_order_data()

    def authenticated(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self.qrcode.validate_cookies():
                self.qrcode.login_by_qrcode()
                self.request.save_cookies_to_local()
            return func(self, *args, **kwargs)

        return wrapper

    @authenticated
    def reserve(self):
        logger.info("开始预约")
        url = "https://yushou.jd.com/youshouinfo.action"
        self.request.session.headers["Referer"] = (
            "https://item.jd.com/%s.html" % self.sku_id
        )
        params = {
            "callback": "fetchJSON",
            "sku": self.sku_id,
            "_": int(time.time() * 1000),
        }
        resp = self.request.session.get(url=url, params=params)
        resp_json = parse_json(resp.text)
        resp = self.request.session.get(url="https:" + resp_json["url"])
        soup = BeautifulSoup(resp.text, "html.parser")
        resp_result = soup.select(".bd-right-result")[0].text.strip()
        logger.info(resp_result)

    @authenticated
    def seckill_by_pool(self, count=GlobalConfig.process):
        with ProcessPoolExecutor(count) as pool:
            for i in range(count):
                pool.submit(self.seckill)

    @authenticated
    def seckill(self):
        self.request_seckill_url()
        logger.info("进入秒杀抢购循环")
        while True:
            interval = random.randint(100, 300) / 1000
            try:
                self.request_seckill_checkout_url()
                self.submit_seckill_order()
            except Exception as e:
                logging.exception(e)
                logger.warning("抢购异常，%s秒后自动重试" % interval)
            time.sleep(interval)

    def request_seckill_url(self):
        seckill_url = self.get_seckill_url()
        # yapf: disable
        headers = {
            "Host": "marathon.jd.com",
            "Referer": "https://item.jd.com/%s.html" % self.sku_id,
        }
        # yapf: enable
        logger.info("模拟访问抢购页面")
        self.request.session.get(
            url=seckill_url,
            headers=headers,
            allow_redirects=False,
        )

    def get_seckill_url(self):
        logger.info("尝试获取抢购页面链接")
        url = "https://itemko.jd.com/itemShowBtn"
        params = {
            "callback": "jQuery%s" % random.randint(1000000, 9999999),
            "skuId": self.sku_id,
            "from": "pc",
            "_": int(time.time() * 1000),
        }
        headers = {
            "Host": "itemko.jd.com",
            "Referer": "https://item.jd.com/%s.html" % self.sku_id,
        }
        while True:
            resp = self.request.session.get(
                url=url,
                headers=headers,
                params=params,
            )
            resp_json = parse_json(resp.text)
            if not resp_json.get("url"):
                interval = random.randint(100, 300) / 1000
                # yapf: disable
                logger.warning(
                    "抢购页面链接获取失败，%s秒后自动重试" % interval
                )
                # yapf: enable
                time.sleep(interval)
                continue
            router_url = "https:" + resp_json.get("url")
            seckill_url = router_url.replace("divide", "marathon").replace(
                "user_routing", "captcha.html"
            )
            logger.info("抢购页面链接获取成功：%s" % seckill_url)
            return seckill_url

    def request_seckill_checkout_url(self):
        url = "https://marathon.jd.com/seckill/seckill.action"
        headers = {
            "Host": "marathon.jd.com",
            "Referer": "https://item.jd.com/%s.html" % self.sku_id,
        }
        params = {
            "skuId": self.sku_id,
            "num": self.sku_num,
            "rid": int(time.time()),
        }
        self.request.session.get(
            url=url,
            headers=headers,
            params=params,
            allow_redirects=False,
        )

    def submit_seckill_order(self):
        url = "https://marathon.jd.com/seckillnew/orderService/pc/submitOrder.action"
        params = {"skuId": self.sku_id}
        # yapf: disable
        headers = {
            "Host": "marathon.jd.com",
            "Referer": (
                "https://marathon.jd.com/seckill/seckill.action"
                "?skuId=%s&num=%s&rid=%s" %
                (self.sku_id, self.sku_num, int(time.time()))
            ),
        }
        # yapf: enable
        resp = self.request.session.post(
            url=url,
            headers=headers,
            params=params,
            data=self.order_data,
        )
        resp_json = parse_json(resp.text)
        if resp_json["success"]:
            logger.info("抢购成功，PC端付款链接：%s" % resp_json["pcUrl"])
        else:
            logger.info(
                "提交订单失败，接口返回：%s(%s)" %
                (resp_json["errorMessage"], resp_json["resultCode"])
            )

    def _get_seckill_order_data(self):
        seckill_order_info = self._get_order_info()
        address = seckill_order_info["addressList"][0]
        invoice = seckill_order_info.get("invoiceInfo", {})
        token = seckill_order_info["token"]
        data = {
            "skuId": self.sku_id,
            "num": self.sku_num,
            "addressId": address["id"],
            "yuShou": "true",
            "isModifyAddress": "false",
            "name": address["name"],
            "provinceId": address["provinceId"],
            "cityId": address["cityId"],
            "countyId": address["countyId"],
            "townId": address["townId"],
            "addressDetail": address["addressDetail"],
            "mobile": address["mobile"],
            "mobileKey": address["mobileKey"],
            "email": address["email"],
            "postCode": "",
            "invoiceTitle": invoice.get("invoiceTitle", -1),
            "invoiceCompanyName": "",
            "invoiceContent": invoice.get("invoiceContentType", 1),
            "invoiceTaxpayerNO": "",
            "invoiceEmail": "",
            "invoicePhone": invoice.get("invoicePhone", ""),
            "invoicePhoneKey": invoice.get("invoicePhoneKey", ""),
            "invoice": "true" if invoice else "false",
            "password": self.password,
            "codTimeType": 3,
            "paymentType": 4,
            "areaCode": "",
            "overseas": 0,
            "phone": "",
            "eid": self.eid,
            "fp": self.fp,
            "token": token,
            "pru": "",
        }
        logger.info("订单信息获取成功：%s" % data)
        return data

    @authenticated
    def _get_order_info(self):
        url = "https://marathon.jd.com/seckillnew/orderService/pc/init.action"
        data = {
            "sku": self.sku_id,
            "num": self.sku_num,
            "isModifyAddress": False,
        }
        # yapf: disable
        headers = {
            "Host": "marathon.jd.com",
            "Referer": (
                "https://marathon.jd.com/seckill/seckill.action"
                "?skuId=%s&num=%s&rid=%s" %
                (self.sku_id, self.sku_num, int(time.time()))
            ),
        }
        # yapf: enable
        resp = self.request.session.post(
            url=url,
            headers=headers,
            data=data,
        )
        if resp.text == "null":
            logger.error("订单基本信息获取失败，接口返回null")
        return json.loads(resp.text)
