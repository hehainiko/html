#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file
import pymysql
import datetime
import re
from functools import wraps
from io import BytesIO
# 将报表库改为函数内惰性导入，避免未安装时报错

app = Flask(__name__)
app.secret_key = 'sports_meet_secret_key_2024'

# 登录与权限控制
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('username'):
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('username'):
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        if session.get('role') != '管理员':
            flash('权限不足，仅管理员可访问', 'error')
            return redirect(url_for('query'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'error')
            return redirect(url_for('login'))

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, password, role FROM users WHERE username = %s
            """, (username,))
            row = cursor.fetchone()
            if not row:
                flash('用户不存在', 'error')
                return render_template('login.html')
            if row[1] != password:
                flash('密码错误', 'error')
                return render_template('login.html')
            session['username'] = row[0]
            session['role'] = row[2]
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'登录失败：{e}', 'error')
            return render_template('login.html')
        finally:
            conn.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'success')
    return redirect(url_for('index'))

# 数据库连接配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'database': 'sports_meet_se',
    'user': 'root',
    'password': '123456',
    'charset': 'utf8mb4'
}

def get_db_connection():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset']
        )
        return conn
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return None

def ensure_schema():
    """初始化/迁移数据库结构以支持成员报名与成绩录入"""
    conn = get_db_connection()
    if not conn:
        print('ensure_schema: 数据库连接失败，跳过初始化')
        return
    try:
        cursor = conn.cursor()
        # 创建 registration_members 表（报名成员映射）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS registration_members (
              id INT(11) NOT NULL AUTO_INCREMENT,
              registration_id INT(11) NOT NULL,
              member_id INT(11) NOT NULL,
              check_in_time DATETIME NULL DEFAULT NULL,
              created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id) USING BTREE,
              UNIQUE KEY uniq_reg_member (registration_id, member_id),
              KEY idx_rm_registration (registration_id),
              KEY idx_rm_member (member_id),
              CONSTRAINT fk_rm_registration FOREIGN KEY (registration_id) REFERENCES registrations (id) ON DELETE CASCADE ON UPDATE CASCADE,
              CONSTRAINT fk_rm_member FOREIGN KEY (member_id) REFERENCES team_members (id) ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=Dynamic
            """
        )

        # 为 scores 增加 member_id 列（如不存在）
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_schema=%s AND table_name='scores' AND column_name='member_id'
            """,
            (DB_CONFIG['database'],)
        )
        has_member_id = cursor.fetchone()[0] > 0
        if not has_member_id:
            cursor.execute(
                """
                ALTER TABLE scores 
                ADD COLUMN member_id INT(11) NULL,
                ADD KEY idx_scores_member (member_id),
                ADD CONSTRAINT fk_scores_member FOREIGN KEY (member_id) REFERENCES team_members (id) ON DELETE SET NULL ON UPDATE CASCADE
                """
            )

        # 为 scores 增加唯一索引，限制同一报名+成员+赛程只能录入一次
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.statistics 
            WHERE table_schema=%s AND table_name='scores' AND index_name='uniq_score_once'
            """,
            (DB_CONFIG['database'],)
        )
        has_unique = cursor.fetchone()[0] > 0
        if not has_unique:
            cursor.execute(
                """
                ALTER TABLE scores
                ADD UNIQUE KEY uniq_score_once (registration_id, member_id, stage)
                """
            )

        conn.commit()
    except Exception as e:
        print(f"ensure_schema: 初始化/迁移失败: {e}")
    finally:
        conn.close()

def generate_registration_number(class_name):
    """生成参赛编号：年份+班级+流水号"""
    year = datetime.datetime.now().year
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        # 查询当前班级已有的编号数量
        cursor.execute("""
            SELECT COUNT(*) FROM athletes 
            WHERE class_name = %s AND registration_number LIKE %s
        """, (class_name, f"{year}-{class_name}-%"))
        
        count = cursor.fetchone()[0]
        sequence = str(count + 1).zfill(3)  # 3位流水号
        registration_number = f"{year}-{class_name}-{sequence}"
        
        return registration_number
    except Exception as e:
        print(f"生成编号失败: {e}")
        return None
    finally:
        conn.close()

