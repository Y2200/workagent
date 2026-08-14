"""
迁移：用户资料字段 + 企微绑定唯一约束

1. users 加 real_name 列（幂等）
2. 存量回填：real_name = username（管理员后续可编辑）
3. wechat_user_id 部分唯一索引（先查重，无重复才建；有重复打警告跳过）

幂等，可重复执行。用法：
    python -m work_agent.scripts.migrate_user_profile
"""

from sqlalchemy import text

from work_agent.db.session import engine


def migrate():

    with engine.begin() as conn:

        # 1) real_name 列（幂等）
        conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS real_name VARCHAR(64) DEFAULT ''"
            )
        )

        # 2) 存量回填
        conn.execute(
            text(
                "UPDATE users SET real_name = username "
                "WHERE real_name IS NULL OR real_name = ''"
            )
        )

        # 3) 查重 wechat_user_id
        dupes = conn.execute(
            text(
                "SELECT wechat_user_id, count(*) FROM users "
                "WHERE wechat_user_id IS NOT NULL "
                "GROUP BY wechat_user_id HAVING count(*) > 1"
            )
        ).fetchall()

        if dupes:

            print(
                f"⚠️ 存在重复 wechat_user_id {len(dupes)} 组，"
                "跳过建唯一索引；请先人工去重后重跑本脚本"
            )

            for row in dupes:

                print(
                    f"  重复: {row[0]} × {row[1]}"
                )

        else:

            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_users_wechat_user_id_unique "
                    "ON users (wechat_user_id) "
                    "WHERE wechat_user_id IS NOT NULL"
                )
            )

            print(
                "已创建部分唯一索引：ix_users_wechat_user_id_unique "
                "（1 企微号 ↔ 1 用户）"
            )

    print(
        "迁移完成：users.real_name 列 + 企微绑定唯一约束"
    )


if __name__ == "__main__":

    migrate()
