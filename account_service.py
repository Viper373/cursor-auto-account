import time
from sqlalchemy import text
import register as account_register
from models import db, Account
import logging


class _CallbackLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__(level=logging.INFO)
        self._callback = callback
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        self.setFormatter(formatter)

    def emit(self, record):
        try:
            msg = self.format(record)
            self._callback(msg)
        except Exception:
            pass

# 为用户创建账号
def create_account_for_user(current_user):
    try:
        # 生成随机名字和账号信息
        email_generator = account_register.EmailGenerator(domain=current_user.domain)
        account_info = email_generator.get_account_info()
        
        # 从返回的字典中获取信息
        email = account_info["email"]
        password = account_info["password"]
        first_name = account_info["first_name"]
        last_name = account_info["last_name"]
        
        # 检查邮箱是否已存在
        existing_account = Account.query.filter_by(email=email).first()
        if existing_account:
            return {'status': 'error', 'message': '该邮箱已被使用，请重试'}
        
        if current_user.temp_email_address:
            temp_email_address = current_user.temp_email_address
        else:
            temp_email_address = 'zoowayss@mailto.plus'
        
        # 注册账号
        registration = account_register.Register(first_name, last_name, email, password,temp_email_address)
        success = registration.register()
        
        if not success:
            return {'status': 'error', 'message': '注册失败，请稍后再试'}
        
        # 计算过期时间 (15天后)
        create_time = int(time.time())
        expire_time = create_time + (15 * 24 * 60 * 60)
        
        # 创建账号对象
        account = Account(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            create_time=create_time,
            expire_time=expire_time,
            user_id=current_user.id,
            is_used=0  # 标记为已使用
        )
        
        db.session.add(account)
        db.session.commit()
        return {
            'status': 'success',
            'message': '新账号已创建',
            'account': account.to_dict()
        }
    
    except Exception as e:
        return {'status': 'error', 'message': str(e)} 


# 为用户创建账号（带日志回调）
def create_account_for_user_stream(current_user, log_callback):
    """Same as create_account_for_user, but emits progress logs via log_callback(str)."""
    try:
        log_callback('初始化生成账号信息')
        email_generator = account_register.EmailGenerator(domain=current_user.domain)
        account_info = email_generator.get_account_info()

        email = account_info["email"]
        password = account_info["password"]
        first_name = account_info["first_name"]
        last_name = account_info["last_name"]

        # 唯一性检查
        if Account.query.filter_by(email=email).first():
            msg = '该邮箱已被使用，请重试'
            log_callback(msg)
            return {'status': 'error', 'message': msg}

        temp_email_address = current_user.temp_email_address or 'zoowayss@mailto.plus'

        # 捕获 register.py 内部日志
        root_logger = logging.getLogger()
        capture_handler = _CallbackLogHandler(log_callback)
        root_logger.addHandler(capture_handler)
        try:
            log_callback('开始注册账号')
            registration = account_register.Register(first_name, last_name, email, password, temp_email_address)
            success = registration.register()
        finally:
            root_logger.removeHandler(capture_handler)

        if not success:
            msg = '注册失败，请稍后再试'
            log_callback(msg)
            return {'status': 'error', 'message': msg}

        # 计算过期时间 (15天后)
        create_time = int(time.time())
        expire_time = create_time + (15 * 24 * 60 * 60)

        # 保存账号
        account = Account(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            create_time=create_time,
            expire_time=expire_time,
            user_id=current_user.id,
            is_used=0
        )

        db.session.add(account)
        db.session.commit()

        log_callback('账号已创建并写入数据库')
        return {
            'status': 'success',
            'message': '新账号已创建',
            'account': account.to_dict()
        }
    except Exception as e:
        msg = str(e)
        log_callback(f'异常：{msg}')
        return {'status': 'error', 'message': msg}