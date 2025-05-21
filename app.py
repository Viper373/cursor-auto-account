import os
import random
import string
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv
from flask_cors import CORS
# 加载.env文件
load_dotenv()

# 导入自定义模块
from models import db
from auth import SECRET_KEY, TOKEN_EXPIRY_DAYS
import auth
from db_utils import init_db
from views.api import api_bp
import urllib.parse
# 创建并配置 Flask 应用
def create_app():
    app = Flask(__name__)

    # 从环境变量获取数据库配置
    app.config['DB_HOST'] = os.getenv('DB_HOST', 'localhost')
    app.config['DB_PORT'] = int(os.getenv('DB_PORT', '3306'))
    app.config['DB_USER'] = os.getenv('DB_USER', 'root')
    app.config['DB_PASSWORD'] = os.getenv('DB_PASSWORD', 'root')
    app.config['DB_NAME'] = os.getenv('DB_NAME', 'cursor_accounts')

    # 设置 SQLAlchemy 数据库 URI
    # 对密码进行URL编码，避免特殊字符（如@）造成解析问题
    encoded_password = urllib.parse.quote_plus(app.config["DB_PASSWORD"])
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{app.config["DB_USER"]}:{encoded_password}@{app.config["DB_HOST"]}:{app.config["DB_PORT"]}/{app.config["DB_NAME"]}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # JWT密钥
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', ''.join(random.choices(string.ascii_letters + string.digits, k=32)))
    # Token有效期（天）
    app.config['TOKEN_EXPIRY_DAYS'] = int(os.getenv('TOKEN_EXPIRY_DAYS', '30'))

    # 初始化数据库
    db.init_app(app)

    # 设置认证模块的密钥和过期时间 - 修复直接设置模块变量
    auth.SECRET_KEY = app.config['SECRET_KEY']
    auth.TOKEN_EXPIRY_DAYS = app.config['TOKEN_EXPIRY_DAYS']

    # 注册蓝图
    app.register_blueprint(api_bp)

    # 允许跨域（只允许你的前端域名，安全！）
    CORS(app, origins=["https://cursor-auto-account-web.vercel.app", "https://cursor.viper3.top"], supports_credentials=True)

    # 初始化数据库 (确保在Vercel环境下也会执行)
    with app.app_context(): # 确保在应用上下文中执行
        init_db(app)

    return app

app = create_app()

# 应用入口
if __name__ == '__main__':
    # 初始化数据库 # 已移至 create_app
    # init_db(app)

    # 获取环境变量中的主机和端口，默认为0.0.0.0:8001
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8001'))

    # 启动应用
    app.run(host=host, port=port, debug=(os.getenv('DEBUG', 'False').lower() == 'true'))