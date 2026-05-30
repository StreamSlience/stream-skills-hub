#!/usr/bin/env python3
"""
sql_parser.py - SQL 解析模块，基于 sqlglot 库

提供 SQL 文件解析、AST 操作、diff 对比等功能。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
import sqlglot
from sqlglot import exp, parse_one
from sqlglot.diff import diff as sqlglot_diff


# ─────────────────────────────────────────────
# 数据类定义
# ─────────────────────────────────────────────

@dataclass
class SQLStatement:
    """SQL 语句的结构化表示"""
    type: str  # CREATE_TABLE, ALTER_TABLE, DROP_TABLE, etc.
    object_name: str  # 对象名（表名、索引名等）
    raw_sql: str  # 原始 SQL 文本
    ast: Optional[exp.Expression] = None  # sqlglot AST 对象
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外信息


@dataclass
class AlterTableOperation:
    """ALTER TABLE 的单个原子操作"""
    operation_type: str  # ADD_COLUMN, DROP_COLUMN, MODIFY_COLUMN, ADD_CONSTRAINT, DROP_CONSTRAINT, RENAME
    table_name: str
    column_name: Optional[str] = None  # 列名（如适用）
    column_type: Optional[str] = None  # 列类型（如适用）
    constraint_info: Optional[Dict[str, Any]] = None  # 约束信息（如适用）
    raw_sql: str = ""  # 原始 ALTER 语句片段
    ast_node: Optional[exp.Expression] = None  # sqlglot AST 节点


# ─────────────────────────────────────────────
# SQL 解析函数
# ─────────────────────────────────────────────

def parse_sql_file(content: str, dialect: str = "postgres") -> List[SQLStatement]:
    """
    解析完整 SQL 文件为语句列表。

    Args:
        content: SQL 文件内容
        dialect: 数据库方言（"postgres" 或 "clickhouse"）

    Returns:
        SQLStatement 对象列表
    """
    if not content.strip():
        return []

    try:
        # 使用 sqlglot 解析 SQL
        statements = sqlglot.parse(content, dialect=dialect)
    except Exception as e:
        print(f"[WARN] SQL 解析失败: {e}")
        return []

    result = []
    for ast_node in statements:
        if ast_node is None:
            continue

        stmt_type = _classify_statement_type(ast_node)
        object_name = extract_object_name(ast_node)
        raw_sql = ast_node.sql(dialect=dialect)

        stmt = SQLStatement(
            type=stmt_type,
            object_name=object_name,
            raw_sql=raw_sql,
            ast=ast_node,
            metadata=_extract_metadata(ast_node, dialect)
        )
        result.append(stmt)

    return result


# ─────────────────────────────────────────────
# 语句分类注册表
# ─────────────────────────────────────────────

class StatementClassifier:
    """可扩展的 SQL 语句分类器"""

    def __init__(self):
        self._classifiers = []

    def register(self, predicate, stmt_type: str):
        """
        注册分类规则。

        Args:
            predicate: 函数，接收 ast_node，返回 bool
            stmt_type: 语句类型字符串
        """
        self._classifiers.append((predicate, stmt_type))
        return self

    def classify(self, ast_node: exp.Expression) -> str:
        """根据注册的规则分类语句"""
        for predicate, stmt_type in self._classifiers:
            try:
                if predicate(ast_node):
                    return stmt_type
            except Exception:
                continue
        return "OTHER"


# 全局分类器实例
_statement_classifier = StatementClassifier()

# 注册 CREATE 语句分类规则
_statement_classifier.register(
    lambda node: isinstance(node, exp.Create) and isinstance(node.expression, exp.Table),
    "CREATE_TABLE"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Create) and isinstance(node.expression, exp.Index),
    "CREATE_INDEX"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Create) and isinstance(node.expression, exp.View),
    "CREATE_VIEW"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Create) and "DICTIONARY" in node.sql().upper(),
    "CREATE_DICT"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Create),
    "CREATE_FUNCTION"
)

# 注册 DROP 语句分类规则
_statement_classifier.register(
    lambda node: isinstance(node, exp.Drop) and node.kind == "TABLE",
    "DROP_TABLE"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Drop) and node.kind == "INDEX",
    "DROP_INDEX"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Drop) and node.kind == "VIEW",
    "DROP_VIEW"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Drop) and node.kind == "DICTIONARY",
    "DROP_DICT"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Drop),
    "DROP_FUNCTION"
)

# 注册 DML 语句分类规则
_statement_classifier.register(
    lambda node: isinstance(node, exp.Alter),
    "ALTER_TABLE"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Insert),
    "INSERT"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Update),
    "UPDATE"
)
_statement_classifier.register(
    lambda node: isinstance(node, exp.Delete),
    "DELETE"
)


def _classify_statement_type(ast_node: exp.Expression) -> str:
    """根据 AST 节点类型分类 SQL 语句（使用注册表）"""
    return _statement_classifier.classify(ast_node)


def extract_object_name(ast_node: exp.Expression) -> str:
    """
    从 AST 节点中提取对象名。

    支持格式：
    - 简单名：users
    - 带引号："users"、`users`
    - 带 schema：public.users、"public"."users"
    """
    try:
        if isinstance(ast_node, exp.Create):
            # CREATE TABLE/INDEX/VIEW
            if hasattr(ast_node, 'this') and ast_node.this:
                return normalize_object_name(ast_node.this.name)

        elif isinstance(ast_node, exp.Drop):
            # DROP TABLE/INDEX/VIEW
            if hasattr(ast_node, 'this') and ast_node.this:
                return normalize_object_name(ast_node.this.name)

        elif isinstance(ast_node, exp.Alter):
            # ALTER TABLE
            if hasattr(ast_node, 'this') and ast_node.this:
                return normalize_object_name(ast_node.this.name)

        elif isinstance(ast_node, exp.Insert):
            # INSERT INTO
            if hasattr(ast_node, 'this') and ast_node.this:
                return normalize_object_name(ast_node.this.name)

        elif isinstance(ast_node, exp.Update):
            # UPDATE
            if hasattr(ast_node, 'this') and ast_node.this:
                return normalize_object_name(ast_node.this.name)

        elif isinstance(ast_node, exp.Delete):
            # DELETE FROM
            if hasattr(ast_node, 'this') and ast_node.this:
                return normalize_object_name(ast_node.this.name)

    except Exception as e:
        print(f"[WARN] 对象名提取失败: {e}")

    return ""


def normalize_object_name(name: str) -> str:
    """
    规范化对象名，统一格式用于比较。

    - 移除引号
    - 转换为小写（可选，取决于数据库）
    - 保留 schema 前缀
    """
    if not name:
        return ""

    # 移除引号
    name = name.strip('"').strip("'").strip("`")

    # 保留原始大小写（不转换为小写，以保持准确性）
    return name


def _extract_metadata(ast_node: exp.Expression, dialect: str) -> Dict[str, Any]:
    """从 AST 节点中提取元数据"""
    metadata = {}

    try:
        if isinstance(ast_node, exp.Create) and isinstance(ast_node.expression, exp.Table):
            # 提取表的列定义
            table_expr = ast_node.expression
            if hasattr(table_expr, 'expressions'):
                columns = []
                for col_def in table_expr.expressions:
                    if isinstance(col_def, exp.ColumnDef):
                        columns.append({
                            'name': col_def.name,
                            'type': col_def.kind.sql(dialect=dialect) if col_def.kind else None,
                            'constraints': _extract_column_constraints(col_def)
                        })
                metadata['columns'] = columns

        elif isinstance(ast_node, exp.Create) and isinstance(ast_node.expression, exp.Index):
            # 提取索引信息
            index_expr = ast_node.expression
            metadata['index_name'] = index_expr.name
            if hasattr(index_expr, 'expressions'):
                metadata['columns'] = [col.name for col in index_expr.expressions]

    except Exception as e:
        print(f"[WARN] 元数据提取失败: {e}")

    return metadata


def _extract_column_constraints(col_def: exp.ColumnDef) -> List[str]:
    """提取列的约束信息"""
    constraints = []
    try:
        if hasattr(col_def, 'constraints'):
            for constraint in col_def.constraints:
                if isinstance(constraint, exp.NotNull):
                    constraints.append("NOT NULL")
                elif isinstance(constraint, exp.Unique):
                    constraints.append("UNIQUE")
                elif isinstance(constraint, exp.PrimaryKey):
                    constraints.append("PRIMARY KEY")
                elif isinstance(constraint, exp.ForeignKey):
                    constraints.append("FOREIGN KEY")
    except Exception:
        pass

    return constraints


def normalize_statement(stmt: SQLStatement) -> str:
    """
    规范化语句用于比较。

    - 移除注释
    - 统一空白
    - 转换为标准格式
    """
    if stmt.ast:
        try:
            # 使用 sqlglot 生成规范化的 SQL
            return stmt.ast.sql(pretty=False, normalize=True)
        except Exception:
            pass

    # 备选方案：直接规范化原始 SQL
    import re
    sql = stmt.raw_sql
    # 移除注释
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # 合并空白
    sql = re.sub(r"\s+", " ", sql).strip()
    return sql


# ─────────────────────────────────────────────
# SQL Diff 函数
# ─────────────────────────────────────────────

def get_sql_diff(old_sql: str, new_sql: str, dialect: str = "postgres") -> Dict[str, Any]:
    """
    使用 sqlglot.diff 对比两个 SQL 语句的 AST。

    Args:
        old_sql: 旧版本 SQL
        new_sql: 新版本 SQL
        dialect: 数据库方言

    Returns:
        差异信息字典，包含 added_nodes、removed_nodes、modified_nodes
    """
    try:
        old_ast = parse_one(old_sql, dialect=dialect)
        new_ast = parse_one(new_sql, dialect=dialect)

        if old_ast is None or new_ast is None:
            return {'error': 'Failed to parse SQL'}

        # 使用 sqlglot.diff 获取差异
        diff_result = sqlglot_diff(old_ast, new_ast)

        return {
            'old_ast': old_ast,
            'new_ast': new_ast,
            'diff': diff_result,
            'added_nodes': _extract_diff_nodes(diff_result, 'added'),
            'removed_nodes': _extract_diff_nodes(diff_result, 'removed'),
            'modified_nodes': _extract_diff_nodes(diff_result, 'modified')
        }

    except Exception as e:
        print(f"[WARN] SQL diff 失败: {e}")
        return {'error': str(e)}


def _extract_diff_nodes(diff_result: Any, node_type: str) -> List[Dict[str, Any]]:
    """从 diff 结果中提取特定类型的节点"""
    nodes = []
    try:
        if hasattr(diff_result, node_type):
            node_list = getattr(diff_result, node_type)
            for node in node_list:
                nodes.append({
                    'type': type(node).__name__,
                    'sql': node.sql() if hasattr(node, 'sql') else str(node),
                    'node': node
                })
    except Exception:
        pass

    return nodes


def extract_column_diff(old_ast: exp.Expression, new_ast: exp.Expression) -> Dict[str, Any]:
    """
    从 CREATE TABLE AST 中提取列级差异。

    Args:
        old_ast: 旧版本 AST
        new_ast: 新版本 AST

    Returns:
        包含列级变动的字典
    """
    changes = {
        'added_columns': [],
        'removed_columns': [],
        'modified_columns': []
    }

    try:
        # 提取旧版本的列定义
        old_columns = _extract_columns_from_ast(old_ast)
        new_columns = _extract_columns_from_ast(new_ast)

        old_col_map = {col['name']: col for col in old_columns}
        new_col_map = {col['name']: col for col in new_columns}

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
                if old_col != new_col:
                    changes['modified_columns'].append({
                        'name': col_name,
                        'old': old_col,
                        'new': new_col,
                        'type_changed': old_col.get('type') != new_col.get('type'),
                        'constraints_changed': old_col.get('constraints') != new_col.get('constraints')
                    })

    except Exception as e:
        print(f"[WARN] 列级差异提取失败: {e}")

    return changes


def _extract_columns_from_ast(ast: exp.Expression) -> List[Dict[str, Any]]:
    """从 CREATE TABLE AST 中提取列定义列表"""
    columns = []

    try:
        if isinstance(ast, exp.Create):
            table_expr = ast.expression
            if isinstance(table_expr, exp.Table) and hasattr(table_expr, 'expressions'):
                for col_def in table_expr.expressions:
                    if isinstance(col_def, exp.ColumnDef):
                        col_info = {
                            'name': col_def.name,
                            'type': col_def.kind.sql() if col_def.kind else None,
                            'constraints': _extract_column_constraints(col_def),
                            'default': col_def.args.get('default') if hasattr(col_def, 'args') else None
                        }
                        columns.append(col_info)

    except Exception as e:
        print(f"[WARN] 列提取失败: {e}")

    return columns


def extract_index_diff(old_ast: exp.Expression, new_ast: exp.Expression) -> Dict[str, Any]:
    """
    从 CREATE INDEX AST 中提取索引级差异。

    Args:
        old_ast: 旧版本 AST
        new_ast: 新版本 AST

    Returns:
        包含索引变动的字典
    """
    changes = {
        'columns_changed': False,
        'old_columns': [],
        'new_columns': []
    }

    try:
        old_cols = _extract_index_columns_from_ast(old_ast)
        new_cols = _extract_index_columns_from_ast(new_ast)

        changes['old_columns'] = old_cols
        changes['new_columns'] = new_cols
        changes['columns_changed'] = old_cols != new_cols

    except Exception as e:
        print(f"[WARN] 索引差异提取失败: {e}")

    return changes


def _extract_index_columns_from_ast(ast: exp.Expression) -> List[str]:
    """从 CREATE INDEX AST 中提取索引列"""
    columns = []

    try:
        if isinstance(ast, exp.Create):
            index_expr = ast.expression
            if isinstance(index_expr, exp.Index) and hasattr(index_expr, 'expressions'):
                for expr in index_expr.expressions:
                    if isinstance(expr, exp.Column):
                        columns.append(expr.name)
                    elif isinstance(expr, exp.Identifier):
                        columns.append(expr.name)
                    else:
                        columns.append(expr.sql())

    except Exception as e:
        print(f"[WARN] 索引列提取失败: {e}")

    return columns


def extract_diff_details(old_stmt: SQLStatement, new_stmt: SQLStatement, dialect: str = "postgres") -> Dict[str, Any]:
    """
    从 diff 结果中提取高层语义信息。

    识别字段类型变更、约束变更、索引变更等。
    """
    diff_result = get_sql_diff(old_stmt.raw_sql, new_stmt.raw_sql, dialect)

    if 'error' in diff_result:
        return {'error': diff_result['error']}

    details = {
        'added_columns': [],
        'removed_columns': [],
        'modified_columns': [],
        'added_indexes': [],
        'removed_indexes': [],
        'modified_indexes': [],
        'added_constraints': [],
        'removed_constraints': [],
        'modified_constraints': []
    }

    try:
        # 提取列级变动
        if old_stmt.type == "CREATE_TABLE" and new_stmt.type == "CREATE_TABLE":
            details.update(_detect_column_changes(old_stmt, new_stmt, dialect))

        # 提取索引级变动
        if old_stmt.type == "CREATE_INDEX" and new_stmt.type == "CREATE_INDEX":
            details.update(_detect_index_changes(old_stmt, new_stmt, dialect))

    except Exception as e:
        print(f"[WARN] 差异详情提取失败: {e}")

    return details


def _detect_column_changes(old_stmt: SQLStatement, new_stmt: SQLStatement, dialect: str) -> Dict[str, Any]:
    """检测列级变动"""
    changes = {
        'added_columns': [],
        'removed_columns': [],
        'modified_columns': []
    }

    try:
        old_cols = old_stmt.metadata.get('columns', [])
        new_cols = new_stmt.metadata.get('columns', [])

        old_col_names = {col['name']: col for col in old_cols}
        new_col_names = {col['name']: col for col in new_cols}

        # 新增列
        for col_name, col_info in new_col_names.items():
            if col_name not in old_col_names:
                changes['added_columns'].append(col_info)

        # 删除列
        for col_name, col_info in old_col_names.items():
            if col_name not in new_col_names:
                changes['removed_columns'].append(col_info)

        # 修改列
        for col_name in old_col_names:
            if col_name in new_col_names:
                old_col = old_col_names[col_name]
                new_col = new_col_names[col_name]
                if old_col != new_col:
                    changes['modified_columns'].append({
                        'name': col_name,
                        'old': old_col,
                        'new': new_col
                    })

    except Exception as e:
        print(f"[WARN] 列变动检测失败: {e}")

    return changes


def _detect_index_changes(old_stmt: SQLStatement, new_stmt: SQLStatement, dialect: str) -> Dict[str, Any]:
    """检测索引级变动"""
    changes = {
        'added_indexes': [],
        'removed_indexes': [],
        'modified_indexes': []
    }

    try:
        old_cols = old_stmt.metadata.get('columns', [])
        new_cols = new_stmt.metadata.get('columns', [])

        if old_cols != new_cols:
            changes['modified_indexes'].append({
                'old_columns': old_cols,
                'new_columns': new_cols
            })

    except Exception as e:
        print(f"[WARN] 索引变动检测失败: {e}")

    return changes


# ─────────────────────────────────────────────
# ALTER TABLE 拆分函数
# ─────────────────────────────────────────────

def parse_alter_table(stmt: SQLStatement) -> List[AlterTableOperation]:
    """
    将 ALTER TABLE 语句拆分为原子操作。

    Args:
        stmt: ALTER TABLE 语句

    Returns:
        AlterTableOperation 列表
    """
    operations = []

    if stmt.type != "ALTER_TABLE" or stmt.ast is None:
        return operations

    try:
        alter_node = stmt.ast
        table_name = stmt.object_name

        if isinstance(alter_node, exp.Alter):
            # 遍历 ALTER 的操作
            if hasattr(alter_node, 'actions'):
                for action in alter_node.actions:
                    op = _parse_alter_action(action, table_name, alter_node.sql())
                    if op:
                        operations.append(op)

    except Exception as e:
        print(f"[WARN] ALTER TABLE 拆分失败: {e}")

    return operations


def _parse_alter_action(action: exp.Expression, table_name: str, raw_sql: str) -> Optional[AlterTableOperation]:
    """解析单个 ALTER 操作"""
    try:
        if isinstance(action, exp.Add):
            # ADD COLUMN / ADD CONSTRAINT
            if hasattr(action, 'expressions'):
                for expr in action.expressions:
                    if isinstance(expr, exp.ColumnDef):
                        return AlterTableOperation(
                            operation_type="ADD_COLUMN",
                            table_name=table_name,
                            column_name=expr.name,
                            column_type=expr.kind.sql() if expr.kind else None,
                            constraint_info={'constraints': _extract_column_constraints(expr)},
                            raw_sql=raw_sql,
                            ast_node=action
                        )
                    elif isinstance(expr, exp.Constraint):
                        return AlterTableOperation(
                            operation_type="ADD_CONSTRAINT",
                            table_name=table_name,
                            constraint_info={'constraint': expr.sql()},
                            raw_sql=raw_sql,
                            ast_node=action
                        )

        elif isinstance(action, exp.Drop):
            # DROP COLUMN / DROP CONSTRAINT
            if hasattr(action, 'expressions'):
                for expr in action.expressions:
                    if isinstance(expr, exp.Column):
                        return AlterTableOperation(
                            operation_type="DROP_COLUMN",
                            table_name=table_name,
                            column_name=expr.name,
                            raw_sql=raw_sql,
                            ast_node=action
                        )
                    elif isinstance(expr, exp.Constraint):
                        return AlterTableOperation(
                            operation_type="DROP_CONSTRAINT",
                            table_name=table_name,
                            constraint_info={'constraint': expr.sql()},
                            raw_sql=raw_sql,
                            ast_node=action
                        )

        elif isinstance(action, exp.Modify):
            # MODIFY COLUMN
            if hasattr(action, 'expressions'):
                for expr in action.expressions:
                    if isinstance(expr, exp.ColumnDef):
                        return AlterTableOperation(
                            operation_type="MODIFY_COLUMN",
                            table_name=table_name,
                            column_name=expr.name,
                            column_type=expr.kind.sql() if expr.kind else None,
                            constraint_info={'constraints': _extract_column_constraints(expr)},
                            raw_sql=raw_sql,
                            ast_node=action
                        )

        elif isinstance(action, exp.Rename):
            # RENAME COLUMN / RENAME TABLE
            return AlterTableOperation(
                operation_type="RENAME",
                table_name=table_name,
                raw_sql=raw_sql,
                ast_node=action
            )

    except Exception as e:
        print(f"[WARN] ALTER 操作解析失败: {e}")

    return None
