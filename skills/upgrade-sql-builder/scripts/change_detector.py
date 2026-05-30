#!/usr/bin/env python3
"""
change_detector.py - 变动检测模块，基于 sqlglot diff

识别新增、删除、修改三类变动，提取细粒度差异信息。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from sql_parser import (
    SQLStatement, parse_sql_file, get_sql_diff, extract_diff_details,
    parse_alter_table, normalize_statement
)


# ─────────────────────────────────────────────
# 数据类定义
# ─────────────────────────────────────────────

@dataclass
class Change:
    """SQL 变动的结构化表示"""
    action: str  # "add" | "remove" | "modify"
    stmt_type: str  # CREATE_TABLE, ALTER_TABLE, DROP_TABLE, etc.
    object_name: str  # 对象名
    old_stmt: Optional[SQLStatement] = None  # 旧版本语句（modify 时有值）
    new_stmt: Optional[SQLStatement] = None  # 新版本语句（modify 时有值）
    diff_details: Dict[str, Any] = field(default_factory=dict)  # sqlglot diff 结果详情
    details: Dict[str, Any] = field(default_factory=dict)  # 高层语义变动信息
    source_file: str = ""  # 来源文件路径


# ─────────────────────────────────────────────
# 变动检测函数
# ─────────────────────────────────────────────

def detect_changes(
    old_stmts: List[SQLStatement],
    new_stmts: List[SQLStatement],
    dialect: str = "postgres"
) -> List[Change]:
    """
    比较旧版本和新版本 SQL，返回变动列表。

    Args:
        old_stmts: 旧版本语句列表
        new_stmts: 新版本语句列表
        dialect: 数据库方言

    Returns:
        Change 对象列表
    """
    changes = []

    # 按对象名和类型建立映射
    old_map = _build_stmt_map(old_stmts)
    new_map = _build_stmt_map(new_stmts)

    # 检测新增和修改
    for key, new_stmt in new_map.items():
        if key not in old_map:
            # 新增
            change = Change(
                action="add",
                stmt_type=new_stmt.type,
                object_name=new_stmt.object_name,
                new_stmt=new_stmt,
                details={}
            )
            changes.append(change)
        else:
            # 可能是修改
            old_stmt = old_map[key]
            diff_result = get_sql_diff(old_stmt.raw_sql, new_stmt.raw_sql, dialect)

            if 'error' not in diff_result:
                # 检查是否真的有差异
                old_normalized = normalize_statement(old_stmt)
                new_normalized = normalize_statement(new_stmt)

                if old_normalized != new_normalized:
                    # 修改
                    diff_details = extract_diff_details(old_stmt, new_stmt, dialect)
                    change = Change(
                        action="modify",
                        stmt_type=new_stmt.type,
                        object_name=new_stmt.object_name,
                        old_stmt=old_stmt,
                        new_stmt=new_stmt,
                        diff_details=diff_result,
                        details=diff_details
                    )
                    changes.append(change)

    # 检测删除
    for key, old_stmt in old_map.items():
        if key not in new_map:
            # 删除
            change = Change(
                action="remove",
                stmt_type=old_stmt.type,
                object_name=old_stmt.object_name,
                old_stmt=old_stmt,
                details={}
            )
            changes.append(change)

    return changes


def _build_stmt_map(stmts: List[SQLStatement]) -> Dict[str, SQLStatement]:
    """
    按 (type, object_name) 建立语句映射。

    用于快速查找和对比。
    """
    stmt_map = {}
    for stmt in stmts:
        key = (stmt.type, stmt.object_name)
        stmt_map[key] = stmt
    return stmt_map


# ─────────────────────────────────────────────
# 字段级变动检测
# ─────────────────────────────────────────────

def detect_column_changes(
    old_stmt: SQLStatement,
    new_stmt: SQLStatement,
    dialect: str = "postgres"
) -> Dict[str, Any]:
    """
    检测字段级变动（新增、删除、修改）。

    Args:
        old_stmt: 旧版本 CREATE TABLE 语句
        new_stmt: 新版本 CREATE TABLE 语句
        dialect: 数据库方言

    Returns:
        包含 added_columns、removed_columns、modified_columns 的字典
    """
    changes = {
        'added_columns': [],
        'removed_columns': [],
        'modified_columns': []
    }

    if old_stmt.type != "CREATE_TABLE" or new_stmt.type != "CREATE_TABLE":
        return changes

    try:
        old_cols = old_stmt.metadata.get('columns', [])
        new_cols = new_stmt.metadata.get('columns', [])

        old_col_map = {col['name']: col for col in old_cols}
        new_col_map = {col['name']: col for col in new_cols}

        # 新增列
        for col_name, col_info in new_col_map.items():
            if col_name not in old_col_map:
                changes['added_columns'].append(col_info)

        # 删除列
        for col_name, col_info in old_col_map.items():
            if col_name not in new_col_map:
                changes['removed_columns'].append(col_info)

        # 修改列
        for col_name in old_col_map:
            if col_name in new_col_map:
                old_col = old_col_map[col_name]
                new_col = new_col_map[col_name]

                # 比较类型和约束
                type_changed = old_col.get('type') != new_col.get('type')
                constraints_changed = old_col.get('constraints') != new_col.get('constraints')

                if type_changed or constraints_changed:
                    changes['modified_columns'].append({
                        'name': col_name,
                        'old': old_col,
                        'new': new_col,
                        'type_changed': type_changed,
                        'constraints_changed': constraints_changed
                    })

    except Exception as e:
        print(f"[WARN] 字段变动检测失败: {e}")

    return changes


# ─────────────────────────────────────────────
# 索引级变动检测
# ─────────────────────────────────────────────

def detect_index_changes(
    old_stmts: List[SQLStatement],
    new_stmts: List[SQLStatement],
    dialect: str = "postgres"
) -> Dict[str, Any]:
    """
    检测索引级变动（新增、删除、修改）。

    Args:
        old_stmts: 旧版本语句列表
        new_stmts: 新版本语句列表
        dialect: 数据库方言

    Returns:
        包含 added_indexes、removed_indexes、modified_indexes 的字典
    """
    changes = {
        'added_indexes': [],
        'removed_indexes': [],
        'modified_indexes': []
    }

    try:
        # 提取索引语句
        old_indexes = {stmt.object_name: stmt for stmt in old_stmts if stmt.type == "CREATE_INDEX"}
        new_indexes = {stmt.object_name: stmt for stmt in new_stmts if stmt.type == "CREATE_INDEX"}

        # 新增索引
        for idx_name, idx_stmt in new_indexes.items():
            if idx_name not in old_indexes:
                changes['added_indexes'].append({
                    'name': idx_name,
                    'columns': idx_stmt.metadata.get('columns', []),
                    'sql': idx_stmt.raw_sql
                })

        # 删除索引
        for idx_name, idx_stmt in old_indexes.items():
            if idx_name not in new_indexes:
                changes['removed_indexes'].append({
                    'name': idx_name,
                    'columns': idx_stmt.metadata.get('columns', []),
                    'sql': idx_stmt.raw_sql
                })

        # 修改索引
        for idx_name in old_indexes:
            if idx_name in new_indexes:
                old_idx = old_indexes[idx_name]
                new_idx = new_indexes[idx_name]

                old_cols = old_idx.metadata.get('columns', [])
                new_cols = new_idx.metadata.get('columns', [])

                if old_cols != new_cols:
                    changes['modified_indexes'].append({
                        'name': idx_name,
                        'old_columns': old_cols,
                        'new_columns': new_cols,
                        'old_sql': old_idx.raw_sql,
                        'new_sql': new_idx.raw_sql
                    })

    except Exception as e:
        print(f"[WARN] 索引变动检测失败: {e}")

    return changes


# ─────────────────────────────────────────────
# 约束级变动检测
# ─────────────────────────────────────────────

def detect_constraint_changes(
    old_stmts: List[SQLStatement],
    new_stmts: List[SQLStatement],
    dialect: str = "postgres"
) -> Dict[str, Any]:
    """
    检测约束级变动（新增、删除、修改）。

    Args:
        old_stmts: 旧版本语句列表
        new_stmts: 新版本语句列表
        dialect: 数据库方言

    Returns:
        包含 added_constraints、removed_constraints、modified_constraints 的字典
    """
    changes = {
        'added_constraints': [],
        'removed_constraints': [],
        'modified_constraints': []
    }

    try:
        # 从 CREATE TABLE 语句中提取约束
        old_constraints = _extract_constraints_from_stmts(old_stmts)
        new_constraints = _extract_constraints_from_stmts(new_stmts)

        # 新增约束
        for constraint_key, constraint_info in new_constraints.items():
            if constraint_key not in old_constraints:
                changes['added_constraints'].append(constraint_info)

        # 删除约束
        for constraint_key, constraint_info in old_constraints.items():
            if constraint_key not in new_constraints:
                changes['removed_constraints'].append(constraint_info)

        # 修改约束
        for constraint_key in old_constraints:
            if constraint_key in new_constraints:
                old_constraint = old_constraints[constraint_key]
                new_constraint = new_constraints[constraint_key]

                if old_constraint != new_constraint:
                    changes['modified_constraints'].append({
                        'key': constraint_key,
                        'old': old_constraint,
                        'new': new_constraint
                    })

    except Exception as e:
        print(f"[WARN] 约束变动检测失败: {e}")

    return changes


def _extract_constraints_from_stmts(stmts: List[SQLStatement]) -> Dict[str, Any]:
    """从语句列表中提取所有约束"""
    constraints = {}

    for stmt in stmts:
        if stmt.type == "CREATE_TABLE":
            # 从表的列定义中提取约束
            columns = stmt.metadata.get('columns', [])
            for col in columns:
                col_constraints = col.get('constraints', [])
                for constraint in col_constraints:
                    key = (stmt.object_name, col['name'], constraint)
                    constraints[key] = {
                        'table': stmt.object_name,
                        'column': col['name'],
                        'constraint': constraint
                    }

    return constraints


# ─────────────────────────────────────────────
# ALTER TABLE 操作检测
# ─────────────────────────────────────────────

def detect_alter_operations(
    old_stmts: List[SQLStatement],
    new_stmts: List[SQLStatement],
    dialect: str = "postgres"
) -> List[Dict[str, Any]]:
    """
    检测 ALTER TABLE 操作。

    Args:
        old_stmts: 旧版本语句列表
        new_stmts: 新版本语句列表
        dialect: 数据库方言

    Returns:
        ALTER 操作列表
    """
    operations = []

    try:
        # 提取 ALTER TABLE 语句
        old_alters = {stmt.object_name: stmt for stmt in old_stmts if stmt.type == "ALTER_TABLE"}
        new_alters = {stmt.object_name: stmt for stmt in new_stmts if stmt.type == "ALTER_TABLE"}

        # 处理新增的 ALTER
        for table_name, alter_stmt in new_alters.items():
            alter_ops = parse_alter_table(alter_stmt)
            for op in alter_ops:
                operations.append({
                    'action': 'add',
                    'table': table_name,
                    'operation': op.operation_type,
                    'column': op.column_name,
                    'type': op.column_type,
                    'constraint_info': op.constraint_info,
                    'raw_sql': op.raw_sql
                })

        # 处理删除的 ALTER
        for table_name, alter_stmt in old_alters.items():
            if table_name not in new_alters:
                alter_ops = parse_alter_table(alter_stmt)
                for op in alter_ops:
                    operations.append({
                        'action': 'remove',
                        'table': table_name,
                        'operation': op.operation_type,
                        'column': op.column_name,
                        'type': op.column_type,
                        'constraint_info': op.constraint_info,
                        'raw_sql': op.raw_sql
                    })

    except Exception as e:
        print(f"[WARN] ALTER TABLE 操作检测失败: {e}")

    return operations


# ─────────────────────────────────────────────
# 综合变动分析
# ─────────────────────────────────────────────

def analyze_changes(
    old_content: str,
    new_content: str,
    dialect: str = "postgres",
    source_file: str = ""
) -> List[Change]:
    """
    完整的变动分析流程。

    Args:
        old_content: 旧版本 SQL 文件内容
        new_content: 新版本 SQL 文件内容
        dialect: 数据库方言
        source_file: 来源文件路径

    Returns:
        Change 对象列表
    """
    # 解析 SQL 文件
    old_stmts = parse_sql_file(old_content, dialect)
    new_stmts = parse_sql_file(new_content, dialect)

    # 检测基础变动
    changes = detect_changes(old_stmts, new_stmts, dialect)

    # 为每个变动添加来源文件信息
    for change in changes:
        change.source_file = source_file

    # 对于 CREATE_TABLE 的修改，检测字段级变动
    for change in changes:
        if change.action == "modify" and change.stmt_type == "CREATE_TABLE":
            change.details.update(detect_column_changes(change.old_stmt, change.new_stmt, dialect))

    # 检测索引级变动
    index_changes = detect_index_changes(old_stmts, new_stmts, dialect)
    if any(index_changes.values()):
        # 创建虚拟 Change 对象表示索引变动
        for added_idx in index_changes['added_indexes']:
            changes.append(Change(
                action="add",
                stmt_type="CREATE_INDEX",
                object_name=added_idx['name'],
                details=added_idx,
                source_file=source_file
            ))
        for removed_idx in index_changes['removed_indexes']:
            changes.append(Change(
                action="remove",
                stmt_type="DROP_INDEX",
                object_name=removed_idx['name'],
                details=removed_idx,
                source_file=source_file
            ))
        for modified_idx in index_changes['modified_indexes']:
            changes.append(Change(
                action="modify",
                stmt_type="CREATE_INDEX",
                object_name=modified_idx['name'],
                details=modified_idx,
                source_file=source_file
            ))

    # 检测约束级变动
    constraint_changes = detect_constraint_changes(old_stmts, new_stmts, dialect)
    if any(constraint_changes.values()):
        for added_constraint in constraint_changes['added_constraints']:
            changes.append(Change(
                action="add",
                stmt_type="ADD_CONSTRAINT",
                object_name=f"{added_constraint['table']}.{added_constraint['constraint']}",
                details=added_constraint,
                source_file=source_file
            ))
        for removed_constraint in constraint_changes['removed_constraints']:
            changes.append(Change(
                action="remove",
                stmt_type="DROP_CONSTRAINT",
                object_name=f"{removed_constraint['table']}.{removed_constraint['constraint']}",
                details=removed_constraint,
                source_file=source_file
            ))

    return changes
