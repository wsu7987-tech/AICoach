"""Generate the distributable workbook without a database or model invocation."""

from pathlib import Path

from app.services.evaluation.workbook import make_workbook


def main():
    destination = Path(__file__).resolve().parents[2] / "assets" / "AI_Coach_批量评测模板.xlsx"
    destination.write_bytes(make_workbook())
    print(f"Generated: {destination}")


if __name__ == "__main__":
    main()
