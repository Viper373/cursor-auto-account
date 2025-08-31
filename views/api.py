import logging
import time
import traceback
import threading
from functools import wraps
from flask import Blueprint, jsonify, request, current_app, Response, stream_with_context
import json
import queue
import threading
from sqlalchemy import func
from models import db, User, Account
from auth import token_required, admin_required, generate_token
from account_service import create_account_for_user, create_account_for_user_stream

# 创建蓝图
api_bp = Blueprint('api', __name__, url_prefix='/api')

# 设置日志
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 创建一个信号量用于限制并发请求
account_semaphore = threading.Semaphore(3)

# 限流装饰器
def limit_concurrency(semaphore):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 尝试获取信号量
            acquired = semaphore.acquire(blocking=False)
            if not acquired:
                # 如果没有获取到信号量，返回响应码 429 (Too Many Requests)
                logger.warning("并发请求数超过限制，拒绝处理请求")
                return jsonify({
                    'status': 'error',
                    'message': '服务器繁忙，请稍后再试'
                }), 429

            try:
                # 执行原函数
                return f(*args, **kwargs)
            finally:
                # 无论成功与否，释放信号量
                semaphore.release()
        return decorated_function
    return decorator

# 用户注册
@api_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.json

        if not data or not data.get('username') or not data.get('password'):
            return jsonify({
                'status': 'error',
                'message': '请提供用户名和密码'
            }), 400

        # 检查用户名是否已存在
        existing_user = User.query.filter_by(username=data['username']).first()
        if existing_user:
            return jsonify({
                'status': 'error',
                'message': '用户名已存在'
            }), 400

        # 创建新用户
        new_user = User(
            username=data['username'],
            password_hash=User.hash_password(data['password']),
            temp_email_address='zoowayss@mailto.plus',
            email=data.get('email'),
            created_at=int(time.time())
        )

        db.session.add(new_user)
        db.session.commit()

        # 生成token
        token = generate_token(new_user.id)

        return jsonify({
            'status': 'success',
            'message': '注册成功',
            'user': new_user.to_dict(),
            'token': token
        })

    except Exception as e:
        logger.error(f"注册失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 用户登录
@api_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.json

        if not data or not data.get('username') or not data.get('password'):
            return jsonify({
                'status': 'error',
                'message': '请提供用户名和密码'
            }), 400

        # 查找用户
        user = User.query.filter_by(username=data['username']).first()
        if not user or not user.verify_password(data['password']):
            return jsonify({
                'status': 'error',
                'message': '用户名或密码错误'
            }), 401

        # 更新最后登录时间
        user.last_login = int(time.time())
        db.session.commit()

        # 生成token
        token = generate_token(user.id)

        return jsonify({
            'status': 'success',
            'message': '登录成功',
            'user': user.to_dict(),
            'token': token
        })

    except Exception as e:
        logger.error(f"登录失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 获取用户信息
@api_bp.route('/user', methods=['GET'])
@token_required
def get_user_info():
    return jsonify({
        'status': 'success',
        'user': request.current_user.to_dict()
    })

# 退出登录
@api_bp.route('/logout', methods=['POST'])
@token_required
def logout():
    # 无需数据库操作，客户端清除token即可
    return jsonify({
        'status': 'success',
        'message': '已成功退出登录'
    })

# 获取一个可用账号 (已登录用户)
@api_bp.route('/account', methods=['GET'])
@token_required
@limit_concurrency(account_semaphore)
def get_account():
    try:
        logger.info(f"用户 {request.current_user.id} 请求获取账号")
        result = create_account_for_user(request.current_user)
        if result.get('status') == 'success':
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        logger.error(f"获取账号失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# 实时日志（SSE）获取新账号
@api_bp.route('/account/stream', methods=['GET'])
@token_required
@limit_concurrency(account_semaphore)
def get_account_stream():
    def sse_format(data: str, event: str = None):
        if event:
            return f"event: {event}\n" f"data: {data}\n\n"
        return f"data: {data}\n\n"

    user = request.current_user
    app_ctx = current_app._get_current_object()
    q: queue.Queue[tuple[str, str]] = queue.Queue()

    def worker():
        try:
            def cb(line: str):
                q.put(('log', line))
            # 推入 Flask 应用上下文，供数据库等使用
            with app_ctx.app_context():
                result = create_account_for_user_stream(user, cb)
            q.put(('done', json.dumps(result, ensure_ascii=False)))
        except Exception as e:
            q.put(('error', json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)))
        finally:
            q.put(('close', ''))

    threading.Thread(target=worker, daemon=True).start()

    @stream_with_context
    def generate():
        # 立即发送一条心跳/握手，确保连接建立并避免某些代理超时
        yield sse_format('连接已建立', 'log')
        while True:
            event, payload = q.get()
            if event == 'close':
                break
            yield sse_format(payload, event)

    headers = {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    }
    return Response(generate(), headers=headers)

# 获取用户的所有账号
@api_bp.route('/accounts', methods=['GET'])
@token_required
def get_user_accounts():
    try:
        user_id = request.current_user.id
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        # 查询用户的账号 - 只查询明确归属于该用户且未被删除的账号
        query = Account.query.filter_by(user_id=user_id, is_deleted=0).order_by(Account.create_time.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        accounts = [account.to_dict() for account in pagination.items]

        return jsonify({
            'status': 'success',
            'page': page,
            'per_page': per_page,
            'total': pagination.total,
            'total_pages': pagination.pages,
            'accounts': accounts
        })

    except Exception as e:
        logger.error(f"获取用户账号失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 用户账号统计（排除已删除，available 排除已过期）
@api_bp.route('/accounts/stats', methods=['GET'])
@token_required
def get_user_account_stats():
    try:
        user_id = request.current_user.id
        now_ts = int(time.time())

        base_q = Account.query.filter_by(user_id=user_id, is_deleted=0)
        total = base_q.count()
        used = base_q.filter(Account.is_used == 1).count()
        available = base_q.filter(Account.is_used == 0, Account.expire_time > now_ts).count()

        return jsonify({
            'status': 'success',
            'total': total,
            'used': used,
            'available': available
        })
    except Exception as e:
        logger.error(f"获取用户账号统计失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 修改账号使用状态
@api_bp.route('/account/<int:account_id>/status', methods=['PUT'])
@token_required
def update_account_status(account_id):
    try:
        # 获取请求数据
        data = request.json
        if data is None or 'is_used' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数'
            }), 400

        # 查找账号
        account = Account.query.get(account_id)
        if not account:
            return jsonify({
                'status': 'error',
                'message': f'账号 ID {account_id} 不存在'
            }), 404

        # 检查用户权限
        user = request.current_user

        # 严格检查账号所有权 - 只有明确归属于当前用户或管理员的账号才能修改
        # 不再自动归属无主账号
        if not hasattr(account, 'user_id') or account.user_id is None:
            if user.id == 1:  # 管理员可以处理无主账号
                try:
                    account.user_id = user.id  # 管理员可以认领无主账号
                except:
                    pass  # 如果列不存在，忽略错误
            else:
                return jsonify({
                    'status': 'error',
                    'message': '无权修改此账号'
                }), 403
        elif account.user_id != user.id and user.id != 1:
            return jsonify({
                'status': 'error',
                'message': '无权修改此账号'
                }), 403

        # 更新状态
        account.is_used = data['is_used']
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': '账号状态已更新',
            'account': account.to_dict()
        })

    except Exception as e:
        logger.error(f"更新账号状态失败: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# 管理员获取所有账号
@api_bp.route('/admin/accounts', methods=['GET'])
@admin_required
def admin_get_accounts():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        # 获取查询参数，是否包含已删除的账号
        show_deleted = request.args.get('show_deleted', 'false').lower() == 'true'

        # 构建查询
        query = Account.query

        # 如果不显示已删除账号，则添加过滤条件
        if not show_deleted:
            query = query.filter_by(is_deleted=0)

        # 计算总页数
        total_accounts = query.count()
        total_pages = (total_accounts + per_page - 1) // per_page

        # 获取当前页的账号数据，按照create_time倒序排列
        accounts = query.order_by(Account.create_time.desc()).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'status': 'success',
            'page': page,
            'per_page': per_page,
            'total': total_accounts,
            'total_pages': total_pages,
            'accounts': [account.to_dict() for account in accounts.items]
        })

    except Exception as e:
        logger.error(f"管理员获取所有账号失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 管理员获取所有用户
@api_bp.route('/admin/users', methods=['GET'])
@admin_required
def admin_get_users():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        # 查询用户 倒序排列
        query = User.query.order_by(User.id.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        users = [user.to_dict() for user in pagination.items]

        return jsonify({
            'status': 'success',
            'page': page,
            'per_page': per_page,
            'total': pagination.total,
            'total_pages': pagination.pages,
            'users': users
        })

    except Exception as e:
        logger.error(f"管理员获取所有用户失败: {traceback.format_exc()}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 逻辑删除账号
@api_bp.route('/account/<int:account_id>/delete', methods=['PUT'])
@token_required
def delete_account(account_id):
    try:
        # 查找账号
        account = Account.query.get(account_id)
        if not account:
            return jsonify({
                'status': 'error',
                'message': f'账号 ID {account_id} 不存在'
            }), 404

        # 检查用户权限
        user = request.current_user

        # 严格检查账号所有权 - 只有明确归属于当前用户或管理员的账号才能删除
        if not hasattr(account, 'user_id') or account.user_id is None:
            if user.id == 1:  # 管理员可以处理无主账号
                pass
            else:
                return jsonify({
                    'status': 'error',
                    'message': '无权删除此账号'
                }), 403
        elif account.user_id != user.id and user.id != 1:
            return jsonify({
                'status': 'error',
                'message': '无权删除此账号'
            }), 403

        # 更新删除状态
        account.is_deleted = 1
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': '账号已删除',
            'account': account.to_dict()
        })

    except Exception as e:
        logger.error(f"删除账号失败: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# 健康检查
@api_bp.route('/health', methods=['GET'])
def health_check():
    from datetime import datetime
    return jsonify({'status': 'ok', 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}), 200

@api_bp.route('/user/<int:user_id>', methods=['PUT'])
@token_required
def update_user(user_id):
    try:
        # 记录调试信息
        logger.info(f"更新用户请求 - 当前用户ID: {request.current_user.id}")

        # 检查权限
        if request.current_user.id != user_id and not request.current_user.is_admin:
            logger.warning(f"权限不足 - 当前用户ID: {request.current_user.id}, 目标用户ID: {user_id}")
            return jsonify({
                'status': 'error',
                'message': '无权修改其他用户信息'
            }), 403

        # 获取请求数据
        data = request.json
        if not data:
            logger.warning("缺少更新数据")
            return jsonify({
                'status': 'error',
                'message': '缺少更新数据'
            }), 400

        # 查找用户
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"用户不存在 - 用户ID: {user_id}")
            return jsonify({
                'status': 'error',
                'message': '用户不存在'
            }), 404

        # 更新用户信息
        if 'domain' in data:
            user.domain = data['domain']
        if 'temp_email_address' in data:
            if '@' in data['temp_email_address']:
                user.temp_email_address = data['temp_email_address']
            else:
                raise ValueError('临时邮箱地址格式错误 正确格式：zoowayss@mailto.plus')
        if 'email' in data:
            user.email = data['email']
        if 'password' in data:
            user.password_hash = User.hash_password(data['password'])

        db.session.commit()
        logger.info(f"用户信息更新成功 - 用户ID: {user_id}")

        return jsonify({
            'status': 'success',
            'message': '用户信息更新成功',
            'user': user.to_dict()
        })

    except Exception as e:
        logger.error(f"更新用户信息失败: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500