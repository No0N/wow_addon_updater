"""
ElvUI Updater — точка входа приложения.
Запуск: python main.py
Сборка exe: pyinstaller build.spec (или см. README).
"""
from gui import run_app


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
