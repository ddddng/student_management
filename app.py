import os
import yaml
import secrets
import csv
import click
import datetime # <--- 添加导入
from io import StringIO
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, Response, jsonify # 添加 jsonify 用于可能的 AJAX 响应
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func # 导入 func 用于计算总分
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_migrate import Migrate

# ─── 加载配置 ────────────────────────────────────────────────────────────────
def load_config():
    cfg_file = 'config.yaml'
    default_cfg = {
        'database': {'url': 'sqlite:///students.db'}, # 默认使用 SQLite
        'app':      {'secret_key': '', 'debug': False}
    }
    if not os.path.exists(cfg_file):
        with open(cfg_file, 'w', encoding='utf-8') as f:
            yaml.safe_dump(default_cfg, f)
            print(f"'{cfg_file}' 不存在，已创建默认配置。")
            cfg = default_cfg
    else:
        try:
            with open(cfg_file, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
                if not cfg: # 处理空文件的情况
                    print(f"警告：'{cfg_file}' 为空，使用默认配置。")
                    cfg = default_cfg
                # 合并默认值，确保所有键都存在
                for key, value in default_cfg.items():
                    if key not in cfg:
                        cfg[key] = value
                    elif isinstance(value, dict):
                         for sub_key, sub_value in value.items():
                             if key in cfg and isinstance(cfg[key], dict) and sub_key not in cfg[key]:
                                 cfg[key][sub_key] = sub_value
                             elif key not in cfg: # Ensure parent key exists before adding subkey
                                 cfg[key] = {}
                                 cfg[key][sub_key] = sub_value


        except Exception as e:
            print(f"加载 '{cfg_file}' 出错: {e}，使用默认配置。")
            cfg = default_cfg

    # 自动生成 secret_key
    if not cfg.get('app', {}).get('secret_key'):
        cfg['app']['secret_key'] = secrets.token_hex(16)
        try:
            with open(cfg_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(cfg, f)
            print("已生成并保存新的 'secret_key'。")
        except Exception as e:
            print(f"警告：无法保存自动生成的 'secret_key' 到 '{cfg_file}': {e}")

    # 确保 debug 字段存在且为 bool
    cfg['app']['debug'] = bool(cfg.get('app', {}).get('debug', False))
    # 确保 database url 存在
    if 'database' not in cfg or 'url' not in cfg['database']:
        print("警告：配置中缺少 'database.url'，使用默认 SQLite。")
        cfg['database'] = {'url': 'sqlite:///students.db'}

    return cfg

config = load_config()

# ─── Flask 应用 & 扩展 初始化 ────────────────────────────────────────────────
app = Flask(__name__)
app.config.update({
    'SQLALCHEMY_DATABASE_URI':          config['database']['url'],
    'SECRET_KEY':                       config['app']['secret_key'],
    'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    'DEBUG':                            config['app']['debug'],
    'UPLOAD_FOLDER':                    os.path.join(os.getcwd(), 'uploads'),
    'ALLOWED_EXTENSIONS':               {'csv'}
})

# 确保上传目录存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
migrate = Migrate(app, db) # 初始化 Flask-Migrate
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "请先登录以访问此页面。"
login_manager.login_message_category = "warning"


# ─── 模型 ────────────────────────────────────────────────────────────────────
class User(db.Model, UserMixin):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False) # 使用 Text 支持长哈希

class Subject(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    scores = db.relationship('Score', backref='subject', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Subject {self.name}>'

class Student(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(80), nullable=False)
    class_name = db.Column(db.String(50), nullable=False) # 班级名称可能需要更长
    # 确保这里没有 math_score 等直接的分数列！
    scores     = db.relationship('Score', backref='student', lazy='dynamic', cascade="all, delete-orphan") # lazy='dynamic' 方便查询

    # 计算总分的方法
    def get_total_score(self):
        # 使用 SQLAlchemy 的聚合函数
        total = db.session.query(func.sum(Score.score))\
                          .filter(Score.student_id == self.id)\
                          .scalar()
        return total or 0.0 # 如果没有分数，返回 0.0

    # 获取特定科目的分数 (修正: 直接查询 Score 表)
    def get_score(self, subject_id):
        score_obj = Score.query.filter_by(student_id=self.id, subject_id=subject_id).first()
        return score_obj.score if score_obj else None # 返回 None 或 0.0 皆可，看业务需求

    def __repr__(self):
        return f'<Student {self.name}>'


class Score(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    score      = db.Column(db.Float, nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False) # 添加 ondelete
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id', ondelete='CASCADE'), nullable=False) # 添加 ondelete

    # 确保一个学生对于一个科目只有一个分数
    __table_args__ = (db.UniqueConstraint('student_id', 'subject_id', name='_student_subject_uc'),)

    def __repr__(self):
        # Avoid potential N+1 problem if backref wasn't used carefully elsewhere
        # Fetch student and subject names safely if needed, but often not necessary in repr
        # For simplicity, keep the original repr or just use IDs
         return f'<Score student_id={self.student_id} subject_id={self.subject_id}: {self.score}>'
        # return f'<Score {self.student.name} - {self.subject.name}: {self.score}>' # Use with caution


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 上下文处理器 ---
@app.context_processor
def inject_current_year():
    """将当前年份注入所有模板"""
    return {'current_year': datetime.datetime.now().year}

# ─── 辅助函数 ────────────────────────────────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# ─── 路由 ────────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def home():
    return redirect(url_for('student_list'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        user = User.query.filter_by(username=u).first()
        if user and check_password_hash(user.password, p):
            login_user(user)
            flash("登录成功！", "success")
            next_page = request.args.get('next')
            return redirect(next_page or url_for('student_list'))
        flash("用户名或密码错误！", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("您已成功退出登录。", "info")
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_password')

        if not check_password_hash(current_user.password, old_pw):
            flash("旧密码不正确！", "danger")
        elif not new_pw:
             flash("新密码不能为空！", "danger")
        elif new_pw != confirm_pw:
            flash("两次输入的新密码不一致！", "danger")
        else:
            current_user.password = generate_password_hash(new_pw)
            db.session.commit()
            flash("密码修改成功！", "success")
            return redirect(url_for('student_list')) # 或重定向到个人资料页（如果将来有）
    return render_template('change_password.html')

# --- 科目管理 ---
@app.route('/subjects')
@login_required
def subject_list():
    subjects = Subject.query.order_by(Subject.id).all()
    return render_template('subject_list.html', subjects=subjects)

@app.route('/subject/add', methods=['POST'])
@login_required
def add_subject():
    name = request.form.get('name', '').strip()
    if not name:
        flash("科目名称不能为空！", "danger")
    elif Subject.query.filter(func.lower(Subject.name) == func.lower(name)).first(): # Case-insensitive check
        flash(f"科目 '{name}' 已存在！", "warning")
    else:
        try:
            new_subject = Subject(name=name)
            db.session.add(new_subject)
            db.session.commit()
            flash(f"科目 '{name}' 添加成功！", "success")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error adding subject: {e}", exc_info=True)
            flash(f"添加科目时出错，请查看日志。", "danger")
    return redirect(url_for('subject_list'))

@app.route('/subject/edit/<int:subject_id>', methods=['POST'])
@login_required
def edit_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    new_name = request.form.get('name', '').strip()
    if not new_name:
        flash("科目名称不能为空！", "danger")
    # Check if the new name exists for *another* subject (case-insensitive)
    elif new_name.lower() != subject.name.lower() and \
         Subject.query.filter(func.lower(Subject.name) == func.lower(new_name)).first():
         flash(f"科目名称 '{new_name}' 已被其他科目使用！", "warning")
    else:
        try:
            subject.name = new_name
            db.session.commit()
            flash("科目名称更新成功！", "success")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error editing subject {subject_id}: {e}", exc_info=True)
            flash(f"更新科目时出错，请查看日志。", "danger")
    return redirect(url_for('subject_list'))


@app.route('/subject/delete/<int:subject_id>', methods=['POST'])
@login_required
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    try:
        # Deleting subject cascades to Score thanks to relationship and FK constraint (if set correctly)
        db.session.delete(subject)
        db.session.commit()
        flash(f"科目 '{subject.name}' 及其所有相关成绩已删除！", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting subject {subject_id}: {e}", exc_info=True)
        flash(f"删除科目时出错：{e}", "danger") # Keep original simple message for user
    return redirect(url_for('subject_list'))

# --- 学生管理 ---
@app.route('/students')
@login_required
def student_list():
    search_name = request.args.get('search_name', '').strip()
    search_id = request.args.get('search_id', '').strip()
    # Use the visual selector for user display, hidden inputs drive logic
    sort_by_visual = request.args.get('sort_by_visual', 'id') # Default to 'id'

    # Parameters derived from sort_by_visual (usually set by JS)
    sort_by_subject_id_str = request.args.get('sort_by_subject', '')
    sort_by_total_str = request.args.get('sort_by_total', '').lower()

    sort_by_subject_id = None
    try:
        if sort_by_subject_id_str:
            sort_by_subject_id = int(sort_by_subject_id_str)
    except ValueError:
        sort_by_subject_id = None # Ignore invalid input

    sort_by_total = sort_by_total_str == 'true'

    query = Student.query

    if search_name:
        query = query.filter(Student.name.like(f"%{search_name}%"))
    if search_id:
        try:
            query = query.filter(Student.id == int(search_id))
        except ValueError:
            flash("请输入有效的学生ID（数字）进行搜索！", "warning")
            search_id = '' # Clear invalid input for display

    # Apply sorting
    students = [] # Initialize as empty list
    if sort_by_subject_id:
        query = query.outerjoin(Score, (Student.id == Score.student_id) & (Score.subject_id == sort_by_subject_id))\
                     .order_by(func.coalesce(Score.score, 0).desc(), Student.id) # Sort by score descending, then ID
        students = query.all()
    elif sort_by_total:
        # Fetch all students matching search criteria first
        students_list = query.order_by(Student.id).all() # Fetch with a default order first
        # Sort in Python using the pre-defined method
        try:
            students_list.sort(key=lambda s: s.get_total_score(), reverse=True)
            students = students_list
        except Exception as e:
             app.logger.error(f"Error sorting students by total score: {e}", exc_info=True)
             flash("按总分排序时发生错误。", "danger")
             students = query.order_by(Student.id).all() # Fallback to ID sort
    else:
        # Default sort by ID
        query = query.order_by(Student.id)
        students = query.all()


    subjects = Subject.query.order_by(Subject.id).all() # 获取所有科目用于表头和排序选项

    return render_template('student_list.html',
                           students=students,
                           subjects=subjects,
                           search_name=search_name,
                           search_id=search_id,
                           sort_by=sort_by_visual) # Pass the visual sort parameter for the dropdown selection


@app.route('/student/add', methods=['GET', 'POST'])
@login_required
def add_student():
    subjects = Subject.query.order_by(Subject.id).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        class_name = request.form.get('class_name', '').strip()

        # Prepare data for re-rendering form immediately in case of errors
        temp_student_data = {
            'name': name,
            'class_name': class_name,
            # Capture submitted scores for potential re-display
            'scores': {f'score_{s.id}': request.form.get(f'score_{s.id}') for s in subjects}
        }

        if not name or not class_name:
            flash("学生姓名和班级不能为空！", "danger")
            return render_template('edit_student.html', student_data=temp_student_data, student=None, subjects=subjects)

        new_student = Student(name=name, class_name=class_name)
        db.session.add(new_student)

        try:
            # Flush needed to get new_student.id for Score objects
            db.session.flush()

            scores_data = []
            validation_error = False # Flag for score validation errors
            for subject in subjects:
                score_str = request.form.get(f'score_{subject.id}')
                if score_str and score_str.strip(): # Process only if score is entered
                    try:
                        score_val = float(score_str.strip())
                        if score_val < 0:
                             flash(f"科目 '{subject.name}' 的分数不能为负数！", "warning")
                             validation_error = True
                             continue # Skip adding this score, but continue processing others
                        scores_data.append(Score(student_id=new_student.id, subject_id=subject.id, score=score_val))
                    except ValueError:
                        flash(f"科目 '{subject.name}' 的分数格式无效 ('{score_str}')！请输入数字。", "danger")
                        validation_error = True
                        # Allow seeing all errors, don't break

            if validation_error:
                db.session.rollback() # Rollback student add if any score was invalid
                flash("请修正分数错误后重新提交。", "warning") # General message
                return render_template('edit_student.html', student_data=temp_student_data, student=None, subjects=subjects)


            if scores_data:
                db.session.add_all(scores_data)

            db.session.commit()
            flash("学生添加成功！", "success")
            return redirect(url_for('student_list'))

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error adding student or scores: {e}", exc_info=True)
            flash(f"添加学生或成绩时发生数据库错误，请检查日志。", "danger")
            return render_template('edit_student.html', student_data=temp_student_data, student=None, subjects=subjects)

    # GET request
    return render_template('edit_student.html', student=None, subjects=subjects)


@app.route('/student/edit/<int:student_id>', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    subjects = Subject.query.order_by(Subject.id).all()

    if request.method == 'POST':
        new_name = request.form.get('name', '').strip()
        new_class_name = request.form.get('class_name', '').strip()

        # Prepare data for re-rendering form immediately in case of errors
        submitted_scores = {f'score_{s.id}': request.form.get(f'score_{s.id}') for s in subjects}
        temp_student_data = {'name': new_name, 'class_name': new_class_name, 'scores': submitted_scores }

        if not new_name or not new_class_name:
            flash("学生姓名和班级不能为空！", "danger")
            # Re-render form with submitted values
            # Pass `student` for ID context, `temp_student_data` for values
            return render_template('edit_student.html', student=student, student_data=temp_student_data, subjects=subjects)

        student.name = new_name
        student.class_name = new_class_name

        try:
            validation_error = False # Flag for score validation errors
            scores_to_add = []    # New Score objects
            scores_to_delete = [] # Existing Score objects to remove

            for subject in subjects:
                score_str = request.form.get(f'score_{subject.id}')
                # Find existing score using query for clarity, avoid potential lazy-loading issues in loop
                existing_score_obj = Score.query.filter_by(student_id=student.id, subject_id=subject.id).first()

                if score_str and score_str.strip(): # Score value provided
                    try:
                        score_val = float(score_str.strip())
                        if score_val < 0:
                            flash(f"科目 '{subject.name}' 的分数不能为负数！该科目未更新。", "warning")
                            validation_error = True
                            continue # Skip this subject

                        if existing_score_obj:
                            if existing_score_obj.score != score_val: # Update only if changed
                                existing_score_obj.score = score_val
                                # Mark as modified (SQLAlchemy usually handles this, but explicit doesn't hurt)
                                db.session.add(existing_score_obj)
                        else:
                            # Create new Score object if it didn't exist
                            scores_to_add.append(Score(student_id=student.id, subject_id=subject.id, score=score_val))

                    except ValueError:
                        flash(f"科目 '{subject.name}' 的分数格式无效 ('{score_str}')！请输入数字。该科目未更新。", "danger")
                        validation_error = True
                        continue # Skip this subject

                elif existing_score_obj and (not score_str or not score_str.strip()):
                    # Score existed but input is now empty, mark for deletion
                    scores_to_delete.append(existing_score_obj)

            # If strict validation (all or nothing) is needed, uncomment below
            # if validation_error:
            #     db.session.rollback()
            #     flash("部分成绩格式有误，未保存任何更改。请修正后重新提交。", "danger")
            #     return render_template('edit_student.html', student=student, student_data=temp_student_data, subjects=subjects)


            # Add new scores
            if scores_to_add:
                db.session.add_all(scores_to_add)
            # Delete scores marked for deletion
            if scores_to_delete:
                for score_obj in scores_to_delete:
                    db.session.delete(score_obj)

            # Commit all changes (updates to student, updates to existing scores, additions, deletions)
            db.session.commit()

            if not validation_error:
                 flash("学生信息更新成功！", "success")
            else:
                 flash("学生信息已部分更新，但部分成绩因格式或数值问题未被保存，请检查。", "warning")

            return redirect(url_for('student_list'))

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error editing student {student_id}: {e}", exc_info=True)
            flash(f"更新学生信息时发生数据库错误：{e}", "danger")
            # Re-render with submitted data
            return render_template('edit_student.html', student=student, student_data=temp_student_data, subjects=subjects)


    # GET request: Prepare existing scores for display
    # Fetch scores into a dictionary {subject_id: score_value}
    existing_scores = {score.subject_id: score.score for score in student.scores.all()}
    return render_template('edit_student.html', student=student, subjects=subjects, current_scores=existing_scores)


@app.route('/student/delete/<int:student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    try:
        # Deleting the student should cascade via relationship/FK if set up correctly
        db.session.delete(student)
        db.session.commit()
        flash(f"学生 '{student.name}' (ID: {student_id}) 已成功删除！", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting student {student_id}: {e}", exc_info=True)
        flash(f"删除学生时出错：{e}", "danger")
    return redirect(url_for('student_list'))


@app.route('/export')
@login_required
def export_students():
    students = Student.query.order_by(Student.id).all()
    subjects = Subject.query.order_by(Subject.id).all()

    si = StringIO()
    # Use utf-8-sig for BOM
    # si.write(u'\ufeff') # Not needed if encoding handled by Response object correctly

    writer = csv.writer(si)

    # Dynamic header generation
    header = ['ID', '姓名', '班级'] + [subject.name for subject in subjects] + ['总分']
    writer.writerow(header)

    # Write data rows
    for student in students:
        # Pre-fetch scores into a dictionary for efficient lookup {subject_id: score}
        scores_dict = {score.subject_id: score.score for score in student.scores.all()} # Use .all() with lazy='dynamic'
        row = [student.id, student.name, student.class_name]
        total_score = 0
        for subject in subjects:
            score = scores_dict.get(subject.id) # Get score or None
            row.append(f"{score:.1f}" if isinstance(score, (int, float)) else '') # Format or empty string
            if isinstance(score, (int, float)):
                total_score += score
        row.append(f"{total_score:.1f}") # Add formatted total score
        writer.writerow(row)

    output = si.getvalue()

    return Response(
        output, # Keep raw string
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment;filename=students_export.csv",
            "Content-Type": "text/csv; charset=utf-8-sig" # Specify encoding with BOM here
            }
    )


@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_students():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or f.filename == '':
            flash("未选择文件！", "danger")
            return redirect(request.url)
        if not allowed_file(f.filename):
            flash("不允许的文件类型，请上传 CSV 文件！", "danger")
            return redirect(request.url)

        try:
            # Attempt to decode with common encodings
            content = f.stream.read()
            decoded_content = None
            encodings_to_try = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312']
            detected_encoding = None
            for enc in encodings_to_try:
                try:
                    decoded_content = content.decode(enc)
                    detected_encoding = enc
                    app.logger.info(f"CSV file decoded successfully using encoding: {enc}")
                    break
                except UnicodeDecodeError:
                    continue

            if decoded_content is None:
                 flash("无法解码文件内容，请确保文件使用 UTF-8 或 GBK/GB2312 编码。", "danger")
                 return redirect(request.url)

            stream = StringIO(decoded_content) # Use default newline handling of StringIO
            reader = csv.reader(stream)

            # --- Header Validation ---
            header = next(reader, None)
            if not header:
                flash("CSV 文件为空或无法读取表头！", "danger")
                return redirect(request.url)

            # Normalize header names
            normalized_header = [h.strip().lower() for h in header]
            try:
                # Case-insensitive check for required columns
                name_index = next(i for i, h in enumerate(normalized_header) if h == '姓名')
                class_index = next(i for i, h in enumerate(normalized_header) if h == '班级')
            except StopIteration:
                 flash("CSV 文件格式错误！表头必须包含 '姓名' 和 '班级' 列（大小写不敏感）。", "danger")
                 return redirect(request.url)

            # --- Subject Mapping ---
            all_subjects = Subject.query.all()
            subject_name_to_id = {subject.name.strip().lower(): subject.id for subject in all_subjects} # Lowercase and strip for mapping
            csv_col_index_to_subject_id = {} # Map CSV column index to subject_id
            unknown_subjects_in_csv = []
            processed_indices = {name_index, class_index}

            for index, col_name in enumerate(header):
                if index in processed_indices:
                    continue
                normalized_col_name = col_name.strip().lower()
                if not normalized_col_name: # Skip empty column headers
                    continue

                subject_id = subject_name_to_id.get(normalized_col_name)
                if subject_id:
                    csv_col_index_to_subject_id[index] = subject_id
                    processed_indices.add(index)
                elif col_name.strip(): # Report only non-empty unknown columns
                    unknown_subjects_in_csv.append(col_name.strip())

            if unknown_subjects_in_csv:
                 flash(f"警告：CSV 文件中的以下科目在系统中不存在或名称不完全匹配，对应列将被忽略：{', '.join(unknown_subjects_in_csv)}", "warning")

            # --- Data Processing ---
            imported_count = 0
            updated_count = 0 # If implementing update logic later
            skipped_rows_info = [] # Store tuples (line_num, reason)
            line_num = 1 # Header is line 1

            # Process rows
            for row in reader:
                line_num += 1
                if not row or len(row) <= max(name_index, class_index): # Skip empty or short rows
                    # Optionally log short rows if needed
                    # skipped_rows_info.append((line_num, "行数据不完整"))
                    continue

                # Check if row is entirely empty cells
                if all(not cell or cell.isspace() for cell in row):
                    continue

                name = row[name_index].strip()
                class_name = row[class_index].strip()

                if not name or not class_name:
                    skipped_rows_info.append((line_num, f"姓名 ('{name}') 或班级 ('{class_name}') 为空"))
                    continue

                # --- Find or Create Student ---
                # Simple: Add new student. Assumes unique names/classes aren't strictly enforced or handled manually.
                # TODO: Add logic here to check if student exists and update instead?
                student = Student(name=name, class_name=class_name)
                db.session.add(student) # Add student tentatively

                current_student_scores_valid = []
                score_error_in_row = False
                for col_index, subject_id in csv_col_index_to_subject_id.items():
                    if col_index < len(row) and row[col_index] and row[col_index].strip(): # Check index and if cell has non-whitespace content
                        score_str = row[col_index].strip()
                        try:
                            score_val = float(score_str)
                            if score_val < 0:
                                 skipped_rows_info.append((line_num, f"姓名'{name}', 科目'{header[col_index]}'分数无效(负数: {score_str})"))
                                 score_error_in_row = True
                                 break # Stop processing scores for this row on error
                            # Store valid score info temporarily
                            current_student_scores_valid.append({'subject_id': subject_id, 'score': score_val})
                        except ValueError:
                            skipped_rows_info.append((line_num, f"姓名'{name}', 科目'{header[col_index]}'分数格式无效('{score_str}')"))
                            score_error_in_row = True
                            break # Stop processing scores for this row on error

                if score_error_in_row:
                    db.session.rollback() # Rollback the student add for this row
                    continue # Move to the next row in CSV
                else:
                    # No score errors, proceed to associate scores after flushing student
                    try:
                        db.session.flush() # Flush to get student.id
                        for score_info in current_student_scores_valid:
                             # Check for existing score before adding (important if update logic is added)
                             # For pure add, this isn't strictly needed but good practice
                             existing = Score.query.filter_by(student_id=student.id, subject_id=score_info['subject_id']).first()
                             if not existing:
                                 db.session.add(Score(student_id=student.id, subject_id=score_info['subject_id'], score=score_info['score']))
                             # else: handle update if needed
                        # Commit per student (safer for large files, prevents one error stopping all)
                        db.session.commit()
                        imported_count += 1
                    except Exception as ex:
                         db.session.rollback() # Rollback this student's transaction
                         skipped_rows_info.append((line_num, f"姓名'{name}', 数据库错误: {ex}"))


            # --- Final Report ---
            success_msg = "导入完成！"
            if imported_count > 0:
                success_msg += f" 成功添加 {imported_count} 名新学生记录。"
            else: # If nothing was imported (and no updates implemented)
                 if not skipped_rows_info: # And no rows were skipped
                     success_msg = "未导入任何新学生数据。CSV 文件可能为空或所有学生已存在（如果实现更新逻辑）。"
                 else: # Nothing imported, but rows were skipped
                      success_msg = "未导入任何新学生数据。"


            if skipped_rows_info:
                 # Summarize skipped rows concisely
                 reasons = {}
                 max_reasons_to_show = 3
                 for _, reason in skipped_rows_info:
                     simple_reason = reason.split(',')[1] if ',' in reason else reason # Simplify reason text
                     simple_reason = simple_reason.split(':')[0].strip() # Further simplify
                     reasons[simple_reason] = reasons.get(simple_reason, 0) + 1

                 summary_parts = [f"{count} 行因 '{reason}'" for reason, count in list(reasons.items())[:max_reasons_to_show]]
                 if len(reasons) > max_reasons_to_show:
                     summary_parts.append("及其他原因")
                 summary = ", ".join(summary_parts)

                 success_msg += f" 跳过了 {len(skipped_rows_info)} 行 ({summary})。"
                 flash(success_msg, "warning") # Use warning if skips occurred
            elif imported_count > 0: # or updated_count > 0:
                 flash(success_msg, "success") # Use success only if no skips
            else:
                 flash(success_msg, "info") # Use info if nothing imported and no skips


            return redirect(url_for('student_list'))

        except Exception as e:
            db.session.rollback() # Rollback any partial changes on major error
            flash(f"处理 CSV 文件时发生严重错误：{e}", "danger")
            app.logger.error(f"CSV import failed: {e}", exc_info=True)
            return redirect(request.url)

    # GET request
    return render_template('import.html')


# ─── CLI：数据库管理 ───────────────────────────────────────────────
@app.cli.command("init-db")
@click.option('--drop', is_flag=True, help='删除所有表后再创建。')
def init_db(drop):
    """初始化数据库：创建所有表并添加默认管理员 admin/admin。"""
    with app.app_context():
        if drop:
            click.confirm('确定要删除所有数据库表吗？此操作不可逆！', abort=True)
            db.drop_all()
            click.echo("已删除所有表。")

        try:
            db.create_all()
            click.echo("已创建所有数据库表。")
        except Exception as e:
             click.echo(f"创建数据库表时出错: {e}", err=True)
             return # Stop if tables can't be created


        if not User.query.filter_by(username="admin").first():
            admin_password = "admin" # 默认密码
            try:
                admin = User(
                    username="admin",
                    password=generate_password_hash(admin_password)
                )
                db.session.add(admin)
                db.session.commit()
                click.echo(f"已创建默认管理员账户：admin / {admin_password}")
            except Exception as e:
                 db.session.rollback()
                 click.echo(f"创建默认管理员时出错: {e}", err=True)
        else:
            click.echo("管理员账户 'admin' 已存在。")

        # 可以选择在这里添加默认科目
        default_subjects = ["语文", "数学", "英语", "科学", "物理"] # Added Physics
        added_subjects = []
        try:
            for subj_name in default_subjects:
                 # Case-insensitive check
                 if not Subject.query.filter(func.lower(Subject.name) == func.lower(subj_name)).first():
                     db.session.add(Subject(name=subj_name))
                     added_subjects.append(subj_name)
            if added_subjects:
                 db.session.commit()
                 click.echo(f"已添加默认科目：{', '.join(added_subjects)}")
            else:
                 click.echo("默认科目已存在或添加失败。")
        except Exception as e:
             db.session.rollback()
             click.echo(f"添加默认科目时出错: {e}", err=True)


# ─── 启动检查与运行 ───────────────────────────────────────────────────────────────────
def initialize_database():
     """确保数据库和必要的数据存在 (在应用启动时检查)"""
     # This runs *before* the first request, but *after* the app object is created.
     # It's good for initial checks but less ideal for complex setup than CLI commands.
     with app.app_context():
        try:
            # Attempt a simple query to check DB connection & table existence (more reliable than create_all)
            db.session.query(User).first()
            print("数据库连接正常，表结构已存在。")
        except Exception as e:
             print(f"数据库连接或表结构检查失败: {e}")
             print("请确保数据库服务正在运行，并且已使用 'flask db upgrade' 或 'flask init-db' 初始化数据库。")
             # Optionally exit if DB is mandatory for startup
             # exit(1)

        # Ensure default admin exists (moved logic here from original position)
        try:
            if not User.query.filter_by(username="admin").first():
                print("未找到管理员 'admin'，正在创建默认管理员 admin/admin...")
                admin = User(
                    username="admin",
                    password=generate_password_hash("admin") # Use same default password
                )
                db.session.add(admin)
                db.session.commit()
                print("默认管理员创建成功。")
        except Exception as e:
             print(f"检查或创建默认管理员时出错: {e}")
             db.session.rollback() # Rollback potentially failed commit

        # Ensure default subjects exist (moved logic here)
        try:
            default_subjects = ["语文", "数学", "英语", "科学", "物理"] # Match CLI
            added_subjects = []
            for subj_name in default_subjects:
                 # Case-insensitive check
                 if not Subject.query.filter(func.lower(Subject.name) == func.lower(subj_name)).first():
                     db.session.add(Subject(name=subj_name))
                     added_subjects.append(subj_name)
            if added_subjects:
                 db.session.commit()
                 print(f"已添加默认科目：{', '.join(added_subjects)}")
        except Exception as e:
             print(f"检查或创建默认科目时出错: {e}")
             db.session.rollback()


if __name__ == '__main__':
    # Initialize database schema and default data CHECK before running
    # initialize_database() # Call the check function
    # Use flask run instead of app.run for development
    pass # Standard practice is to use `flask run` command
else:
     # Perform initialization checks when imported (e.g., by Gunicorn/uWSGI)
     # initialize_database() # Uncomment if needed for production deployment initialization
     pass