def generate_team_registration_number(school_name):
    """生成代表队编号：年份+学校+流水号"""
    year = datetime.datetime.now().year
    conn = get_db_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM teams 
            WHERE school_name = %s AND registration_number LIKE %s
            """,
            (school_name, f"{year}-{school_name}-%")
        )

        count = cursor.fetchone()[0]
        sequence = str(count + 1).zfill(3)
        registration_number = f"{year}-{school_name}-{sequence}"

        return registration_number
    except Exception as e:
        print(f"生成代表队编号失败: {e}")
        return None
    finally:
        conn.close()

def check_registration_limits(athlete_id, event_id):
    """检查报名限制"""
    conn = get_db_connection()
    if not conn:
        return False, "数据库连接失败"
    
    try:
        cursor = conn.cursor()
        
        # 检查该运动员已报名项目数量（最多3项）
        cursor.execute("""
            SELECT COUNT(*) FROM registrations 
            WHERE athlete_id = %s AND status != '弃权'
        """, (athlete_id,))
        athlete_events = cursor.fetchone()[0]
        
        if athlete_events >= 3:
            return False, "每人最多只能报名3个项目"
        
        # 获取运动员班级和项目信息
        cursor.execute("""
            SELECT a.class_name, e.event_name FROM athletes a, events e
            WHERE a.id = %s AND e.id = %s
        """, (athlete_id, event_id))
        result = cursor.fetchone()
        if not result:
            return False, "运动员或项目不存在"
        
        class_name, event_name = result
        
        # 检查该班级该项目已报名人数（最多5人）
        cursor.execute("""
            SELECT COUNT(*) FROM registrations r
            JOIN athletes a ON r.athlete_id = a.id
            WHERE a.class_name = %s AND r.event_id = %s AND r.status != '弃权'
        """, (class_name, event_id))
        class_event_count = cursor.fetchone()[0]
        
        if class_event_count >= 5:
            return False, f"每个班级每项目最多只能报5人，{class_name}的{event_name}项目已满"
        
        return True, "可以报名"
        
    except Exception as e:
        print(f"检查报名限制失败: {e}")
        return False, f"检查失败: {e}"
    finally:
        conn.close()

def auto_assign_referee(event_id):
    """自动分配裁判员"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        # 获取项目要求的裁判职称
        cursor.execute("SELECT referee_requirement FROM events WHERE id = %s", (event_id,))
        requirement = cursor.fetchone()
        if not requirement:
            return None
        
        required_title = requirement[0]
        
        # 查找符合要求的裁判员（优先选择工作量少的）
        cursor.execute("""
            SELECT r.id FROM referees r
            LEFT JOIN registrations reg ON r.id = reg.referee_id
            WHERE r.title = %s
            GROUP BY r.id
            ORDER BY COUNT(reg.id) ASC
            LIMIT 1
        """, (required_title,))
        
        referee = cursor.fetchone()
        return referee[0] if referee else None
        
    except Exception as e:
        print(f"自动分配裁判失败: {e}")
        return None
    finally:
        conn.close()

@app.route('/')
def index():
    """首页"""
    return render_template('index.html')

