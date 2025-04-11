# 学生成绩管理系统

这是一个基于 Flask 框架和 SQLAlchemy 构建的简单学生成绩管理系统。

源代码托管于 GitHub: [https://github.com/ddddng/student_management](https://github.com/ddddng/student_management)

## 主要功能

*   用户登录/登出/密码修改
*   学生信息管理 (增删改查、搜索)
*   科目管理 (增删改)
*   成绩录入与展示
*   按科目/总分排序
*   CSV 数据导入/导出

## 环境要求

*   Python 3.8 或更高版本
*   pip (Python 包管理器)
*   Git (用于克隆仓库)
*   MySQL 数据库 (可选，如果配置使用)

## 安装与设置

1.  **克隆仓库:**
    打开你的终端或命令行工具，执行：
    ```bash
    git clone https://github.com/ddddng/student_management.git
    cd student_management
    ```

2.  **安装依赖包:**
    项目依赖项在 `requirements.txt` 文件中列出
    ```bash
    pip install -r requirements.txt
    ```

## 配置

应用程序的主要配置在项目根目录的 `config.yaml` 文件中。

1.  **首次运行:** 如果 `config.yaml` 不存在，应用程序在首次尝试运行时会自动创建它，包含默认设置
2.  **数据库连接:**
    *   **MySQL:**
        *   首先，请确保你已在 MySQL 中创建了一个数据库 (例如 `student_db`)。
        *   编辑 `config.yaml` 文件，修改 `database` 部分：
            ```yaml
            database:
              # 注释掉或删除 SQLite 行
              # url: sqlite:///students.db
              # 添加 MySQL 连接字符串，替换<>中的内容
              url: mysql+pymysql://<用户名>:<密码>@<主机地址>:<端口号>/<数据库名>?charset=utf8mb4
            ```
            **示例:** `url: mysql+pymysql://root:your_mysql_password@localhost:3306/student_db?charset=utf8mb4`
        *   确保已安装对应的 Python MySQL 驱动 (如 `PyMySQL`)。
3.  **Secret Key:** 用于会话安全，首次运行会自动生成并写入 `config.yaml`。
4.  **Debug 模式:** 在 `config.yaml` 中，可设置 `app.debug` 为 `true` (开发) 或 `false` (生产)。

## 数据库设置

本项目使用 Flask-Migrate 来管理数据库表结构的变更。

1.  **初始化 Migrate (如果项目中没有 `migrations` 文件夹):**
    ```bash
    flask db init
    ```

2.  **创建/更新数据库表:**
    *   **首次创建:**
        ```bash
        # 生成第一个迁移脚本 (基于当前模型)
        flask db migrate -m "Initial migration."
        # 应用迁移，创建所有表
        flask db upgrade
        ```
    *   **模型更改后更新:**
        如果你修改了 `app.py` 中的 `db.Model` 类（如添加字段），请执行：
        ```bash
        # 生成记录更改的迁移脚本
        flask db migrate -m "描述你的更改，例如：添加 email 到 Student"
        # 应用更改到数据库
        flask db upgrade
        ```

3.  **创建初始管理员和科目 (可选):**
    此命令会尝试创建表（如果不存在）、添加默认管理员 (`admin`/`admin`) 和默认科目。
    ```bash
    flask init-db
    ```
    *如果需要强制删除所有表并重新创建 (会丢失所有数据!)，请使用:*
    ```bash
    # 警告：删除所有数据！
    flask init-db --drop
    ```

## 运行应用

1.  **确保配置和数据库就绪:**
    *   依赖已安装。
    *   `config.yaml` 配置正确。
    *   数据库已通过 `flask db upgrade` 更新到最新结构。
2.  **启动开发服务器:**
    在项目根目录下运行：
    ```bash
    flask run
    ```
3.  **访问:**
    在浏览器中打开通常是 `http://127.0.0.1:5000` 的地址。

## 使用

*   **登录:** 使用默认账号 `admin` / `admin` (如果运行过 `flask init-db`)，或你自行创建的账号。建议首次登录后修改密码。
*   **操作:** 通过导航栏访问学生列表、科目管理、导入导出等功能。
*   **CSV 导入:** 确保上传的 CSV 文件包含名为 "姓名" 和 "班级" 的表头 (大小写不敏感)。其他列名应与系统中的科目名称匹配才能导入对应成绩。
*   **CSV 导出:** 将导出当前所有学生及其各科成绩和总分。