def main() -> None:
    try:
        from mediaporter_app.gui import run
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            raise SystemExit("Missing dependency: PySide6. Run 'pip install -r requirements.txt'.") from exc
        raise

    run()


if __name__ == "__main__":
    main()