@app.route('/team_register', methods=['GET', 'POST'])
@admin_required
def team_register():
    """代表队报名"""
    if request.method == 'POST':
        school_name = request.form['school_name']
        team_name = request.form['team_name']
        leader_name = request.form.get('leader_name')
        leader_phone = request.form.get('leader_phone')

        # 生成代表队编号
        registration_number = generate_team_registration_number(school_name)
        if not registration_number:
            flash('生成代表队编号失败', 'error')
            return redirect(url_for('team_register'))

        # 插入代表队信息
        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'error')
            return redirect(url_for('team_register'))

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO teams (school_name, team_name, registration_number)
                VALUES (%s, %s, %s)
                """,
                (school_name, team_name, registration_number)
            )
            team_id = cursor.lastrowid

            # 可选：插入领队信息
            if leader_name:
                cursor.execute(
                    """
                    INSERT INTO team_members (team_id, member_name, role, phone)
                    VALUES (%s, %s, '领队', %s)
                    """,
                    (team_id, leader_name, leader_phone)
                )

            conn.commit()
            flash(f'代表队注册成功！编号：{registration_number}', 'success')

        except pymysql.err.IntegrityError:
            flash('代表队信息重复或编号冲突，请检查输入', 'error')
        except Exception as e:
            flash(f'注册失败：{e}', 'error')
        finally:
            conn.close()

        # 注册成功后跳转到对应代表队的成员管理页
        return redirect(url_for('team_members', team_id=team_id))

    return render_template('team_register.html')

# 团队化改造：移除裁判员报名路由

@app.route('/event_register', methods=['GET', 'POST'])
@admin_required
def event_register():
    """项目报名（选择代表队成员）"""
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'error')
        return redirect(url_for('index'))

    # 获取代表队和项目列表
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, school_name, team_name, registration_number FROM teams ORDER BY school_name, team_name")
        teams = cursor.fetchall()

        cursor.execute("SELECT id, event_name, event_type FROM events ORDER BY event_type, event_name")
        events = cursor.fetchall()

    except Exception as e:
        flash(f'数据加载失败：{e}', 'error')
        return redirect(url_for('index'))
    finally:
        conn.close()

    if request.method == 'POST':
        team_id = request.form['team_id']
        event_id = request.form['event_id']
        member_id = request.form.get('member_id')

        if not member_id:
            flash('请选择成员后再报名', 'error')
            return render_template('event_register.html', teams=teams, events=events)

        conn = get_db_connection()
        if not conn:
            flash('数据库连接失败', 'error')
            return render_template('event_register.html', teams=teams, events=events)

        try:
            cursor = conn.cursor()
            # 确保存在团队-项目报名记录
            cursor.execute("SELECT id FROM registrations WHERE team_id=%s AND event_id=%s", (team_id, event_id))
            row = cursor.fetchone()
            if row:
                registration_id = row[0]
            else:
                cursor.execute("INSERT INTO registrations (team_id, event_id) VALUES (%s, %s)", (team_id, event_id))
                registration_id = cursor.lastrowid

            # 校验项目总报名人数上限（最多8人）
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM registration_members rm
                JOIN registrations r ON rm.registration_id = r.id
                WHERE r.event_id = %s
                """,
                (event_id,)
            )
            total_count = cursor.fetchone()[0]
            if total_count >= 8:
                flash('该项目报名人数已满（最多8人）', 'error')
                return render_template('event_register.html', teams=teams, events=events)

            # 插入报名成员，避免重复
            cursor.execute(
                """
                SELECT COUNT(*) FROM registration_members WHERE registration_id=%s AND member_id=%s
                """,
                (registration_id, member_id)
            )
            exists = cursor.fetchone()[0] > 0
            if exists:
                flash('该成员已报名此项目', 'error')
            else:
                cursor.execute(
                    """
                    INSERT INTO registration_members (registration_id, member_id) VALUES (%s, %s)
                    """,
                    (registration_id, member_id)
                )
                conn.commit()
                flash('项目报名成功！', 'success')

        except Exception as e:
            flash(f'报名失败：{e}', 'error')
        finally:
            conn.close()

    return render_template('event_register.html', teams=teams, events=events)

