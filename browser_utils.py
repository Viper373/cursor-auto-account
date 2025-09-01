from DrissionPage import ChromiumOptions, Chromium
import sys
import os
import logging

class BrowserManager:
    def __init__(self):
        self.browser = None

    def init_browser(self, user_agent=None):
        """初始化浏览器"""
        co = self._get_browser_options(user_agent)
        self.browser = Chromium(co)
        return self.browser

    def _get_browser_options(self, user_agent=None):
        """获取浏览器配置"""
        co = ChromiumOptions()
        # 1) 浏览器可执行文件路径优先从环境变量读取
        #    支持 BROWSER_PATH（项目自定义）与 DP_BROWSER_PATH（DrissionPage 兼容）
        browser_path_env = os.getenv('BROWSER_PATH') or os.getenv('DP_BROWSER_PATH')
        # 2) 常见路径回退（apt / snap）
        common_paths = [
            '/usr/bin/google-chrome',
            '/usr/bin/chromium',
            '/snap/bin/chromium',
        ]
        browser_path = None
        for p in [browser_path_env, *common_paths]:
            if p and os.path.exists(p):
                browser_path = p
                break

        if browser_path:
            try:
                # DrissionPage 方式
                if hasattr(co, 'set_browser_path'):
                    co.set_browser_path(browser_path)
                # 兜底：设置环境变量供底层读取
                os.environ['DP_BROWSER_PATH'] = browser_path
                logging.info(f"Using browser at: {browser_path}")
            except Exception as e:
                logging.warning(f"设置浏览器路径失败: {e}")
        else:
            logging.warning("未检测到可用的浏览器可执行文件，请在 .env 中设置 BROWSER_PATH")
        try:
            extension_path = self._get_extension_path("turnstilePatch")
            co.add_extension(extension_path)
        except FileNotFoundError as e:
            logging.warning(f"警告: {e}")

        co.set_pref("credentials_enable_service", False)
        co.set_argument("--hide-crash-restore-bubble")
        co.set_argument("--remote-debugging-port=9222")
        co.set_argument("--remote-debugging-address=0.0.0.0")
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-gpu")
        co.set_argument("--disable-dev-shm-usage")
        if user_agent:
            co.set_user_agent(user_agent)

        co.headless()  # 生产环境使用无头模式

        return co

    def _get_extension_path(self,exname='turnstilePatch'):
        """获取插件路径"""
        root_dir = os.getcwd()
        extension_path = os.path.join(root_dir, exname)

        if hasattr(sys, "_MEIPASS"):
            extension_path = os.path.join(sys._MEIPASS, exname)

        if not os.path.exists(extension_path):
            raise FileNotFoundError(f"插件不存在: {extension_path}")

        return extension_path

    def quit(self):
        """关闭浏览器"""
        if self.browser:
            try:
                self.browser.quit()
            except:
                pass
