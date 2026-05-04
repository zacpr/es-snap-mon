"""Entry point for es-snap-mon."""
from .app import App


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()