# 成员管理入口与页面
@app.route('/members')
@admin_required
def members():
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'error')
        return redirect(url_for('index'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, school_name, team_name, registration_number FROM teams ORDER BY school_name, team_name")
        teams = cursor.fetchall()
        return render_template('members.html', teams=teams)
    except Exception as e:
        flash(f'数据加载失败：{e}', 'error')
        return redirect(url_for('index'))
    finally:
        conn.close()

@app.route('/team/<int:team_id>/members', methods=['GET', 'POST'])
@admin_required
def team_members(team_id):
    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'error')
        return redirect(url_for('members'))
    try:
        cursor = conn.cursor()
        if request.method == 'POST':
            member_name = request.form['member_name']
            phone = request.form.get('phone')
            student_id = request.form.get('student_id')
            role = request.form.get('role', '队员')
            cursor.execute(
                """
                INSERT INTO team_members (team_id, member_name, role, phone, student_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (team_id, member_name, role, phone, student_id)
            )
            conn.commit()
            flash('成员添加成功！', 'success')

        cursor.execute("SELECT school_name, team_name FROM teams WHERE id=%s", (team_id,))
        team = cursor.fetchone()
        cursor.execute("SELECT id, member_name, role, phone, student_id FROM team_members WHERE team_id=%s ORDER BY role, member_name", (team_id,))
        members = cursor.fetchall()
        return render_template('team_members.html', team=team, team_id=team_id, members=members)
    except Exception as e:
        flash(f'成员管理失败：{e}', 'error')
        return redirect(url_for('members'))
    finally:
        conn.close()

# 团队成员查询API（用于项目报名动态加载）
@app.route('/api/team_members/<int:team_id>')
def api_team_members(team_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, member_name FROM team_members WHERE team_id=%s ORDER BY member_name", (team_id,))
        data = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'查询失败：{e}'})
    finally:
        conn.close()

# 报名成员查询API（用于成绩录入按报名成员选择）
@app.route('/api/registration_members/<int:registration_id>')
def api_registration_members(registration_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tm.id, tm.member_name
            FROM registration_members rm
            JOIN team_members tm ON rm.member_id = tm.id
            WHERE rm.registration_id=%s
            ORDER BY tm.member_name
            """,
            (registration_id,)
        )
        data = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'查询失败：{e}'})
    finally:
        conn.close()

@app.route('/score_input', methods=['GET', 'POST'])
@admin_required
def score_input():
    """成绩录入"""
    if request.method == 'POST':
        action = request.form.get('action', 'score')
        
        if action == 'checkin':
            # 检录功能
            registration_id = request.form['registration_id']
            conn = get_db_connection()
            if not conn:
                flash('数据库连接失败', 'error')
                return redirect(url_for('score_input'))
            
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE registrations SET status = '已检录', check_in_time = NOW() 
                    WHERE id = %s
                """, (registration_id,))
                conn.commit()
                flash('检录成功！', 'success')
            except Exception as e:
                flash(f'检录失败：{e}', 'error')
            finally:
                conn.close()
                
        else:
            # 成绩录入
            registration_id = request.form['registration_id']
            member_id = request.form.get('member_id')
            if not member_id:
                flash('请先选择该报名记录的成员', 'error')
                return redirect(url_for('score_input'))
            score_value = float(request.form['score_value'])
            score_unit = request.form['score_unit']
            recorded_by = request.form.get('recorded_by', '系统')
            stage = request.form.get('stage', '决赛')
            
            conn = get_db_connection()
            if not conn:
                flash('数据库连接失败', 'error')
                return redirect(url_for('score_input'))
            
            try:
                cursor = conn.cursor()

                # 录入前校验：同一成员在同一赛程同一项目仅允许一次成绩
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM scores 
                    WHERE registration_id=%s AND member_id=%s AND stage=%s
                    """,
                    (registration_id, member_id, stage)
                )
                exists_cnt = cursor.fetchone()[0]
                if exists_cnt > 0:
                    flash('该成员在该赛程该项目已录入成绩，禁止重复录入', 'error')
                    return redirect(url_for('score_input'))
                
                # 插入成绩（包含赛程）
                cursor.execute(
                    """
                    INSERT INTO scores (registration_id, member_id, score_value, score_unit, recorded_by, stage)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (registration_id, member_id, score_value, score_unit, recorded_by, stage)
                )
                
                # 更新报名状态为已参赛
                cursor.execute("""
                    UPDATE registrations SET status = '已参赛' WHERE id = %s
                """, (registration_id,))
                
                conn.commit()
                flash('成绩录入成功！', 'success')
                
            except Exception as e:
                flash(f'成绩录入失败：{e}', 'error')
            finally:
                conn.close()
            
        return redirect(url_for('score_input'))
    
    # 获取报名记录（允许多阶段录入，不再排除已有成绩）
    conn = get_db_connection()
    if not conn:
        return render_template('score_input.html', registrations=[])
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.id, t.school_name, t.team_name, e.event_name, e.event_type
            FROM registrations r
            JOIN teams t ON r.team_id = t.id
            JOIN events e ON r.event_id = e.id
            WHERE r.status IN ('已报名', '已检录', '已参赛')
            ORDER BY e.event_name, t.school_name, t.team_name
        """)
        registrations = cursor.fetchall()
        
    except Exception as e:
        flash(f'数据加载失败：{e}', 'error')
        registrations = []
    finally:
        conn.close()
    
    return render_template('score_input.html', registrations=registrations)

