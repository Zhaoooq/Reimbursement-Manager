from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage, QPainter


class ImageMergeError(ValueError):
    """Raised when a source image cannot be merged into a PNG."""


class ImageMergeService:
    """Create a top-aligned, side-by-side PNG without changing its sources."""

    def merge(
        self,
        *,
        order_image_path: Path,
        payment_image_path: Path,
        output_path: Path,
    ) -> Path:
        order_image = self._load_image(Path(order_image_path))
        payment_image = self._load_image(Path(payment_image_path))
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        merged = QImage(
            order_image.width() + payment_image.width(),
            max(order_image.height(), payment_image.height()),
            QImage.Format.Format_ARGB32,
        )
        merged.fill("white")
        painter = QPainter(merged)
        try:
            painter.drawImage(0, 0, order_image)
            painter.drawImage(order_image.width(), 0, payment_image)
        finally:
            painter.end()

        # The visual pixels remain identical, while the output name keeps
        # repeated user-requested generations distinct under SHA256 tracking.
        merged.setText("reimbursement_manager_output", output.name)
        if not merged.save(str(output), "PNG"):
            raise ImageMergeError(f"Unable to write merged PNG: {output}")
        return output

    @staticmethod
    def _load_image(path: Path) -> QImage:
        image = QImage(str(path))
        if image.isNull():
            raise ImageMergeError(
                f"Current attachment is not a readable JPG/PNG image: {path.name}"
            )
        return image
