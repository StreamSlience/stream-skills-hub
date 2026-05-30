#!/usr/bin/env python3
"""
safety_rules.py - 安全规则模块

定义和应用 SQL 升级规则，确保生成的 SQL 语句安全可靠。
支持 PostgreSQL 和 ClickHouse 的特性差异。
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable
from change_detector import Change
from sql_parser import SQLStatement


# ─────────────────────────────────────────────
# 数据类定义
# ─────────────────────────────────────────────

@dataclass
class SafetyRule:
    """安全规则定义"""
    stmt_type: str  # 适用的语句类型
    action: str  # 适用的变动类型（add、remove、modify）
    db_type: str  # 适用的数据库类型（postgres、clickhouse、*）
    rule_func: Callable  # 规则函数


# ─────────────────────────────────────────────
# 规则函数库 - CREATE 语句
# ─────────────────────────────────────────────

def rule_create_table_add(change: Change, db_type: str) -> Optional[str]:
    """CREATE TABLE 新增规则：确保 IF NOT EXISTS"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF NOT EXISTS" in upper:
        return sql + ";"

    # 在表名前插入 IF NOT EXISTS
    # 匹配 CREATE [TEMPORARY] TABLE <name>
    pattern = r"(CREATE\s+(?:TEMPORARY\s+)?TABLE\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF NOT EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        # 兜底方案
        replaced = re.sub(
            r"(CREATE\s+(?:TEMPORARY\s+)?TABLE\s+)",
            r"\1IF NOT EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_create_index_add(change: Change, db_type: str) -> Optional[str]:
    """CREATE INDEX 新增规则：确保 IF NOT EXISTS"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF NOT EXISTS" in upper:
        return sql + ";"

    # 在索引名前插入 IF NOT EXISTS
    pattern = r"(CREATE\s+(?:UNIQUE\s+)?INDEX\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF NOT EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(CREATE\s+(?:UNIQUE\s+)?INDEX\s+)",
            r"\1IF NOT EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_create_view_add(change: Change, db_type: str) -> Optional[str]:
    """CREATE VIEW 新增规则：确保 IF NOT EXISTS"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF NOT EXISTS" in upper:
        return sql + ";"

    # 在视图名前插入 IF NOT EXISTS
    pattern = r"(CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF NOT EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+)",
            r"\1IF NOT EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_create_function_add(change: Change, db_type: str) -> Optional[str]:
    """CREATE FUNCTION 新增规则：PostgreSQL 用 OR REPLACE，ClickHouse 用 IF NOT EXISTS"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if db_type == "postgres":
        # PostgreSQL：使用 CREATE OR REPLACE FUNCTION
        if "OR REPLACE" in upper:
            return sql + ";"

        replaced = re.sub(
            r"(CREATE\s+)(?:OR\s+REPLACE\s+)?(FUNCTION\s+)",
            r"\1OR REPLACE \2",
            sql, count=1, flags=re.IGNORECASE
        )
        return replaced + ";"

    else:  # clickhouse
        # ClickHouse：使用 IF NOT EXISTS
        if "IF NOT EXISTS" in upper:
            return sql + ";"

        replaced = re.sub(
            r"(CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+)",
            r"\1IF NOT EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )
        return replaced + ";"


def rule_create_dict_add(change: Change, db_type: str) -> Optional[str]:
    """CREATE DICTIONARY 新增规则（ClickHouse）：确保 IF NOT EXISTS"""
    if db_type != "clickhouse":
        return None

    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF NOT EXISTS" in upper:
        return sql + ";"

    pattern = r"(CREATE\s+DICTIONARY\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF NOT EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(CREATE\s+DICTIONARY\s+)",
            r"\1IF NOT EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


# ─────────────────────────────────────────────
# 规则函数库 - DROP 语句
# ─────────────────────────────────────────────

def rule_drop_table_remove(change: Change, db_type: str) -> Optional[str]:
    """DROP TABLE 删除规则：确保 IF EXISTS"""
    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF EXISTS" in upper:
        return sql + ";"

    # 在表名前插入 IF EXISTS
    pattern = r"(DROP\s+TABLE\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(DROP\s+TABLE\s+)",
            r"\1IF EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_drop_index_remove(change: Change, db_type: str) -> Optional[str]:
    """DROP INDEX 删除规则：确保 IF EXISTS"""
    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF EXISTS" in upper:
        return sql + ";"

    pattern = r"(DROP\s+INDEX\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(DROP\s+INDEX\s+)",
            r"\1IF EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_drop_view_remove(change: Change, db_type: str) -> Optional[str]:
    """DROP VIEW 删除规则：确保 IF EXISTS"""
    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF EXISTS" in upper:
        return sql + ";"

    pattern = r"(DROP\s+(?:MATERIALIZED\s+)?VIEW\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(DROP\s+(?:MATERIALIZED\s+)?VIEW\s+)",
            r"\1IF EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_drop_function_remove(change: Change, db_type: str) -> Optional[str]:
    """DROP FUNCTION 删除规则：确保 IF EXISTS"""
    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF EXISTS" in upper:
        return sql + ";"

    pattern = r"(DROP\s+FUNCTION\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(DROP\s+FUNCTION\s+)",
            r"\1IF EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


def rule_drop_dict_remove(change: Change, db_type: str) -> Optional[str]:
    """DROP DICTIONARY 删除规则（ClickHouse）：确保 IF EXISTS"""
    if db_type != "clickhouse":
        return None

    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if "IF EXISTS" in upper:
        return sql + ";"

    pattern = r"(DROP\s+DICTIONARY\s+)(\S+)"
    replaced = re.sub(pattern, r"\1IF EXISTS \2", sql, count=1, flags=re.IGNORECASE)

    if replaced == sql:
        replaced = re.sub(
            r"(DROP\s+DICTIONARY\s+)",
            r"\1IF EXISTS ",
            sql, count=1, flags=re.IGNORECASE
        )

    return replaced + ";"


# ─────────────────────────────────────────────
# 规则函数库 - ALTER TABLE 语句
# ─────────────────────────────────────────────

def rule_alter_add_column(change: Change, db_type: str) -> Optional[str]:
    """ALTER TABLE ADD COLUMN 规则"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if db_type == "postgres":
        # PostgreSQL：支持 IF NOT EXISTS
        if "ADD COLUMN" in upper and "IF NOT EXISTS" not in upper:
            sql = re.sub(
                r"(ADD\s+COLUMN\s+)",
                r"\1IF NOT EXISTS ",
                sql, count=1, flags=re.IGNORECASE
            )
    # ClickHouse 不支持 IF NOT EXISTS，直接输出原语句

    return sql + ";"


def rule_alter_drop_column(change: Change, db_type: str) -> Optional[str]:
    """ALTER TABLE DROP COLUMN 规则"""
    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    upper = sql.upper()

    if db_type == "postgres":
        # PostgreSQL：支持 IF EXISTS
        if "DROP COLUMN" in upper and "IF EXISTS" not in upper:
            sql = re.sub(
                r"(DROP\s+COLUMN\s+)",
                r"\1IF EXISTS ",
                sql, count=1, flags=re.IGNORECASE
            )
    # ClickHouse 不支持 IF EXISTS，直接输出原语句

    return sql + ";"


def rule_alter_modify_column(change: Change, db_type: str) -> Optional[str]:
    """ALTER TABLE MODIFY COLUMN 规则"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")

    # 对于 MODIFY，直接输出（两个数据库都支持）
    return sql + ";"


# ─────────────────────────────────────────────
# 规则函数库 - DML 语句
# ─────────────────────────────────────────────

def check_safe_dml(stmt: SQLStatement) -> tuple[bool, Optional[str]]:
    """
    检查 UPDATE/DELETE 是否安全（有非永真 WHERE 条件）。

    Returns:
        (is_safe, warning_message)
    """
    sql = stmt.raw_sql.upper()

    # 检查是否有 WHERE 子句
    if "WHERE" not in sql:
        return False, f"危险操作（无 WHERE 条件）：{stmt.raw_sql[:80]}"

    # 检查是否为永真式 WHERE
    # 匹配 WHERE 1=1、WHERE TRUE、WHERE 1<>0 等
    where_part = sql[sql.find("WHERE"):]

    # 永真式模式
    always_true_patterns = [
        r"WHERE\s+1\s*=\s*1\s*(?:;|$)",
        r"WHERE\s+TRUE\s*(?:;|$)",
        r"WHERE\s+1\s*<>\s*0\s*(?:;|$)",
        r"WHERE\s+0\s*=\s*0\s*(?:;|$)",
    ]

    for pattern in always_true_patterns:
        if re.search(pattern, where_part, re.IGNORECASE):
            return False, f"危险操作（永真 WHERE）：{stmt.raw_sql[:80]}"

    return True, None


def rule_insert_add(change: Change, db_type: str) -> Optional[str]:
    """INSERT 新增规则"""
    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    return sql + ";"


def rule_update_add(change: Change, db_type: str) -> Optional[str]:
    """UPDATE 新增规则：检查 WHERE 条件"""
    is_safe, warning = check_safe_dml(change.new_stmt)

    if not is_safe:
        print(f"  [SKIP] {warning}", flush=True)
        return None

    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    return sql + ";"


def rule_update_remove(change: Change, db_type: str) -> Optional[str]:
    """UPDATE 删除规则：检查 WHERE 条件"""
    is_safe, warning = check_safe_dml(change.old_stmt)

    if not is_safe:
        print(f"  [SKIP] {warning}", flush=True)
        return None

    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    return sql + ";"


def rule_delete_add(change: Change, db_type: str) -> Optional[str]:
    """DELETE 新增规则：检查 WHERE 条件"""
    is_safe, warning = check_safe_dml(change.new_stmt)

    if not is_safe:
        print(f"  [SKIP] {warning}", flush=True)
        return None

    sql = change.new_stmt.raw_sql.strip().rstrip(";")
    return sql + ";"


def rule_delete_remove(change: Change, db_type: str) -> Optional[str]:
    """DELETE 删除规则：检查 WHERE 条件"""
    is_safe, warning = check_safe_dml(change.old_stmt)

    if not is_safe:
        print(f"  [SKIP] {warning}", flush=True)
        return None

    sql = change.old_stmt.raw_sql.strip().rstrip(";")
    return sql + ";"


# ─────────────────────────────────────────────
# 规则库初始化
# ─────────────────────────────────────────────

SAFETY_RULES: List[SafetyRule] = [
    # CREATE 规则
    SafetyRule("CREATE_TABLE", "add", "*", rule_create_table_add),
    SafetyRule("CREATE_INDEX", "add", "*", rule_create_index_add),
    SafetyRule("CREATE_VIEW", "add", "*", rule_create_view_add),
    SafetyRule("CREATE_FUNCTION", "add", "*", rule_create_function_add),
    SafetyRule("CREATE_DICT", "add", "clickhouse", rule_create_dict_add),

    # DROP 规则
    SafetyRule("DROP_TABLE", "remove", "*", rule_drop_table_remove),
    SafetyRule("DROP_INDEX", "remove", "*", rule_drop_index_remove),
    SafetyRule("DROP_VIEW", "remove", "*", rule_drop_view_remove),
    SafetyRule("DROP_FUNCTION", "remove", "*", rule_drop_function_remove),
    SafetyRule("DROP_DICT", "remove", "clickhouse", rule_drop_dict_remove),

    # ALTER TABLE 规则
    SafetyRule("ALTER_TABLE", "add", "postgres", rule_alter_add_column),
    SafetyRule("ALTER_TABLE", "remove", "postgres", rule_alter_drop_column),
    SafetyRule("ALTER_TABLE", "modify", "*", rule_alter_modify_column),

    # DML 规则
    SafetyRule("INSERT", "add", "*", rule_insert_add),
    SafetyRule("UPDATE", "add", "*", rule_update_add),
    SafetyRule("UPDATE", "remove", "*", rule_update_remove),
    SafetyRule("DELETE", "add", "*", rule_delete_add),
    SafetyRule("DELETE", "remove", "*", rule_delete_remove),
]


# ─────────────────────────────────────────────
# 规则应用引擎
# ─────────────────────────────────────────────

def apply_safety_rules(change: Change, db_type: str) -> Optional[str]:
    """
    应用安全规则，生成安全的 SQL 语句。

    Args:
        change: 变动对象
        db_type: 数据库类型（postgres、clickhouse）

    Returns:
        安全的 SQL 语句，或 None（表示跳过）
    """
    # 查找匹配的规则
    matching_rules = [
        rule for rule in SAFETY_RULES
        if rule.stmt_type == change.stmt_type
        and rule.action == change.action
        and (rule.db_type == "*" or rule.db_type == db_type)
    ]

    if not matching_rules:
        # 没有匹配的规则，直接输出原语句
        if change.action == "add" and change.new_stmt:
            return change.new_stmt.raw_sql.strip().rstrip(";") + ";"
        elif change.action == "remove" and change.old_stmt:
            return change.old_stmt.raw_sql.strip().rstrip(";") + ";"
        elif change.action == "modify" and change.new_stmt:
            return change.new_stmt.raw_sql.strip().rstrip(";") + ";"
        return None

    # 应用第一个匹配的规则
    rule = matching_rules[0]
    try:
        result = rule.rule_func(change, db_type)
        return result
    except Exception as e:
        print(f"  [ERROR] 规则应用失败 ({rule.stmt_type}/{rule.action}): {e}", flush=True)
        return None


def apply_safety_rules_batch(changes: List[Change], db_type: str) -> Dict[str, Any]:
    """
    批量应用安全规则。

    Args:
        changes: 变动列表
        db_type: 数据库类型

    Returns:
        包含 safe_sqls 和 skipped 的字典
    """
    safe_sqls = []
    skipped = []

    for change in changes:
        safe_sql = apply_safety_rules(change, db_type)

        if safe_sql is None:
            skipped.append({
                'change': change,
                'reason': '规则应用返回 None'
            })
        else:
            safe_sqls.append({
                'sql': safe_sql,
                'change': change
            })

    return {
        'safe_sqls': safe_sqls,
        'skipped': skipped
    }