@app.route('/query')
def query():
    """查询统计"""
    return render_template('query.html')

@app.route('/api/calculate_rankings/<int:event_id>')
@admin_required
def calculate_rankings(event_id):
    """计算某项目的排名"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    
    try:
        cursor = conn.cursor()
        
        # 获取项目类型
        cursor.execute("SELECT event_type FROM events WHERE id = %s", (event_id,))
        event_type = cursor.fetchone()[0]
        
        # 根据项目类型确定排序方式
        order_by = "ASC" if event_type == "径赛" else "DESC"  # 径赛时间升序，田赛距离降序
        
        # 获取该项目所有成绩并排序
        cursor.execute(f"""
            SELECT s.id, s.score_value, r.id as reg_id
            FROM scores s
            JOIN registrations r ON s.registration_id = r.id
            WHERE r.event_id = %s AND s.stage = '决赛'
            ORDER BY s.score_value {order_by}
        """, (event_id,))
        
        scores = cursor.fetchall()
        
        # 更新排名和得分
        for idx, score in enumerate(scores):
            ranking = idx + 1
            # 得分规则：第1名5分，第2名3分，第3名1分
            points = 5 if ranking == 1 else (3 if ranking == 2 else (1 if ranking == 3 else 0))
            
            cursor.execute("""
                UPDATE scores SET ranking = %s, points = %s WHERE id = %s
            """, (ranking, points, score[0]))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'排名计算完成，共{len(scores)}条记录'})
        
    except Exception as e:
        return jsonify({'error': f'计算排名失败：{e}'})
    finally:
        conn.close()

@app.route('/api/registrations')
def api_registrations():
    """获取参赛名单API"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.id, e.event_name, t.school_name, t.team_name, tm.member_name, r.status
            FROM registrations r
            JOIN teams t ON r.team_id = t.id
            JOIN events e ON r.event_id = e.id
            LEFT JOIN registration_members rm ON rm.registration_id = r.id
            LEFT JOIN team_members tm ON rm.member_id = tm.id
            ORDER BY e.event_name, t.school_name, t.team_name, tm.member_name
            """
        )
        
        registrations = []
        for row in cursor.fetchall():
            registrations.append({
                'id': row[0],
                'event_name': row[1],
                'school_name': row[2],
                'team_name': row[3],
                'member_name': row[4],
                'status': row[5]
            })
        
        return jsonify(registrations)
        
    except Exception as e:
        return jsonify({'error': f'查询失败：{e}'})
    finally:
        conn.close()

@app.route('/api/scores')
def api_scores():
    """获取成绩排名API"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.id, e.event_name, t.school_name, t.team_name,
                   tm.member_name,
                   s.score_value, s.score_unit, s.ranking
            FROM scores s
            JOIN registrations r ON s.registration_id = r.id
            JOIN teams t ON r.team_id = t.id
            JOIN events e ON r.event_id = e.id
            LEFT JOIN team_members tm ON s.member_id = tm.id
            WHERE s.stage = '决赛'
            ORDER BY e.event_name, s.ranking
            """
        )
        
        scores = []
        for row in cursor.fetchall():
            scores.append({
                'id': row[0],
                'event_name': row[1],
                'school_name': row[2],
                'team_name': row[3],
                'member_name': row[4],
                'score_value': row[5],
                'score_unit': row[6],
                'ranking': row[7]
            })
        
        return jsonify(scores)
        
    except Exception as e:
        return jsonify({'error': f'查询失败：{e}'})
    finally:
        conn.close()

@app.route('/api/class_rankings')
def api_class_rankings():
    """获取班级总分排名API"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.class_name,
                   SUM(s.points) as total_points,
                   COUNT(DISTINCT a.id) as athlete_count,
                   SUM(CASE WHEN s.ranking <= 3 THEN 1 ELSE 0 END) as award_count
            FROM athletes a
            JOIN registrations r ON a.id = r.athlete_id
            LEFT JOIN scores s ON r.id = s.registration_id AND s.stage = '决赛'
            GROUP BY a.class_name
            ORDER BY total_points DESC
        """)
        
        rankings = []
        for row in cursor.fetchall():
            rankings.append({
                'class_name': row[0],
                'total_points': row[1] or 0,
                'athlete_count': row[2],
                'award_count': row[3]
            })
        
        return jsonify(rankings)
        
    except Exception as e:
        return jsonify({'error': f'查询失败：{e}'})
    finally:
        conn.close()

@app.route('/api/calculate_all_rankings', methods=['POST'])
@admin_required
def calculate_all_rankings():
    """计算所有项目的排名"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': '数据库连接失败'})
    
    try:
        cursor = conn.cursor()
        
        # 获取所有有成绩的项目
        cursor.execute("""
            SELECT DISTINCT e.id, e.event_type 
            FROM events e
            JOIN registrations r ON e.id = r.event_id
            JOIN scores s ON r.id = s.registration_id AND s.stage = '决赛'
        """)
        
        events = cursor.fetchall()
        total_updated = 0
        
        for event in events:
            event_id, event_type = event
            
            # 根据项目类型确定排序方式
            order_by = "ASC" if event_type == "径赛" else "DESC"
            
            # 获取该项目所有成绩并排序
            cursor.execute(f"""
                SELECT s.id, s.score_value
                FROM scores s
                JOIN registrations r ON s.registration_id = r.id
                WHERE r.event_id = %s AND s.stage = '决赛'
                ORDER BY s.score_value {order_by}
            """, (event_id,))
            
            scores = cursor.fetchall()
            
            # 更新排名和得分
            for idx, score in enumerate(scores):
                ranking = idx + 1
                points = 5 if ranking == 1 else (3 if ranking == 2 else (1 if ranking == 3 else 0))
                
                cursor.execute("""
                    UPDATE scores SET ranking = %s, points = %s WHERE id = %s
                """, (ranking, points, score[0]))
                total_updated += 1
        
        conn.commit()
        return jsonify({'success': True, 'message': f'所有排名计算完成，共更新{total_updated}条记录'})
        
    except Exception as e:
        return jsonify({'error': f'计算排名失败：{e}'})
    finally:
        conn.close()

