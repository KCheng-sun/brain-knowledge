"""MySQL 数据库迁移脚本（Phase 5D）。

从 SQLite (data/metadata.db) 迁移全部数据到 MySQL：
1. 自动创建 brain 数据库
2. 从 SQLite 读取真实表结构，在 MySQL 重建表（确保列名完全一致）
3. 逐表导入数据

用法：python -m brain.storage.migrate_to_mysql
"""

import sqlite3
import sys

import pymysql

from brain.config import get_config


def to_mysql_type(ctype: str) -> str:
    """SQLite 类型 → MySQL 类型映射。"""
    ctype = ctype.upper()
    if "INTEGER" in ctype or "INT" in ctype:
        return "INT"
    if "REAL" in ctype or "FLOAT" in ctype or "DOUBLE" in ctype:
        return "DOUBLE"
    return "TEXT"


def migrate():
    """执行迁移。"""
    cfg = get_config()
    db_cfg = cfg.database
    sqlite_path = cfg.storage.db_path

    if not sqlite_path.exists():
        print(f"❌ SQLite 文件不存在: {sqlite_path}")
        sys.exit(1)

    print(f"源: SQLite ({sqlite_path})")
    print(f"目标: MySQL ({db_cfg.host}:{db_cfg.port}/{db_cfg.database})")

    # 1. 创建数据库
    conn = pymysql.connect(
        host=db_cfg.host, port=db_cfg.port,
        user=db_cfg.user, password=db_cfg.password, charset=db_cfg.charset,
    )
    cur = conn.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_cfg.database}` "
        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ 数据库 {db_cfg.database} 已就绪")

    # 2. 连接到目标库
    conn = pymysql.connect(
        host=db_cfg.host, port=db_cfg.port,
        user=db_cfg.user, password=db_cfg.password,
        database=db_cfg.database, charset=db_cfg.charset,
    )
    mcur = conn.cursor()

    # 3. 从 SQLite 读取表结构，在 MySQL 重建
    sconn = sqlite3.connect(str(sqlite_path))
    sconn.row_factory = sqlite3.Row
    tables = [
        r[0] for r in sconn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    print(f"\nSQLite 表: {tables}")

    for t in tables:
        cols_info = sconn.execute(f"PRAGMA table_info({t})").fetchall()
        pk_cols = [c["name"] for c in cols_info if c["pk"]]
        has_composite_pk = len(pk_cols) > 1

        col_defs = []
        for c in cols_info:
            name = c["name"]
            mtype = to_mysql_type(c["type"])
            is_pk = c["pk"]
            if is_pk and mtype == "TEXT":
                mtype = "VARCHAR(255)"
            if is_pk and mtype == "INT" and not has_composite_pk:
                col_defs.append(f"`{name}` INT AUTO_INCREMENT PRIMARY KEY")
            elif is_pk and not has_composite_pk:
                col_defs.append(f"`{name}` {mtype} PRIMARY KEY")
            else:
                default = ""
                if c["dflt_value"] is not None and mtype != "TEXT":
                    default = f" DEFAULT {c['dflt_value']}"
                col_defs.append(f"`{name}` {mtype}{default}")

        # 复合主键
        if has_composite_pk and not any(
            c["pk"] == 1 and to_mysql_type(c["type"]) == "INT" for c in cols_info
        ):
            pk_def = []
            for pc in pk_cols:
                col_type = next(to_mysql_type(c["type"]) for c in cols_info if c["name"] == pc)
                if col_type == "TEXT":
                    pk_def.append(f"`{pc}`(255)")
                else:
                    pk_def.append(f"`{pc}`")
            col_defs.append(f"PRIMARY KEY ({', '.join(pk_def)})")

        # 索引
        indexes = sconn.execute(f"PRAGMA index_list({t})").fetchall()
        for idx in indexes:
            idx_name = idx["name"]
            if idx_name.startswith("sqlite_autoindex"):
                continue
            idx_cols = [r["name"] for r in sconn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
            idx_col_defs = []
            for ic in idx_cols:
                col_type = next(to_mysql_type(c["type"]) for c in cols_info if c["name"] == ic)
                if col_type == "TEXT":
                    idx_col_defs.append(f"`{ic}`(255)")
                else:
                    idx_col_defs.append(f"`{ic}`")
            unique = "UNIQUE" if idx["unique"] else ""
            col_defs.append(f"{unique} INDEX `{idx_name}` ({', '.join(idx_col_defs)})")

        ddl = f"CREATE TABLE IF NOT EXISTS `{t}` (\n  " + ",\n  ".join(col_defs) + "\n)"
        mcur.execute(f"DROP TABLE IF EXISTS `{t}`")
        mcur.execute(ddl)
        print(f"  重建 {t} ({len(cols_info)} 列)")

    conn.commit()

    # 4. 导入数据
    total_rows = 0
    for t in tables:
        rows = sconn.execute(f"SELECT * FROM {t}").fetchall()
        if not rows:
            print(f"  {t}: 0 行（跳过）")
            continue
        cols = rows[0].keys()
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(f"`{c}`" for c in cols)
        sql = f"INSERT IGNORE INTO `{t}` ({col_names}) VALUES ({placeholders})"
        data = [tuple(r) for r in rows]
        mcur.executemany(sql, data)
        conn.commit()
        print(f"  {t}: {len(data)} 行已导入")
        total_rows += len(data)

    sconn.close()
    mcur.close()
    conn.close()
    print(f"\n✅ 迁移完成，共导入 {total_rows} 行数据")


if __name__ == "__main__":
    migrate()
