"""Seed a realistic demo dataset into a scratch copy of the app data directory."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication


def make_receipt(path: Path, title: str, subtitle: str, tone: str = "photo") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(720, 480, QImage.Format.Format_RGB32)
    image.fill(QColor("#F4F5F7"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    card = QRect(60, 48, 600, 384)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(card, 18, 18)

    accent = {"photo": "#FFD8A8", "pay": "#B7E4C7", "invoice": "#FFC9C9"}.get(tone, "#D0EBFF")
    painter.setBrush(QColor(accent))
    painter.drawRoundedRect(QRect(96, 96, 528, 132), 14, 14)
    painter.setPen(QColor("#1D1D1F"))
    font = QFont("Microsoft YaHei UI", 26)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(120, 118, 480, 48), Qt.AlignmentFlag.AlignLeft, title)
    painter.setPen(QColor("#6E6E73"))
    painter.setFont(QFont("Microsoft YaHei UI", 16))
    painter.drawText(QRect(120, 170, 480, 40), Qt.AlignmentFlag.AlignLeft, subtitle)

    painter.setPen(QColor("#D2D2D7"))
    for index in range(4):
        y = 268 + index * 34
        painter.drawLine(120, y, 468, y)
    painter.setPen(QColor("#8E8E93"))
    painter.setFont(QFont("Microsoft YaHei UI", 13))
    painter.drawText(QRect(120, 396, 480, 24), Qt.AlignmentFlag.AlignLeft, "演示图片 · 仅用于界面评审")
    painter.end()
    image.save(str(path))


def main(root: Path) -> None:
    app = QApplication.instance() or QApplication([])
    db_path = root / "data" / "app.db"
    archive = root / "data" / "archive"
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    for table in ("attachments", "material_requirements", "items", "reimbursement_batches"):
        cursor.execute(f"DELETE FROM {table}")
    connection.commit()

    material_types = {
        row[2]: row[0]
        for row in cursor.execute("SELECT id, name, code FROM material_types")
    }
    required_codes = ["physical_photo", "payment_screenshot", "invoice", "order_screenshot"]

    batches = [
        ("实验耗材报销", "collecting", date(2026, 10, 12), None),
        ("差旅与会议", "submitted", date(2026, 8, 20), date(2026, 8, 26)),
        ("办公用品", "reimbursed", date(2026, 6, 8), date(2026, 6, 15)),
    ]

    items_plan = [
        # batch index, name, merchant, platform, order, qty, unit cents, status, has codes
        (0, "树莓派 Zero 2 W", "树莓派旗舰店", "淘宝", "TB20261005001", 1, 36500, "collecting", ["physical_photo", "physical_photo", "payment_screenshot", "order_screenshot"]),
        (0, "HDMI 转接头", "绿联京东自营", "京东", "JD20261007008", 2, 1995, "collecting", ["physical_photo"]),
        (0, "PCB 加工费", "嘉立创", "官网", "JLC-2026-1003", 1, 82000, "collecting", ["invoice", "payment_screenshot"]),
        (0, "杜邦线套装", "元件批发", "淘宝", "TB20261010012", 1, 1250, "collecting", []),
        (1, "高铁车票 北京-上海", "中国铁路", "12306", "E123456789", 1, 55300, "submitted", ["physical_photo", "payment_screenshot", "invoice", "order_screenshot"]),
        (1, "会议注册费", "中国仪器仪表学会", "官网", "CIS-2026-0812", 1, 120000, "submitted", ["physical_photo", "payment_screenshot", "invoice", "order_screenshot"]),
        (2, "打印纸 A4 一箱", "得力办公", "京东", "JD20260601003", 1, 8990, "reimbursed", ["physical_photo", "payment_screenshot", "invoice", "order_screenshot"]),
        (2, "显示器支架", "北弧旗舰店", "天猫", "TM20260603021", 1, 19900, "reimbursed", ["physical_photo", "payment_screenshot", "invoice", "order_screenshot"]),
    ]

    batch_ids: list[int] = []
    for name, status, created, submitted in batches:
        cursor.execute(
            """
            INSERT INTO reimbursement_batches
                (name, status, reimburser, project_name, submitted_at, reimbursed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                status,
                "赵翰卿",
                "纳米颗粒检测",
                submitted.isoformat() + " 10:00:00" if submitted else None,
                submitted.isoformat() + " 10:00:00" if submitted and status == "reimbursed" else None,
                created.isoformat() + " 09:00:00",
                created.isoformat() + " 09:00:00",
            ),
        )
        batch_ids.append(int(cursor.lastrowid))

    counters: dict[int, int] = {index: 0 for index in range(len(batches))}
    for plan in items_plan:
        batch_index, name, merchant, platform, order, qty, unit, status, codes = plan
        counters[batch_index] += 1
        sequence = counters[batch_index]
        batch_name = batches[batch_index][0]
        batch_date = batches[batch_index][2]
        cursor.execute(
            """
            INSERT INTO items
                (batch_id, sequence_number, name, purchase_date, merchant, platform, order_number,
                 quantity, unit_price_cents, total_amount_cents, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_ids[batch_index],
                sequence,
                name,
                batch_date.isoformat(),
                merchant,
                platform,
                order,
                qty,
                unit,
                unit * qty,
                status,
                None,
                batch_date.isoformat() + " 09:30:00",
                batch_date.isoformat() + " 09:30:00",
            ),
        )
        item_id = int(cursor.lastrowid)

        for order_index, code in enumerate(required_codes, start=1):
            cursor.execute(
                "INSERT INTO material_requirements (item_id, material_type_id, required, sort_order, created_at, updated_at)"
                " VALUES (?, ?, 1, ?, datetime('now'), datetime('now'))",
                (item_id, material_types[code], order_index),
            )

        label = {"physical_photo": "实物图", "payment_screenshot": "支付截图", "invoice": "发票", "order_screenshot": "订单截图"}
        batch_dir = f"{batch_date:%Y-%m}_{batch_name}"
        item_dir = f"{sequence:03d}_{name.replace('/', '-')}"
        per_code_index: dict[str, int] = {}
        for code in codes:
            per_code_index[code] = per_code_index.get(code, 0) + 1
            index = per_code_index[code]
            extension = ".pdf" if code == "invoice" else ".png"
            stored = f"{sequence:03d}_{name.replace('/', '-')}_{label[code]}_{index:02d}{extension}"
            relative = f"{batch_dir}/{item_dir}/{stored}"
            target = archive / Path(relative)
            if extension == ".png":
                make_receipt(target, f"{name} {label[code]}", f"{order} · #{index}", tone={"physical_photo": "photo", "payment_screenshot": "pay", "invoice": "invoice"}.get(code, "photo"))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"%PDF-1.4\n% demo invoice\n%%EOF\n")
            payload = target.read_bytes()
            cursor.execute(
                """
                INSERT INTO attachments
                    (item_id, material_type_id, original_filename, stored_filename, relative_path,
                     file_extension, file_size, sha256, health, is_derived, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', 0, datetime('now'), datetime('now'))
                """,
                (
                    item_id,
                    material_types[code],
                    stored,
                    stored,
                    relative,
                    extension,
                    len(payload),
                    hashlib.sha256(payload + name.encode()).hexdigest(),
                ),
            )

    connection.commit()
    connection.close()
    print("seeded", root)


if __name__ == "__main__":
    import sys

    main(Path(sys.argv[1]))