@app.route('/api/export/participants_pdf', methods=['GET'])
@admin_required
def export_participants_pdf():
    """导出参赛名单PDF（全部项目）"""
    # 惰性导入报表库，避免服务启动阶段依赖缺失
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.pagesizes import A4
    # 初始化PDF
    buf = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setFont('STSong-Light', 16)
    c.drawString(50, height - 50, '参赛名单（全部项目）')
    c.setFont('STSong-Light', 10)
    c.drawString(50, height - 70, f"导出时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 表头
    y = height - 100
    c.setFont('STSong-Light', 12)

    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'error')
        return redirect(url_for('query'))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.event_name,
                   tm.member_name,
                   t.school_name,
                   t.team_name,
                   t.registration_number,
                   r.status
            FROM registrations r
            JOIN teams t ON r.team_id = t.id
            JOIN events e ON r.event_id = e.id
            LEFT JOIN registration_members rm ON rm.registration_id = r.id
            LEFT JOIN team_members tm ON rm.member_id = tm.id
            ORDER BY e.event_name, t.school_name, tm.member_name
            """
        )
        rows = cursor.fetchall()

        # 按项目分组打印
        last_event = None
        seq = 0
        for row in rows:
            event_name, member_name, school_name, team_name, reg_no, status = row
            if event_name != last_event:
                # 新项目标题
                if last_event is not None:
                    y -= 10
                c.setFont('STSong-Light', 14)
                c.drawString(50, y, f"项目：{event_name}")
                y -= 20
                c.setFont('STSong-Light', 12)
                c.drawString(50, y, '序号')
                c.drawString(90, y, '成员')
                c.drawString(170, y, '学校')
                c.drawString(260, y, '队伍编号')
                c.drawString(370, y, '代表队')
                c.drawString(470, y, '状态')
                y -= 16
                last_event = event_name
                seq = 0

            # 页底处理
            if y < 60:
                c.showPage()
                c.setFont('STSong-Light', 12)
                y = height - 60

            seq += 1
            c.drawString(50, y, str(seq))
            c.drawString(90, y, member_name or '')
            c.drawString(170, y, school_name or '')
            c.drawString(260, y, reg_no or '')
            c.drawString(370, y, team_name or '')
            c.drawString(470, y, status or '')
            y -= 16

        c.save()
        buf.seek(0)
        filename = f"参赛名单_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'导出失败：{e}', 'error')
        return redirect(url_for('query'))
    finally:
        conn.close()

@app.route('/api/export/rankings_pdf', methods=['GET'])
@admin_required
def export_rankings_pdf():
    """导出名次公告PDF（仅统计决赛成绩）"""
    # 惰性导入报表库，避免服务启动阶段依赖缺失
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.pagesizes import A4
    buf = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setFont('STSong-Light', 16)
    c.drawString(50, height - 50, '名次公告（仅决赛）')
    c.setFont('STSong-Light', 10)
    c.drawString(50, height - 70, f"导出时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    y = height - 100
    c.setFont('STSong-Light', 12)

    conn = get_db_connection()
    if not conn:
        flash('数据库连接失败', 'error')
        return redirect(url_for('query'))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.event_name,
                   e.event_type,
                   tm.member_name,
                   t.school_name,
                   t.team_name,
                   s.ranking,
                   s.score_value,
                   s.score_unit
            FROM scores s
            JOIN registrations r ON s.registration_id = r.id
            JOIN events e ON r.event_id = e.id
            JOIN teams t ON r.team_id = t.id
            LEFT JOIN registration_members rm ON rm.registration_id = r.id
            LEFT JOIN team_members tm ON tm.id = COALESCE(s.member_id, rm.member_id)
            WHERE s.stage = '决赛'
            ORDER BY e.event_name, s.ranking, tm.member_name
            """
        )
        rows = cursor.fetchall()

        last_event = None
        for row in rows:
            event_name, event_type, member_name, school_name, team_name, ranking, score_value, score_unit = row
            if event_name != last_event:
                # 新项目标题
                if last_event is not None:
                    y -= 10
                c.setFont('STSong-Light', 14)
                c.drawString(50, y, f"项目：{event_name}")
                y -= 20
                c.setFont('STSong-Light', 12)
                c.drawString(50, y, '名次')
                c.drawString(90, y, '成员')
                c.drawString(170, y, '学校')
                c.drawString(260, y, '代表队')
                c.drawString(340, y, '成绩')
                c.drawString(390, y, '单位')
                c.drawString(450, y, '奖牌')
                y -= 16
                last_event = event_name

            # 页底处理
            if y < 60:
                c.showPage()
                c.setFont('STSong-Light', 12)
                y = height - 60

            c.drawString(50, y, str(ranking or ''))
            c.drawString(90, y, member_name or '')
            c.drawString(170, y, school_name or '')
            c.drawString(260, y, team_name or '')
            c.drawString(340, y, f"{score_value}")
            c.drawString(390, y, score_unit or '')
            # 奖牌展示：1金 2银 3铜，其余空白
            medal = ''
            try:
                if ranking == 1:
                    medal = '金牌'
                elif ranking == 2:
                    medal = '银牌'
                elif ranking == 3:
                    medal = '铜牌'
            except Exception:
                medal = ''
            c.drawString(450, y, medal)
            y -= 16

        c.save()
        buf.seek(0)
        filename = f"名次公告_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'导出失败：{e}', 'error')
        return redirect(url_for('query'))
    finally:
        conn.close()

if __name__ == '__main__':
    ensure_schema()
    app.run(debug=True, host='0.0.0.0', port=5000)